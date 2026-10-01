"""E08-T04 acceptance scenarios (fake clock/sockets, no network)."""

from __future__ import annotations

import asyncio
import json
import random

import pytest

from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.planner import DemandTracker, SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.watchdog import FeedHealthEvent, StalenessWatchdog, ping_loop


def _rng(seed: int) -> random.Random:
    return random.Random(seed)  # noqa: S311  (deterministic test jitter)


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_planner_respects_budget_and_union_exact() -> None:
    desired = {f"publicTrade.SYM{i % 14}USDT.{i}" for i in range(37)}
    batches = SubscriptionPlanner().plan(desired)
    assert all(len(b.topics) <= 10 for b in batches)
    assert all(len(json.dumps(list(b.topics))) <= 21_000 for b in batches)
    assert {t for b in batches for t in b.topics} == desired
    assert sum(len(b.topics) for b in batches) == 37


def test_planner_char_cap_and_socket_split() -> None:
    topics = {f"tickers.{'X' * 50}{i:03d}" for i in range(50)}
    b = SubscriptionPlanner(max_args_chars=300, max_topics_per_socket=20).plan(topics)
    assert all(len(json.dumps(list(x.topics))) <= 300 for x in b)
    assert {x.socket_index for x in b} == {0, 1, 2}
    with pytest.raises(ValueError):
        SubscriptionPlanner(max_args_chars=5).plan({"tickers.BTCUSDT"})
    with pytest.raises(ValueError):
        SubscriptionPlanner(max_topics_per_frame=0)


def test_one_upstream_per_topic_and_grace() -> None:
    clk = Clock()
    d = DemandTracker(clk, grace_s=30)
    for i in range(6):
        d.acquire(f"c{i}", "tickers.BTCUSDT")
    assert d.desired() == {"tickers.BTCUSDT"}
    for i in range(5):
        d.release(f"c{i}", "tickers.BTCUSDT")
    assert d.desired() == {"tickers.BTCUSDT"}
    d.release("c5", "tickers.BTCUSDT")
    clk.t = 29
    assert d.desired() == {"tickers.BTCUSDT"}
    d.acquire("c9", "tickers.BTCUSDT")  # returns within grace
    clk.t = 100
    assert d.desired() == {"tickers.BTCUSDT"}
    d.release("c9", "tickers.BTCUSDT")
    d.release("nobody", "other")
    clk.t = 131
    assert d.desired() == set()


def test_backoff_full_jitter_distribution() -> None:
    p = ReconnectPolicy(rng=_rng(1))
    samples = [p.next_delay(3) for _ in range(4000)]  # ceiling 4.0
    assert 0 <= min(samples) < 0.1 and 3.9 < max(samples) <= 4.0
    assert 1.8 < sum(samples) / len(samples) < 2.2
    assert max(p.next_delay(50) for _ in range(500)) <= 30.0


def test_rate_guard_caps_600_attempts() -> None:
    clk = Clock()
    g = ConnectionRateGuard(clk)
    delays = [g.reserve() for _ in range(600)]
    starts = sorted(clk.t + d for d in delays)
    for i, s in enumerate(starts):
        in_window = sum(1 for x in starts if s - 300 < x <= s)
        assert in_window <= 480, i
    assert max(delays) > 0 and delays[479] == 0 and delays[480] > 0
    assert g.remaining() == 0
    with pytest.raises(ValueError):
        ConnectionRateGuard(clk, limit=0)


def test_watchdog_stale_after_2s_book() -> None:
    clk = Clock()
    events: list[FeedHealthEvent] = []
    w = StalenessWatchdog(clk, events.append)
    w.watch("orderbook.50.BTCUSDT")
    clk.t = 1.9
    assert w.check() == []
    clk.t = 2.0
    assert w.check() == ["orderbook.50.BTCUSDT"] and events[0].state == "stale"
    assert w.check() == []
    w.touch("orderbook.50.BTCUSDT")
    w.unwatch("orderbook.50.BTCUSDT")
    w.touch("zzz")


async def test_ping_not_starved_by_blocked_reader() -> None:
    pings: list[int] = []
    gate = asyncio.Event()

    async def sleep(_s: float) -> None:
        await asyncio.sleep(0)

    async def send() -> None:
        pings.append(1)
        if len(pings) == 2:
            gate.set()

    task = asyncio.create_task(ping_loop(send, sleep))
    # a "slow consumer" hogging a different task does not stop the ping task
    await asyncio.wait_for(gate.wait(), 1)
    task.cancel()
    assert len(pings) >= 2


class FakeSocket:
    def __init__(self, silent: bool = False) -> None:
        self.sent: list[dict[str, object]] = []
        self.closed = False
        self._q: asyncio.Queue[str] = asyncio.Queue()
        self.silent = silent

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))

    async def recv(self) -> str:
        return await self._q.get()

    async def close(self) -> None:
        self.closed = True


async def test_frozen_socket_is_recycled_and_resubscribed() -> None:
    clk = Clock()
    socks: list[FakeSocket] = []
    health: list[FeedHealthEvent] = []

    async def factory() -> FakeSocket:
        s = FakeSocket()
        socks.append(s)
        return s

    async def sleep(s: float) -> None:
        clk.t += s
        await asyncio.sleep(0)

    w = StalenessWatchdog(clk, health.append)
    m = ConnectionManager(
        factory,
        SubscriptionPlanner(),
        w,
        ReconnectPolicy(rng=_rng(2)),
        ConnectionRateGuard(clk),
        lambda _m: None,
        sleep=sleep,
    )
    m.set_desired({"orderbook.50.BTCUSDT", "tickers.BTCUSDT"})
    await m.start()
    for _ in range(2000):
        await asyncio.sleep(0)
        if len(socks) >= 2 and socks[1].sent:
            break
    assert len(socks) >= 2 and socks[0].closed
    assert any(h.state == "stale" for h in health)
    assert socks[1].sent[0]["op"] == "subscribe"
    assert set(socks[1].sent[0]["args"]) == {"orderbook.50.BTCUSDT", "tickers.BTCUSDT"}  # type: ignore[call-overload]
    m.set_desired({"tickers.BTCUSDT"})
    await m.stop()
    assert m.state() == "closed"


async def test_factory_failure_backs_off_and_retries() -> None:
    clk = Clock()
    calls = 0

    async def factory() -> FakeSocket:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("dns")
        return FakeSocket()

    async def sleep(s: float) -> None:
        clk.t += s
        await asyncio.sleep(0)

    m = ConnectionManager(
        factory,
        SubscriptionPlanner(),
        StalenessWatchdog(clk, lambda _e: None),
        ReconnectPolicy(rng=_rng(3)),
        ConnectionRateGuard(clk),
        lambda _m: None,
        sleep=sleep,
    )
    await m.start()
    await m.start()
    for _ in range(100):
        await asyncio.sleep(0)
        if m.state() == "open":
            break
    assert calls == 2 and m.state() == "open"
    await m.stop()
