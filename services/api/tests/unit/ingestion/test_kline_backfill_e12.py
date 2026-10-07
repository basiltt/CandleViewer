"""E12-S05 backfill hardening: SR-E12-08 ceilings, SR-E12-09 page rejection, rate-limit
backoff with jitter (fake sleep, no wall clock), `loading_older_bars`, one job per key,
background job before paging finishes, kline sink. No network, no database."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from candleviewer.domain.klines import KlinePageRejected
from candleviewer.exchange.base.errors import RateLimitError
from candleviewer.exchange.base.models import KlineEvent
from candleviewer.ingestion.kline_backfill import (
    MAX_PAGES_PER_JOB,
    STATUS_LOADING_OLDER,
    KlineBackfillService,
)
from candleviewer.ingestion.kline_coverage import Range

SYM, IV = "BTCUSDT", "1"
W = 60_000_000  # 1-minute bar, µs


def _k(start: int, confirmed: bool = True) -> KlineEvent:
    return KlineEvent(
        event_id="00000000-0000-7000-8000-000000000001",  # type: ignore[arg-type]
        ts_event=start, ts_ingest=start, source="backfill", symbol=SYM,
        interval=IV,  # type: ignore[arg-type]
        start=start, end=start + W - 1, open="100", high="101", low="99", close="100",  # type: ignore[arg-type]
        volume="1", turnover="100", confirmed=confirmed,  # type: ignore[arg-type]
    )  # fmt: skip


@dataclass
class _Row:
    ts_us: int
    confirmed: bool


@dataclass
class _Cache:
    rows: dict[int, _Row] = field(default_factory=dict)

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto"
    ) -> Sequence[_Row]:
        return [r for t, r in sorted(self.rows.items()) if rng.start_us <= t < rng.end_us]

    async def write_klines(self, rows: Sequence[object]) -> None:
        for row in rows:
            assert isinstance(row, dict)
            self.rows[int(row["ts_us"])] = _Row(int(row["ts_us"]), bool(row["confirmed"]))


class _Bybit:
    """Bybit-shaped port: the NEWEST `limit` bars of `[start, end]`, scripted errors first."""

    def __init__(self, n_bars: int, errors: Sequence[Exception] = ()) -> None:
        self.bars = [_k(i * W) for i in range(n_bars)]
        self.errors = list(errors)
        self.calls: list[tuple[int, int]] = []

    async def __call__(
        self, symbol: str, interval: str, start: int, end: int, limit: int = 1000
    ) -> Sequence[KlineEvent]:
        self.calls.append((start, end))
        if self.errors:
            raise self.errors.pop(0)
        inside = [b for b in self.bars if start <= b.start <= end]
        return inside[-limit:]


class _Sleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, s: float) -> None:
        self.calls.append(s)


def _svc(fetch: object, cache: _Cache | None = None, **kw: object) -> KlineBackfillService:
    return KlineBackfillService(
        fetch_klines=fetch, cache=cache or _Cache(), sleep=kw.pop("sleep", _Sleep()),  # type: ignore[arg-type]
        random_fn=lambda: 0.5, **kw,  # type: ignore[arg-type]
    )  # fmt: skip


def _rl() -> RateLimitError:
    return RateLimitError("rate limited", exchange_ret_code=10018)


async def test_backfill_pages_newest_first_until_window_covered_with_progress() -> None:
    progress: list[tuple[float, str]] = []
    port = _Bybit(2_500)
    svc = _svc(
        port,
        page_limit=1000,
        on_progress=lambda **kw: progress.append((kw["fraction"], kw["status"])),
    )
    result = await svc.backfill_range(SYM, IV, Range(0, 2_500 * W))
    assert not result.partial and result.pages == 3
    assert [e.start for e in result.fetched] == [i * W for i in range(2_500)]
    assert port.calls[0] == (0, 2_500 * W - 1)  # first page = newest 1000 (chart tail)
    fetching = [f for f, s in progress if s == "fetching"]
    assert len(fetching) == 3 and fetching == sorted(fetching)
    assert progress[-1] == (1.0, "done")


async def test_backfill_page_ceiling_stops_job_and_keeps_partial() -> None:
    port = _Bybit(50)
    svc = _svc(port, page_limit=10, max_pages=3)
    result = await svc.backfill_range(SYM, IV, Range(0, 50 * W))
    assert result.partial and result.stop_reason == "page_ceiling"
    assert len(port.calls) == 3 and len(result.fetched) == 30


def test_backfill_page_ceiling_cannot_be_raised_above_sr_e12_08() -> None:
    svc = _svc(_Bybit(1), max_pages=10_000)
    assert svc._max_pages == MAX_PAGES_PER_JOB == 400


async def test_backfill_rate_limit_backs_off_with_jitter_and_emits_loading_state() -> None:
    sleep, statuses = _Sleep(), []
    port = _Bybit(5, errors=[_rl(), _rl()])
    svc = _svc(port, sleep=sleep, on_progress=lambda **kw: statuses.append(kw["status"]))
    result = await svc.backfill_range(SYM, IV, Range(0, 5 * W))
    assert not result.partial and len(result.fetched) == 5
    # full jitter, random=0.5: 1 + (min(60, 2**n) - 1) * 0.5
    assert sleep.calls == [1.0, 1.5]
    assert statuses.count(STATUS_LOADING_OLDER) == 2


async def test_backfill_aborts_after_five_consecutive_rate_limits_keeping_partial() -> None:
    cache = _Cache()
    port = _Bybit(20)
    svc = _svc(port, cache, page_limit=10)
    await svc.backfill_range(SYM, IV, Range(10 * W, 20 * W))  # prior data
    port.errors = [_rl() for _ in range(5)]
    result = await svc.backfill_range(SYM, IV, Range(0, 20 * W))
    assert result.partial and result.stop_reason == "rate_limited"
    assert len(port.calls) == 1 + 5
    assert sorted(cache.rows) == [i * W for i in range(10, 20)]


async def test_backfill_rate_limit_counter_resets_after_a_good_page() -> None:
    port = _Bybit(30, errors=[_rl()] * 4)
    svc = _svc(port, page_limit=10)
    port_errors_after_first = [_rl()] * 4

    async def fetch(*a: object, **kw: object) -> Sequence[KlineEvent]:
        page = await port(*a, **kw)  # type: ignore[arg-type]
        if port_errors_after_first and not port.errors:
            port.errors, port_errors_after_first[:] = list(port_errors_after_first), []
        return page

    svc._fetch_klines = fetch
    result = await svc.backfill_range(SYM, IV, Range(0, 30 * W))
    assert not result.partial and len(result.fetched) == 30


async def test_backfill_bad_page_rejected_and_prior_pages_kept() -> None:
    cache = _Cache()
    port = _Bybit(30)
    page_no = 0

    async def fetch(*a: object, **kw: object) -> Sequence[KlineEvent]:
        nonlocal page_no
        page_no += 1
        if page_no == 2:
            raise KlinePageRejected("tampered", "high_below_body")
        return await port(*a, **kw)  # type: ignore[arg-type]

    result = await _svc(fetch, cache, page_limit=10).backfill_range(SYM, IV, Range(0, 30 * W))
    assert result.partial and result.stop_reason == "page_rejected"
    assert page_no == 2  # never retried
    assert sorted(cache.rows) == [i * W for i in range(20, 30)]


async def test_backfill_transient_errors_exhausted_is_fetch_failed() -> None:
    port = _Bybit(5, errors=[OSError("503")] * 3)
    result = await _svc(port, max_retries=3).backfill_range(SYM, IV, Range(0, 5 * W))
    assert result.partial and result.stop_reason == "fetch_failed"


class _Gate:
    """Port that blocks every call until released (to observe a job mid-flight)."""

    def __init__(self, n: int) -> None:
        self.inner = _Bybit(n)
        self.release = asyncio.Event()
        self.entered = asyncio.Event()

    async def __call__(self, *a: object, **kw: object) -> Sequence[KlineEvent]:
        self.entered.set()
        await self.release.wait()
        return await self.inner(*a, **kw)  # type: ignore[arg-type]


async def test_start_backfill_is_background_and_one_job_per_symbol_interval() -> None:
    gate = _Gate(5)
    svc = _svc(gate)
    first = svc.start_backfill(SYM, IV, Range(0, 5 * W))
    await gate.entered.wait()
    # Chart is interactive: the caller got a task back and the job is still paging.
    assert svc.job_running(SYM, IV) and not first.done()
    assert svc.start_backfill(SYM, IV, Range(0, 5 * W)) is first  # SR-E12-08: one job
    gate.release.set()
    result = await first
    assert len(result.fetched) == 5 and len(gate.inner.calls) == 1
    await asyncio.sleep(0)
    assert not svc.job_running(SYM, IV)


async def test_concurrent_reads_for_same_key_are_serialised_not_duplicated() -> None:
    port = _Bybit(5)
    svc = _svc(port)
    a, b = await asyncio.gather(
        svc.read_range(SYM, IV, Range(0, 5 * W)), svc.read_range(SYM, IV, Range(0, 5 * W))
    )
    assert len(port.calls) == 1  # second waits, then hits the cache
    assert len(a.fetched) + len(b.fetched) == 5


async def test_aclose_cancels_running_jobs() -> None:
    gate = _Gate(5)
    svc = _svc(gate)
    task = svc.start_backfill(SYM, IV, Range(0, 5 * W))
    await gate.entered.wait()
    await svc.aclose()
    assert task.cancelled()


async def test_crashed_job_is_logged_and_released() -> None:
    class _BadCache(_Cache):
        async def write_klines(self, rows: Sequence[object]) -> None:
            raise RuntimeError("disk")

    svc = _svc(_Bybit(2), _BadCache())
    task = svc.start_backfill(SYM, IV, Range(0, 2 * W))
    with pytest.raises(RuntimeError):
        await task
    await asyncio.sleep(0)
    assert not svc.job_running(SYM, IV)


async def test_kline_sink_receives_only_confirmed_klines() -> None:
    seen: list[int] = []

    async def sink(symbol: str, interval: str, events: Sequence[KlineEvent]) -> None:
        seen.extend(e.start for e in events)

    port = _Bybit(3)
    port.bars[-1] = _k(2 * W, confirmed=False)
    result = await _svc(port, kline_sink=sink).backfill_range(SYM, IV, Range(0, 3 * W))
    assert seen == [0, W]
    assert result.fetched[-1].confirmed is False


async def test_fully_cached_request_never_calls_exchange_and_coverage_exposed() -> None:
    port = _Bybit(5)
    svc = _svc(port)
    await svc.backfill_range(SYM, IV, Range(0, 5 * W))
    port.calls.clear()
    result = await svc.read_range(SYM, IV, Range(0, 5 * W))
    assert port.calls == [] and result.fetched == []
    index = svc.coverage(SYM, IV)
    assert index is not None and index.holes(Range(0, 5 * W)) == []
    assert svc.coverage("ETHUSDT", IV) is None
