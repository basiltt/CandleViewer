"""`ConnectionManager`: one reader task per socket, dedicated ping task,
staleness-driven recycling under backoff and the connection-rate guard (E08-T04).

Transport is injected (`SocketFactory`) so tests use a fake server. The B13
`ws_conn` binding is still the E50-S02 stub; driving this lifecycle through
`statechart.factory` is listed under the PR's Deviations.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol

import structlog

from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.watchdog import StalenessWatchdog, ping_loop
from candleviewer.observability.context import spawn

logger = structlog.get_logger(__name__)


class ConnectionState(StrEnum):
    CONNECTING = "connecting"
    OPEN = "open"
    DEGRADED = "degraded"
    CLOSED = "closed"


class Socket(Protocol):
    async def send(self, frame: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


SocketFactory = Callable[[], Awaitable[Socket]]
Sleep = Callable[[float], Awaitable[None]]


class ConnectionManager:
    def __init__(
        self,
        factory: SocketFactory,
        planner: SubscriptionPlanner,
        watchdog: StalenessWatchdog,
        policy: ReconnectPolicy,
        guard: ConnectionRateGuard,
        on_message: Callable[[str], None],
        *,
        sleep: Sleep = asyncio.sleep,
        ping_interval_s: float = 20.0,
        check_interval_s: float = 0.5,
    ) -> None:
        self._factory = factory
        self._planner = planner
        self._watchdog = watchdog
        self._policy = policy
        self._guard = guard
        self._on_message = on_message
        self._sleep = sleep
        self._ping_interval = ping_interval_s
        self._check_interval = check_interval_s
        self._state = ConnectionState.CLOSED
        self._desired: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._attempt = 0
        self.opens = 0

    def state(self) -> ConnectionState:
        return self._state

    def set_desired(self, topics: set[str]) -> None:
        for gone in self._desired - topics:
            self._watchdog.unwatch(gone)
        for new in topics - self._desired:
            self._watchdog.watch(new)
        self._desired = set(topics)

    async def start(self) -> None:
        if self._task is None:
            self._state = ConnectionState.CONNECTING
            self._task = spawn(self._run(), name="ws-connection")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._state = ConnectionState.CLOSED

    async def _run(self) -> None:
        while True:
            delay = self._guard.reserve()
            if delay > 0:
                self._state = ConnectionState.DEGRADED
                await self._sleep(delay)
            self._state = ConnectionState.CONNECTING
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception:  # any transport failure -> backoff
                logger.warning("ws_session_failed", attempt=self._attempt, exc_info=True)
            self._state = ConnectionState.DEGRADED
            self._attempt += 1
            await self._sleep(self._policy.next_delay(self._attempt))

    async def _session(self) -> None:
        sock = await self._factory()
        self.opens += 1
        try:
            for batch in self._planner.plan(self._desired):
                await sock.send(json.dumps({"op": "subscribe", "args": list(batch.topics)}))
            self._watchdog.reset()
            self._state = ConnectionState.OPEN
            self._attempt = 0

            async def ping() -> None:
                await sock.send(json.dumps({"op": "ping"}))

            tasks = [
                spawn(ping_loop(ping, self._sleep, interval_s=self._ping_interval), name="ws-ping"),
                spawn(self._read(sock), name="ws-reader"),
                spawn(self._watch(), name="ws-watchdog"),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            for t in done:
                if not t.cancelled() and (exc := t.exception()) is not None:
                    raise exc
        finally:
            await sock.close()

    async def _read(self, sock: Socket) -> None:
        while True:
            self._on_message(await sock.recv())

    async def _watch(self) -> None:
        """Returns (ending the session -> recycle) once any topic goes stale."""
        while True:
            await self._sleep(self._check_interval)
            if self._watchdog.check():
                return
