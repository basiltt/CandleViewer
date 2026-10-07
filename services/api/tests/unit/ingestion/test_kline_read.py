"""E12-S05 read path: cache-first, cold-tier read-through, non-blocking backfill, `meta.sources`
/ `meta.recording_started_at`, and cross-check discrepancy logging. Fakes only, no network."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
import structlog

from candleviewer.exchange.base.models import KlineEvent
from candleviewer.ingestion.kline_backfill import KlineBackfillService
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_crosscheck import cross_check
from candleviewer.ingestion.kline_read import KlineReadService
from candleviewer.ingestion.metrics import kline_crosscheck_divergence_total

SYM, IV = "BTCUSDT", "5"
W = 300_000_000


@dataclass
class _Row:
    ts_us: int
    source: str = "tape"
    confirmed: bool = True
    open: str = "100"
    high: str = "101"
    low: str = "99"
    close: str = "100"
    volume: str = "1"
    turnover: str = "100"


@dataclass
class _Hot:
    rows: dict[int, _Row] = field(default_factory=dict)
    reads: int = 0

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto"
    ) -> Sequence[_Row]:
        self.reads += 1
        return [r for t, r in sorted(self.rows.items()) if rng.start_us <= t < rng.end_us]

    async def write_klines(self, rows: Sequence[object]) -> None:
        for row in rows:
            assert isinstance(row, dict)
            self.rows[int(row["ts_us"])] = _Row(int(row["ts_us"]), source=str(row["source"]))


def _k(start: int) -> KlineEvent:
    return KlineEvent.model_validate(
        dict(event_id="00000000-0000-7000-8000-000000000001", ts_event=start, ts_ingest=start,
             source="backfill", symbol=SYM, interval=IV, start=start, end=start + W - 1,
             open="100", high="101", low="99", close="100", volume="1", turnover="100",
             confirmed=True)
    )  # fmt: skip


class _Port:
    def __init__(self, n: int) -> None:
        self.bars = [_k(i * W) for i in range(n)]
        self.calls = 0
        self.release = asyncio.Event()
        self.release.set()

    async def __call__(
        self, symbol: str, interval: str, start: int, end: int, limit: int = 1000
    ) -> Sequence[KlineEvent]:
        self.calls += 1
        await self.release.wait()
        return [b for b in self.bars if start <= b.start <= end][-limit:]


def _svc(hot: _Hot, port: _Port, **kw: object) -> tuple[KlineReadService, KlineBackfillService]:
    bf = KlineBackfillService(fetch_klines=port, cache=hot)
    return KlineReadService(hot, backfill=bf, **kw), bf  # type: ignore[arg-type]


async def test_cache_hit_served_locally_without_exchange_call() -> None:
    hot = _Hot({i * W: _Row(i * W) for i in range(10)})
    port = _Port(10)
    svc, _ = _svc(hot, port, recording_started_at_us=lambda s: 0)
    read = await svc.read(SYM, IV, Range(0, 10 * W))
    assert port.calls == 0 and not read.backfilling and read.holes == []
    assert len(read.rows) == 10 and read.sources == ["questdb"]
    assert read.recording_started_at_us == 0


async def test_tail_only_fetch_and_first_page_served_while_backfill_continues() -> None:
    hot = _Hot({i * W: _Row(i * W) for i in range(5)})
    port = _Port(8)
    port.release.clear()
    svc, bf = _svc(hot, port)
    read = await svc.read(SYM, IV, Range(0, 8 * W))
    # Interactive now: stored bars returned, tail backfill running in the background.
    assert len(read.rows) == 5 and read.backfilling
    assert read.holes == [Range(5 * W, 8 * W)]
    assert read.sources == ["questdb", "exchange_rest"]
    port.release.set()
    task = bf._jobs[(SYM, IV)]
    result = await task
    assert [e.start for e in result.fetched] == [5 * W, 6 * W, 7 * W]
    again = await svc.read(SYM, IV, Range(0, 8 * W))
    assert len(again.rows) == 8 and port.calls == 1 and not again.backfilling
    assert "exchange_rest" in again.sources  # rest-sourced rows are now in the window


async def test_cold_tier_read_through_for_window_older_than_hot_retention() -> None:
    hot = _Hot({i * W: _Row(i * W) for i in range(5, 10)})
    cold_calls: list[Range] = []

    async def cold(sym: str, interval: str, rng: Range) -> Sequence[_Row]:
        cold_calls.append(rng)
        return [_Row(i * W, source="parquet") for i in range(5) if rng.start_us <= i * W]

    svc, _ = _svc(hot, _Port(10), cold=cold, hot_boundary_us=lambda: 5 * W)
    read = await svc.read(SYM, IV, Range(0, 10 * W))
    assert cold_calls == [Range(0, 5 * W)]
    assert [r.ts_us for r in read.rows] == [i * W for i in range(10)]
    assert read.sources == ["parquet", "questdb"]


async def test_window_entirely_cold_never_backfills() -> None:
    async def cold(sym: str, interval: str, rng: Range) -> Sequence[_Row]:
        return []

    port = _Port(5)
    svc, _ = _svc(_Hot(), port, cold=cold, hot_boundary_us=lambda: 100 * W)
    read = await svc.read(SYM, IV, Range(0, 5 * W))
    assert read.rows == [] and read.sources == [] and port.calls == 0


async def test_backfill_window_is_bounded_and_month_interval_never_backfills() -> None:
    port = _Port(0)
    svc, bf = _svc(_Hot(), port, max_backfill_bars=10)
    read = await svc.read(SYM, IV, Range(0, 1_000 * W))
    assert read.holes == [Range(990 * W, 1_000 * W)]
    await bf._jobs[(SYM, IV)]
    month = await svc.read(SYM, "M", Range(0, 1_000 * W))
    assert month.holes == [] and not month.backfilling


async def test_read_without_backfill_service_is_cache_only() -> None:
    svc = KlineReadService(_Hot({0: _Row(0, source="kline")}))
    read = await svc.read(SYM, IV, Range(0, W))
    assert read.sources == ["questdb", "exchange_rest"] and read.recording_started_at_us is None


@dataclass
class _Bar:
    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


def _bar(t: int, **kw: str) -> _Bar:
    base = {"open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}
    base.update(kw)
    return _Bar(t, **{k: Decimal(v) for k, v in base.items()})


def test_cross_check_logs_and_counts_divergence_beyond_tolerance() -> None:
    before = kline_crosscheck_divergence_total.labels(symbol=SYM, interval=IV)._value.get()
    klines = [_k(0), _k(W), _k(2 * W), _k(3 * W)]
    tape = [_bar(0), _bar(W, high="101.5"), _bar(2 * W, volume="1.0005"), _bar(9 * W)]
    with structlog.testing.capture_logs() as logs:
        out = cross_check(SYM, IV, klines, tape, tick_size=Decimal("0.1"))
    assert [(d.ts_us, d.fields) for d in out] == [(W, ("high",))]
    after = kline_crosscheck_divergence_total.labels(symbol=SYM, interval=IV)._value.get()
    assert after == before + 1
    ev = [e for e in logs if e["event"] == "kline_crosscheck_divergence"]
    assert ev and ev[0]["symbol"] == SYM and ev[0]["interval"] == IV and ev[0]["ts_us"] == W


@pytest.mark.parametrize(
    ("kw", "ticks", "fields"),
    [
        ({"close": "100.1"}, 1, ()),
        ({"close": "100.2"}, 1, ("close",)),
        ({"volume": "2"}, 0, ("volume",)),
        ({"volume": "0"}, 0, ("volume",)),
    ],
)
def test_cross_check_tolerance(kw: dict[str, str], ticks: int, fields: tuple[str, ...]) -> None:
    out = cross_check(
        SYM, IV, [_k(0)], [_bar(0, **kw)], tick_size=Decimal("0.1"), price_ticks=ticks
    )
    assert (out[0].fields if out else ()) == fields


def test_cross_check_no_overlap_or_zero_volume_is_not_a_divergence() -> None:
    zero = _k(0).model_copy(update={"volume": Decimal(0)})
    assert cross_check(SYM, IV, [zero], [_bar(0, volume="0")]) == []
    assert cross_check(SYM, IV, [_k(W)], [_bar(0)]) == []


@pytest.mark.perf
async def test_cache_hit_5000_bars_median_read_within_300ms_budget() -> None:
    """US-MKT-008: <=300 ms for a 5 000-bar cache hit (code-path overhead; median of 5, and
    the hit is asserted to make zero exchange calls so it is not a backfill in disguise)."""
    import statistics
    import time

    hot = _Hot({i * W: _Row(i * W) for i in range(5_000)})
    port = _Port(5_000)
    svc, _ = _svc(hot, port)
    samples = []
    for _ in range(5):
        t0 = time.perf_counter()
        read = await svc.read(SYM, IV, Range(0, 5_000 * W))
        samples.append((time.perf_counter() - t0) * 1000)
        assert len(read.rows) == 5_000
    assert port.calls == 0
    assert statistics.median(samples) <= 300.0
