"""Cache-first `/market/klines` read path (E12-S05, `22-api-openapi.yaml` `/market/klines`).

Source priority (OpenAPI): (1) locally stored bars, (2) exchange REST kline backfill for
windows the store does not hold, (3) the Parquet cold tier for windows older than QuestDB hot
retention. `read()` never waits on the exchange: it serves what the tiers hold now and, if the
hot part of the window has holes, starts (or joins) the single background backfill job for
that `(symbol, interval)` — the chart is interactive before paging finishes, and the next read
picks up the new rows. Every result states the tiers it touched (`sources`) and where
tick-accurate data begins (`recording_started_at`; before it, delta/footprint are null).

Backfill only targets the **hot** part of the window (older history is the cold tier's job),
which also bounds how far back one request can make the exchange page (security notes).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from candleviewer.ingestion.kline_backfill import KlineBackfillService
from candleviewer.ingestion.kline_coverage import Range

#: `meta.sources` values (OpenAPI `DataMeta.sources` enum).
SOURCE_HOT: Final = "questdb"
SOURCE_COLD: Final = "parquet"
SOURCE_EXCHANGE: Final = "exchange_rest"
#: Row `source` tags that mean "this bar came from the exchange REST kline endpoint".
_EXCHANGE_ROW_SOURCES: Final = frozenset({"rest", "kline"})


class KlineRowLike(Protocol):
    @property
    def ts_us(self) -> int: ...
    @property
    def open(self) -> str: ...
    @property
    def high(self) -> str: ...
    @property
    def low(self) -> str: ...
    @property
    def close(self) -> str: ...
    @property
    def volume(self) -> str: ...
    @property
    def turnover(self) -> str: ...
    @property
    def confirmed(self) -> bool: ...
    @property
    def source(self) -> str: ...


class HotKlineReader(Protocol):
    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto"
    ) -> Sequence[KlineRowLike]: ...


ColdKlineReader = Callable[[str, str, Range], Awaitable[Sequence[KlineRowLike]]]


@dataclass(frozen=True, slots=True)
class KlineRead:
    rows: list[KlineRowLike]
    sources: list[str]
    recording_started_at_us: int | None
    holes: list[Range]
    backfilling: bool


_MIN_US: Final = 60_000_000
#: Interval code -> bar width (µs). `M` has no fixed width: served from the store, never backfilled.
_WIDTH_US: Final[dict[str, int]] = {
    **{c: int(c) * _MIN_US for c in ("1", "3", "5", "15", "30", "60", "120", "240", "360", "720")},
    "D": 1440 * _MIN_US,
    "W": 7 * 1440 * _MIN_US,
}


class KlineReadService:
    """Tier-merging, non-blocking kline reads for `GET /market/klines`."""

    def __init__(
        self,
        hot: HotKlineReader,
        *,
        backfill: KlineBackfillService | None = None,
        cold: ColdKlineReader | None = None,
        hot_boundary_us: Callable[[], int] = lambda: 0,
        recording_started_at_us: Callable[[str], int | None] = lambda _s: None,
        max_backfill_bars: int = 400_000,
    ) -> None:
        self._hot = hot
        self._backfill = backfill
        self._cold = cold
        self._boundary = hot_boundary_us
        self._recording_started = recording_started_at_us
        self._max_backfill_bars = max_backfill_bars
        self._primed: set[tuple[str, str]] = set()

    async def read(self, symbol: str, interval: str, rng: Range) -> KlineRead:
        boundary = self._boundary()
        sources: list[str] = []
        rows: list[KlineRowLike] = []
        if self._cold is not None and rng.start_us < boundary:
            cold_rows = await self._cold(
                symbol, interval, Range(rng.start_us, min(rng.end_us, boundary))
            )
            if cold_rows:
                sources.append(SOURCE_COLD)
                rows.extend(cold_rows)
        holes: list[Range] = []
        backfilling = False
        if rng.end_us > boundary:
            hot_rng = Range(max(rng.start_us, boundary), rng.end_us)
            hot_rows = await self._hot.read_klines(symbol, interval, hot_rng)
            if hot_rows:
                sources.append(SOURCE_HOT)
                rows.extend(hot_rows)
            holes, backfilling = await self._schedule_backfill(symbol, interval, hot_rng)
        if backfilling or any(r.source in _EXCHANGE_ROW_SOURCES for r in rows):
            sources.append(SOURCE_EXCHANGE)
        rows.sort(key=lambda r: r.ts_us)
        return KlineRead(rows, sources, self._recording_started(symbol), holes, backfilling)

    async def _schedule_backfill(
        self, symbol: str, interval: str, hot_rng: Range
    ) -> tuple[list[Range], bool]:
        width = _WIDTH_US.get(interval)
        if self._backfill is None or width is None:
            return [], False
        # Bound how far back one request can page (SR-E12-08, security notes).
        start = max(hot_rng.start_us, hot_rng.end_us - self._max_backfill_bars * width)
        target = Range(start, hot_rng.end_us)
        key = (symbol, interval)
        if key not in self._primed:
            await self._backfill.load_coverage_from_cache(symbol, interval, target)
            self._primed.add(key)
        index = self._backfill.coverage(symbol, interval)
        holes = index.holes(target) if index is not None else [target]
        if holes:
            self._backfill.start_backfill(symbol, interval, target)
        return holes, self._backfill.job_running(symbol, interval)


__all__ = [
    "SOURCE_COLD",
    "SOURCE_EXCHANGE",
    "SOURCE_HOT",
    "ColdKlineReader",
    "HotKlineReader",
    "KlineRead",
    "KlineReadService",
]
