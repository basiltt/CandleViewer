"""E08-T04: B13 `ws_conn` drives ConnectionManager end to end (fake server, bus)."""

from __future__ import annotations

import asyncio
import json
import random

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.watchdog import FeedHealthEvent, StalenessWatchdog


class _Clock:
    t = 0.0

    def __call__(self) -> float:
        return self.t


class _FakeServer:
    """Fake Bybit public server: records subscribes; a socket can be killed."""

    def __init__(self) -> None:
        self.sockets: list[_Sock] = []

    async def connect(self) -> _Sock:
        s = _Sock()
        self.sockets.append(s)
        return s


class _Sock:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.closed = False
        self.q: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))

    async def recv(self) -> str:
        item = await self.q.get()
        if item == "DROP":
            raise ConnectionResetError("server dropped")
        return item

    async def close(self) -> None:
        self.closed = True


async def _until(pred: object, n: int = 400) -> None:
    for _ in range(n):
        if pred():  # type: ignore[operator]
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not reached")


async def test_drop_reconnect_resubscribe_publishes_feed_health_on_bus() -> None:
    clk, server, bus = _Clock(), _FakeServer(), Bus()
    sub = bus.subscribe("t", "*.health.*.*", QueuePolicy.NEVER_DROP)
    health: list[FeedHealthEvent] = []

    async def sleep(s: float) -> None:
        clk.t += s
        await asyncio.sleep(0)

    m = ConnectionManager(
        server.connect,
        SubscriptionPlanner(),
        StalenessWatchdog(clk, health.append),
        ReconnectPolicy(rng=random.Random(7)),  # noqa: S311
        ConnectionRateGuard(clk),
        lambda _m: None,
        sleep=sleep,
        bus=bus,
    )
    topics = {"tickers.BTCUSDT", "publicTrade.BTCUSDT"}
    m.set_desired(topics)
    await m.start()
    await _until(lambda: m.state() == "open")
    server.sockets[0].q.put_nowait("DROP")
    await _until(lambda: len(server.sockets) == 2 and m.state() == "open")
    assert server.sockets[0].closed
    assert set(server.sockets[1].sent[0]["args"]) == topics  # type: ignore[call-overload]
    seen: list[str] = []
    while not sub.queue.empty():
        seen.append(sub.queue.get_nowait().state)
    assert "healthy" in seen and "degraded" in seen and "resubscribing" in seen
    assert seen.index("degraded") < seen.index("resubscribing")
    await m.stop()
    assert m.state() == "closed"
