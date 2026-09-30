"""Runtime, self-reverting log-level overrides (E04-T02, US-OBS-003).

Scoped to a closed set of subsystem namespaces (never the root logger).
Deadlines use a monotonic clock and are enforced by `tick()`, driven by a
5-second ticker, so a suspended process reverts on resume. Overrides are
deliberately NOT persisted: a restart simply has none.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from candleviewer.observability.context import spawn

Subsystem = Literal["ingestion", "oms", "rules", "recorder", "api", "ws"]
Level = Literal["debug", "info", "warning", "error", "critical"]

MAX_TTL_SECONDS: Final[int] = 3600
DEFAULT_TTL_SECONDS: Final[int] = 900
TICK_INTERVAL_S: Final[float] = 5.0
#: Logger namespaces per subsystem (`cv.*` per the ticket; `candleviewer.*`
#: is what `logging.getLogger(__name__)` call sites actually use).
_NAMESPACE_ROOTS: Final[tuple[str, ...]] = ("cv", "candleviewer")


class LogLevelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subsystem: Subsystem
    level: Level
    ttl_seconds: int = Field(default=DEFAULT_TTL_SECONDS, ge=1, le=MAX_TTL_SECONDS)


class SystemEventSink(Protocol):
    async def record(self, *, component: str, kind: str, detail: dict[str, object]) -> None: ...


@dataclass
class _Override:
    previous: dict[str, int]
    deadline: float
    level: str


def _logger_names(subsystem: str) -> list[str]:
    return [f"{root}.{subsystem}" for root in _NAMESPACE_ROOTS]


class LogLevelOverrides:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sink: SystemEventSink | None = None,
    ) -> None:
        self._clock = clock
        self._sink = sink
        self._active: dict[str, _Override] = {}
        self._ticker: asyncio.Task[None] | None = None

    @property
    def active_count(self) -> int:
        """Backs the `log_level_overrides_active` gauge."""
        return len(self._active)

    async def apply(self, req: LogLevelRequest) -> None:
        numeric = getattr(logging, req.level.upper())
        existing = self._active.get(req.subsystem)
        previous = existing.previous if existing else {}
        for name in _logger_names(req.subsystem):
            lg = logging.getLogger(name)
            previous.setdefault(name, lg.level)
            lg.setLevel(numeric)
        self._active[req.subsystem] = _Override(
            previous=previous, deadline=self._clock() + req.ttl_seconds, level=req.level
        )
        await self._emit("set", req.subsystem, {"level": req.level, "ttl_seconds": req.ttl_seconds})

    async def tick(self) -> None:
        now = self._clock()
        for subsystem in [s for s, o in self._active.items() if o.deadline <= now]:
            await self.revert(subsystem, reason="expired")

    async def revert(self, subsystem: str, *, reason: str = "expired") -> None:
        override = self._active.pop(subsystem, None)
        if override is None:
            return
        for name, level in override.previous.items():
            logging.getLogger(name).setLevel(level)
        await self._emit(reason, subsystem, {"restored": True})

    def start(self) -> None:
        if self._ticker is None:
            self._ticker = spawn(self._run(), name="log-level-ticker")

    async def stop(self) -> None:
        if self._ticker is not None:
            self._ticker.cancel()
            try:
                await self._ticker
            except asyncio.CancelledError:
                pass
            self._ticker = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(TICK_INTERVAL_S)
            await self.tick()

    async def _emit(self, phase: str, subsystem: str, extra: dict[str, object]) -> None:
        if self._sink is not None:
            await self._sink.record(
                component="api",
                kind="log_level_override",
                detail={"phase": phase, "subsystem": subsystem, **extra},
            )
