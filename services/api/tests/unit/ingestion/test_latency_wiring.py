"""E04-T06: stage latency is recorded on the real ingestion publish path."""

from __future__ import annotations

import asyncio
import random

from candleviewer.app import create_app
from candleviewer.ingestion.synthetic_feed import SyntheticFeedGenerator, SyntheticFeedMetrics
from candleviewer.observability.latency import STAGE_BUCKETS, StageRecorder
from candleviewer.observability.metrics import Metrics


def test_create_app_attaches_recorder_to_ingestion() -> None:
    app = create_app()
    assert isinstance(app.state.app_context.ingestion.latency, StageRecorder)


async def test_publish_records_stage_histograms_with_clock_offset() -> None:
    m = Metrics("demo")
    hist = m.histogram("ingest_stage_seconds", "h", ("stage",), buckets=STAGE_BUCKETS, max_series=4)
    ticks = iter(range(1000, 100000, 3))
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)

    gen = SyntheticFeedGenerator(
        records=[object()],  # type: ignore[list-item]
        queue=queue,
        metrics=SyntheticFeedMetrics(m.registry),
        rate_hz=10,
        rng=random.Random(1),  # noqa: S311
        latency=StageRecorder(hist, 1),
        clock_offset_ms=lambda: 0,
        now_ms=lambda: next(ticks),
    )
    await gen._publish_one(object())  # type: ignore[arg-type]
    n = m.registry.get_sample_value(
        "ingest_stage_seconds_count", {"env": "demo", "stage": "fanout"}
    )
    assert n == 1
    ex = m.registry.get_sample_value(
        "ingest_stage_seconds_count", {"env": "demo", "stage": "exchange"}
    )
    assert ex == 1  # offset provider supplied -> exchange stage available


class _FrameSock:
    """Delivers one exchange frame then blocks (fake transport, no network)."""

    def __init__(self, frame: str) -> None:
        self._frames = [frame]
        self._never = asyncio.Event()

    async def send(self, frame: str) -> None:
        return None

    async def recv(self, max_bytes: int) -> str:
        if self._frames:
            return self._frames.pop()
        await self._never.wait()
        return ""

    async def close(self) -> None:
        return None


async def _ws_e2e(offset: int | None) -> tuple[Metrics, list[str]]:
    from candleviewer.exchange.bybit.public_ws import topic_kind
    from candleviewer.ingestion.connection import ConnectionManager
    from candleviewer.ingestion.planner import SubscriptionPlanner
    from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
    from candleviewer.ingestion.watchdog import StalenessWatchdog

    m = Metrics("demo")
    hist = m.histogram("ingest_stage_seconds", "h", ("stage",), buckets=STAGE_BUCKETS, max_series=4)
    clk = [0.0]
    stamps = iter([10_000, 10_002, 10_005])  # recv, decoded, published (ms)
    got: list[str] = []

    async def connect() -> _FrameSock:
        return _FrameSock('{"topic":"publicTrade.BTCUSDT","ts":9990,"data":[]}')

    async def sleep(s: float) -> None:
        clk[0] += s
        await asyncio.sleep(0)

    mgr = ConnectionManager(
        connect,
        SubscriptionPlanner(),
        StalenessWatchdog(lambda: clk[0], lambda _e: None, kind_of=topic_kind),
        ReconnectPolicy(rng=random.Random(1)),  # noqa: S311  (deterministic jitter)
        ConnectionRateGuard(lambda: clk[0]),
        got.append,
        sleep=sleep,
        ping_interval_s=1000.0,
        check_interval_s=1000.0,
        now_ms=lambda: next(stamps),
    )
    mgr.attach_latency(StageRecorder(hist, 1), lambda: offset)
    mgr.set_desired({"publicTrade.BTCUSDT"})
    await mgr.start()
    for _ in range(3000):
        if got:
            break
        await asyncio.sleep(0)
    await mgr.stop()
    return m, got


def _sum(m: Metrics, stage: str) -> float | None:
    return m.registry.get_sample_value("ingest_stage_seconds_sum", {"env": "demo", "stage": stage})


async def test_ws_frame_through_connection_manager_records_stages_with_offset() -> None:
    m, got = await _ws_e2e(offset=-5)  # exchange clock 5 ms behind local
    assert len(got) == 1
    assert _sum(m, "parse") == 0.002
    assert _sum(m, "fanout") == 0.003
    # t_recv - (t_exchange - offset) = 10000 - (9990 + 5) = 5 ms
    assert _sum(m, "exchange") == 0.005


async def test_ws_frame_unmeasured_offset_leaves_exchange_stage_unavailable() -> None:
    m, _ = await _ws_e2e(offset=None)
    n = m.registry.get_sample_value(
        "ingest_stage_seconds_count", {"env": "demo", "stage": "exchange"}
    )
    assert n in (None, 0.0)  # child pre-bound; never observed
    assert _sum(m, "parse") == 0.002


async def test_clock_guard_offset_feeds_ingestion_provider() -> None:
    from candleviewer.app import wire_clock_offset

    async def fetch() -> tuple[int, float, float]:
        raise AssertionError("unused")

    app = create_app()
    ctx = app.state.app_context
    guard = wire_clock_offset(ctx, fetch)  # type: ignore[arg-type]
    assert ctx.ingestion.clock_offset_ms() is None  # unmeasured => unavailable
    guard._offset_us, guard._last_measured_monotonic = 7_000, 1.0
    assert ctx.ingestion.clock_offset_ms() == 7


def test_wire_public_ws_attaches_clock_guard_and_closer() -> None:
    from candleviewer.app import build_app_context, wire_public_ws

    ctx = build_app_context()
    wire_public_ws(ctx)
    assert ctx.ingestion.clock is not None
    assert ctx.ingestion.clock_offset_ms() is None  # unmeasured -> exchange stage unavailable
    # E12-S05: kline backfill jobs are cancelled before the shared REST client is closed.
    assert len(ctx.ingestion._closers) == 2
    assert ctx.ingestion._closers[0].__qualname__ == "KlineBackfillService.aclose"
    assert ctx.ingestion.klines is not None
