"""E08-T04 ACs end to end: fake WS transport -> ConnectionManager -> B13 chart -> bus.

Fake clock (sleep advances it), no network, no wall-clock sleeps.
"""

from __future__ import annotations

import asyncio
import json
import random

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.bybit.public_ws import topic_kind
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.watchdog import StalenessWatchdog


class _Clock:
    t = 0.0

    def __call__(self) -> float:
        return self.t


class _Sock:
    """Frozen socket: accepts subscribes, never delivers a frame."""

    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.closed = False
        self._never: asyncio.Event = asyncio.Event()

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))

    async def recv(self, max_bytes: int) -> str:
        await self._never.wait()
        return ""

    async def close(self) -> None:
        self.closed = True


def _drain(sub: object) -> list[tuple[str, str]]:
    q = sub.queue  # type: ignore[attr-defined]
    out: list[tuple[str, str]] = []
    while not q.empty():
        ev = q.get_nowait()
        out.append((ev.topic, ev.state))
    return out


async def _spin(pred: object, n: int = 3000) -> None:
    for _ in range(n):
        if pred():  # type: ignore[operator]
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not reached")


async def test_frozen_book_socket_publishes_stale_then_recycles() -> None:
    clk, bus, socks = _Clock(), Bus(), []
    sub = bus.subscribe("t", "*.health.*.*", QueuePolicy.NEVER_DROP)

    async def connect() -> _Sock:
        socks.append(_Sock())
        return socks[-1]

    async def sleep(s: float) -> None:
        clk.t += s
        await asyncio.sleep(0)

    m = ConnectionManager(
        connect,
        SubscriptionPlanner(),
        StalenessWatchdog(clk, lambda _e: None, kind_of=topic_kind),
        ReconnectPolicy(rng=random.Random(1)),  # noqa: S311  (deterministic jitter)
        ConnectionRateGuard(clk),
        lambda _f: None,
        sleep=sleep,
        bus=bus,
        ping_interval_s=1000.0,
    )
    m.set_desired({"orderbook.50.BTCUSDT"})
    await m.start()
    await _spin(lambda: len(socks) >= 2 and bool(socks[1].sent) and m.state() == "open")
    seen = _drain(sub)
    assert ("orderbook.50.BTCUSDT", "stale") in seen
    states = [s for _, s in seen]
    assert states.index("stale") < states.index("resubscribing") < len(states)
    assert socks[0].closed
    await m.stop()


async def test_reconnect_storm_capped_and_reported_degraded() -> None:
    clk, bus, opens = _Clock(), Bus(), [0]
    dial_at: list[float] = []
    sub = bus.subscribe("t", "*.health.*.*", QueuePolicy.NEVER_DROP, maxsize=10_000)

    async def connect() -> _Sock:
        opens[0] += 1
        dial_at.append(clk.t)
        raise OSError("refused")

    async def sleep(s: float) -> None:
        clk.t += s
        await asyncio.sleep(0)

    guard = ConnectionRateGuard(clk, limit=5, window_s=300.0)
    m = ConnectionManager(
        connect,
        SubscriptionPlanner(),
        StalenessWatchdog(clk, lambda _e: None, kind_of=topic_kind),
        ReconnectPolicy(rng=random.Random(2)),  # noqa: S311
        guard,
        lambda _f: None,
        sleep=sleep,
        bus=bus,
        budget_recheck_s=1.0,
    )
    m.set_desired({"tickers.BTCUSDT"})
    await m.start()
    await _spin(lambda: opens[0] >= 20)
    # AC: the storm is spread so no 300 s window ever holds more than the cap.
    for t in dial_at:
        assert sum(1 for x in dial_at if t - 300.0 + 1e-6 < x <= t) <= 5
    assert m.state() in {"degraded", "connecting"}
    assert ("tickers.BTCUSDT", "degraded") in _drain(sub)
    await m.stop()
    assert m.state() == "closed"
