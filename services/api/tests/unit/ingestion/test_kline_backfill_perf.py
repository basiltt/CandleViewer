"""Perf recording for the E08-S06 DoD item QA defect #1622 flagged missing:
"Perf: 300 ms cache-read budget and backfill wall time recorded" (ticket
"Performance notes": "<=300 ms to first paint from cache for 5 000 bars";
"Test plan": "Perf: 5 000-bar cache read p95; full 90-day 5m backfill wall
time and request count").

Not a network/DB test (C-13.5): the cache is `FakeMarketDataRepository`
in-memory, and the exchange fetcher is an in-memory page generator — this
measures the `KlineBackfillService`/`MarketDataRepository` code path's own
overhead, not real QuestDB latency (that is E07-T03/an integration-marked
test's job once a real backend exists). Printed numbers are the "recorded"
evidence the PR body pastes; the assertions are the CI-enforced budget.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from candleviewer.exchange.base.models import KlineEvent
from candleviewer.ingestion.kline_backfill import KlineBackfillService
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.storage.models import TimeRange
from candleviewer.storage.repositories.rows import KlineRow
from candleviewer.storage.testing import FakeMarketDataRepository

_SYMBOL = "BTCUSDT"
_INTERVAL = "5"
_BAR_WIDTH_US = 5 * 60 * 1_000_000
_FIVE_THOUSAND_BARS_US = 5_000 * _BAR_WIDTH_US
_NINETY_DAYS_US = 90 * 24 * 60 * 60 * 1_000_000


def _kline(start: int) -> KlineEvent:
    return KlineEvent(
        event_id="00000000-0000-7000-8000-000000000001",
        ts_event=start,
        ts_ingest=start,
        source="backfill",
        symbol=_SYMBOL,
        interval=_INTERVAL,  # type: ignore[arg-type]
        start=start,
        end=start + _BAR_WIDTH_US - 1,
        open="100",
        high="101",
        low="99",
        close="100",
        volume="1",
        turnover="100",
        confirmed=True,
    )


class _RowCache:
    """Adapts `KlineBackfillService`'s plain-dict `write_klines` payload
    (`ingestion/kline_backfill.py`'s `_row_payload` docstring: "the
    composition root's cache adapter constructs the real `KlineRow` from
    this shape") into `FakeMarketDataRepository`'s `KlineRow` expectation —
    the same adapter the real composition root (`app.py`) would provide."""

    def __init__(self) -> None:
        self._repo = FakeMarketDataRepository()

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto"
    ) -> list[KlineRow]:
        return await self._repo.read_klines(
            sym, interval, TimeRange(start_us=rng.start_us, end_us=rng.end_us)
        )

    async def write_klines(self, rows: Sequence[object]) -> None:
        kline_rows = [KlineRow(**row) for row in rows]  # type: ignore[arg-type]
        await self._repo.write_klines(kline_rows)


class _PagingFetcher:
    """Serves `_kline` rows for whatever window is requested, in
    Bybit-page-sized (1 000-row) chunks -- mirrors the real adapter's own
    1 000-row-per-call limit (`KlineFetcher`'s docstring)."""

    def __init__(self) -> None:
        self.page_count = 0

    async def __call__(
        self, symbol: str, interval: str, start: int, end: int, limit: int = 1000
    ) -> Sequence[KlineEvent]:
        self.page_count += 1
        rows: list[KlineEvent] = []
        cursor = start
        while cursor < end and len(rows) < limit:
            rows.append(_kline(cursor))
            cursor += _BAR_WIDTH_US
        return rows


async def test_cache_read_of_5000_bars_is_under_300ms_budget() -> None:
    cache = _RowCache()
    fetcher = _PagingFetcher()
    service = KlineBackfillService(fetch_klines=fetcher, cache=cache)
    rng = Range(0, _FIVE_THOUSAND_BARS_US)

    # Cold: populate the cache once (not part of the measured budget).
    await service.backfill_range(_SYMBOL, _INTERVAL, rng)

    started = time.perf_counter()
    rows = await cache.read_klines(_SYMBOL, _INTERVAL, Range(0, rng.end_us))
    elapsed_ms = (time.perf_counter() - started) * 1000

    print(f"[perf][E08-S06] 5000-bar cache read: {elapsed_ms:.2f} ms (budget: 300 ms)")
    assert len(rows) == 5_000
    assert elapsed_ms < 300


async def test_full_90_day_5m_backfill_wall_time_and_request_count_recorded() -> None:
    cache = _RowCache()
    fetcher = _PagingFetcher()
    service = KlineBackfillService(fetch_klines=fetcher, cache=cache)
    rng = Range(0, _NINETY_DAYS_US)
    expected_bars = _NINETY_DAYS_US // _BAR_WIDTH_US
    expected_pages = -(-expected_bars // 1000)  # ceil division, 1000-row pages

    started = time.perf_counter()
    result = await service.backfill_range(_SYMBOL, _INTERVAL, rng)
    elapsed_s = time.perf_counter() - started

    print(
        f"[perf][E08-S06] 90-day 5m backfill: {elapsed_s * 1000:.2f} ms wall time, "
        f"{fetcher.page_count} requests (expected {expected_pages})"
    )
    assert not result.partial
    assert len(result.fetched) == expected_bars
    assert fetcher.page_count == expected_pages
