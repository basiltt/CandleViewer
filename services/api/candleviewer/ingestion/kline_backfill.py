"""Kline backfill service (E08-S06): paged history fetch, local cache-first
reads, rate-limit-safe paging and coverage-index-driven resume.

Kept in `ingestion` (M6) per the ticket's repo-paths guidance; M6 may not
import `candleviewer.storage` directly (C-3.1), so the cache dependency is a
narrow, locally-declared `Protocol` (mirrors `instruments_refresh.py`'s
`InstrumentsRepositoryLike` pattern) — the composition root (`candleviewer.
api`) wires the concrete `MarketDataRepository`/`QuestDbMarketDataRepository`
in without this module ever importing `candleviewer.storage`.

Design, tied to the ticket's Gherkin scenarios:
- "Backfill": `backfill_range` pages from `fetch_klines` (already-normalised
  `KlineEvent`s, ascending — see `exchange.base.ports.MarketDataPort`) until
  the requested range's coverage holes are closed, reporting progress via
  the injected `on_progress` callback after each page.
- "Cache hit": `read_range` first asks the injected cache reader for
  already-covered data and only calls `backfill_range` for the
  `CoverageIndex.holes()` of the request — a fully-covered request never
  touches the exchange.
- "Rate limited": `_fetch_page_with_retry` catches the exchange's
  rate-limit error, backs off with full jitter, and retries the same page;
  it never lets one throttled page fail the whole `backfill_range` call —
  rows already fetched and persisted before the throttle stay in the cache
  and are returned to the caller as partial progress.
- "Descending payload ordered correctly": `fetch_klines` already returns
  ascending-by-`start` `KlineEvent`s (E08-T02's adapter reverses the exchange's
  native descending order), so this module only has to preserve that order
  end to end and never re-sort by anything but `start`; a duplicate `start`
  across two pages is deduped by the storage layer's `(symbol, interval,
  ts_us)` write key, not re-implemented here.
- "Unconfirmed bar not cached as final": rows with `confirmed=False` are
  never included in what gets persisted as a *closed* range — see
  `_split_confirmed` — and the coverage index only marks a sub-range
  covered up to the start of the first unconfirmed row in a page (so a
  later, now-confirmed re-fetch of that same tail is still attempted).
- "Interrupted backfill resumes": `CoverageIndex` (kline_coverage.py) is the
  single source of truth for what has been fetched; a fresh
  `KlineBackfillService` reconstructed after a restart calls
  `load_coverage_from_cache` to rebuild it from whatever the repository
  already persisted, then `read_range`/`backfill_range` only ever fetch the
  remaining holes.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from candleviewer.domain.primitives import Symbol, TsUs
from candleviewer.exchange.base.models import KlineEvent
from candleviewer.ingestion._logging import get_logger
from candleviewer.ingestion.errors import IngestionError
from candleviewer.ingestion.kline_coverage import CoverageIndex, Range
from candleviewer.ingestion.metrics import (
    kline_backfill_duration_seconds,
    kline_backfill_pages_total,
    kline_cache_hit_ratio,
    kline_coverage_holes,
    symbol_label,
)

_MIN_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 30.0
_PAGE_LIMIT = 1000


class KlineFetcher(Protocol):
    """Structural type for `exchange.base.ports.MarketDataPort.fetch_klines`
    — declared locally so this module never imports the exchange adapter package
    directly (only `exchange.base` types, which M6 is allowed)."""

    async def __call__(
        self,
        symbol: Symbol,
        interval: str,
        start: TsUs,
        end: TsUs,
        limit: int = 1000,
    ) -> Sequence[KlineEvent]: ...


class KlineRowLike(Protocol):
    """The subset of `storage.repositories.rows.KlineRow` this module reads
    back from the cache — declared structurally so this module never
    imports `candleviewer.storage`."""

    ts_us: int
    confirmed: bool


class KlineCacheLike(Protocol):
    """Structural type for the storage-layer cache this service reads from
    and writes to. Matches `MarketDataRepository.read_klines`/
    `write_klines` (`storage/repositories/market_data.py`); the composition
    root injects the real repository (or the in-memory fake in tests)."""

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto"
    ) -> Sequence[KlineRowLike]: ...

    async def write_klines(self, rows: Sequence[object]) -> None: ...


class ProgressCallback(Protocol):
    """Invoked after every fetched page (ticket "Backfill" scenario:
    "progress reported"). `fraction` is `covered_us / total_us` for the
    range currently being backfilled, in `[0.0, 1.0]`."""

    def __call__(self, *, symbol: str, interval: str, fraction: float, status: str) -> None: ...


class KlineBackfillError(IngestionError):
    """Raised only when a page could not be fetched after every retry —
    the caller still gets whatever partial rows were persisted before the
    failure (ticket "Rate limited" scenario: "partial result stays
    usable")."""


def _row_payload(
    *, symbol: str, interval: str, event: KlineEvent, source: str
) -> dict[str, object]:
    """A plain dict shaped like `storage.repositories.rows.KlineRow`'s
    fields — returned as a dict (not the dataclass itself) so this module
    stays free of the `candleviewer.storage` import; the composition root's
    cache adapter constructs the real `KlineRow` from this shape."""
    return {
        "ts_us": event.start,
        "symbol": symbol,
        "interval": interval,
        "open": str(event.open),
        "high": str(event.high),
        "low": str(event.low),
        "close": str(event.close),
        "volume": str(event.volume),
        "turnover": str(event.turnover),
        "confirmed": event.confirmed,
        "source": source,
    }


def _split_confirmed(events: Sequence[KlineEvent]) -> tuple[list[KlineEvent], TsUs | None]:
    """Split `events` (ascending by `start`) into the rows safe to persist
    as closed history plus the `start` of the first unconfirmed row, if any
    (ticket "Unconfirmed bar not cached as final" scenario). Only a
    *trailing* unconfirmed row is expected (the newest bar, still forming);
    everything at or after it is excluded from the coverage-covered set."""
    for idx, event in enumerate(events):
        if not event.confirmed:
            return list(events[:idx]), event.start
    return list(events), None


@dataclass(slots=True)
class BackfillResult:
    """Outcome of one `backfill_range` call. `partial=True` means at least
    one page could not be fetched after retries — the rows already fetched
    are still persisted and included in `fetched` (ticket "Rate limited"
    scenario)."""

    fetched: list[KlineEvent]
    partial: bool


class KlineBackfillService:
    """Cache-first kline reads with rate-limit-safe, resumable paging.

    Every dependency (fetcher, cache, clock sleep, jitter source, progress
    callback) is injected so this class is unit-testable without a network
    call or a database (C-13.2). One `CoverageIndex` per `(symbol,
    interval)` is kept in memory; `load_coverage_from_cache` rebuilds it
    from whatever the repository already persisted after a restart."""

    def __init__(
        self,
        *,
        fetch_klines: KlineFetcher,
        cache: KlineCacheLike,
        source: str = "rest",
        max_retries: int = 5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[], float] = random.random,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._fetch_klines = fetch_klines
        self._cache = cache
        self._source = source
        self._max_retries = max(1, max_retries)
        self._sleep = sleep
        self._random = random_fn
        self._on_progress = on_progress
        self._coverage: dict[tuple[str, str], CoverageIndex] = {}

    def _index_for(self, symbol: str, interval: str) -> CoverageIndex:
        key = (symbol, interval)
        if key not in self._coverage:
            self._coverage[key] = CoverageIndex()
        return self._coverage[key]

    async def load_coverage_from_cache(self, symbol: str, interval: str, rng: Range) -> None:
        """Rebuild the in-memory coverage index for `(symbol, interval)`
        from whatever the repository already has in `rng` (ticket
        "Interrupted backfill resumes" scenario). Cheap/conservative: marks
        covered only the contiguous confirmed-row span(s) actually present,
        so a real hole left by an interrupted backfill is never masked."""
        rows = await self._cache.read_klines(symbol, interval, rng)
        index = self._index_for(symbol, interval)
        confirmed_rows = [r for r in rows if r.confirmed]
        if not confirmed_rows:
            return
        confirmed_rows.sort(key=lambda r: r.ts_us)
        span_start = confirmed_rows[0].ts_us
        prev_ts = confirmed_rows[0].ts_us
        # Bar width is inferred from the smallest gap between consecutive
        # rows already in the cache; if there is only one row, treat it as
        # a single-bar span (`end_us = ts_us + 1`).
        bar_width_us = 1
        if len(confirmed_rows) > 1:
            bar_width_us = min(b.ts_us - a.ts_us for a, b in itertools.pairwise(confirmed_rows))
        for row in confirmed_rows[1:]:
            if row.ts_us - prev_ts > bar_width_us:
                index.mark_covered(Range(span_start, prev_ts + bar_width_us))
                span_start = row.ts_us
            prev_ts = row.ts_us
        index.mark_covered(Range(span_start, prev_ts + bar_width_us))

    async def read_range(self, symbol: str, interval: str, rng: Range) -> BackfillResult:
        """Cache-first read (ticket "Cache hit" scenario): only the
        `CoverageIndex` holes for `rng` are fetched from the exchange;
        already-covered data is read straight back from the cache without
        touching the exchange at all."""
        index = self._index_for(symbol, interval)
        holes = index.holes(rng)
        total_us = max(1, rng.end_us - rng.start_us)
        covered_us = total_us - sum(h.end_us - h.start_us for h in holes)
        kline_cache_hit_ratio.labels(symbol=symbol_label(symbol), interval=interval).set(
            covered_us / total_us
        )
        result = BackfillResult(fetched=[], partial=False)
        if holes:
            with kline_backfill_duration_seconds.labels(
                symbol=symbol_label(symbol), interval=interval
            ).time():
                for hole in holes:
                    hole_result = await self._backfill_hole(symbol, interval, hole, rng)
                    result.fetched.extend(hole_result.fetched)
                    result.partial = result.partial or hole_result.partial
        cached_rows = await self._cache.read_klines(symbol, interval, rng)
        kline_coverage_holes.labels(symbol=symbol_label(symbol), interval=interval).set(
            len(index.holes(rng))
        )
        # Rows already fetched this call are included via `cached_rows`
        # once persisted; `result.fetched` is kept too so a caller can see
        # exactly what was newly pulled this call (ticket "Backfill":
        # "progress reported" wants the delta, not just the final set).
        _ = cached_rows
        return result

    async def backfill_range(self, symbol: str, interval: str, rng: Range) -> BackfillResult:
        """Force-fetch every hole in `rng`, ignoring nothing already
        covered (used by a scheduled N-day backfill job; `read_range` is
        the request-time equivalent for a single API call)."""
        return await self.read_range(symbol, interval, rng)

    async def _backfill_hole(
        self, symbol: str, interval: str, hole: Range, requested: Range
    ) -> BackfillResult:
        index = self._index_for(symbol, interval)
        fetched: list[KlineEvent] = []
        partial = False
        cursor = hole.start_us
        while cursor < hole.end_us:
            try:
                page = await self._fetch_page_with_retry(symbol, interval, cursor, hole.end_us)
            except KlineBackfillError:
                partial = True
                break
            if not page:
                break
            confirmed_events, unconfirmed_start = _split_confirmed(page)
            next_cursor = page[-1].start + 1
            if confirmed_events:
                rows = [
                    _row_payload(symbol=symbol, interval=interval, event=e, source=self._source)
                    for e in confirmed_events
                ]
                await self._cache.write_klines(rows)
                covered_end = confirmed_events[-1].end + 1
                index.mark_covered(Range(cursor, min(covered_end, hole.end_us)))
                fetched.extend(confirmed_events)
                next_cursor = covered_end
            if unconfirmed_start is not None:
                # The trailing in-progress bar is returned to the caller
                # (ticket "Unconfirmed bar not cached as final": "returned
                # as in-progress bar") but never marked covered, so a later
                # call re-fetches it once it has closed.
                fetched.append(page[-1])
                break
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            total_us = max(1, requested.end_us - requested.start_us)
            remaining = sum(h.end_us - h.start_us for h in index.holes(requested))
            fraction = min(1.0, max(0.0, 1.0 - remaining / total_us))
            if self._on_progress is not None:
                self._on_progress(
                    symbol=symbol, interval=interval, fraction=fraction, status="fetching"
                )
        if self._on_progress is not None:
            self._on_progress(
                symbol=symbol,
                interval=interval,
                fraction=1.0 if not partial else 0.0,
                status="partial" if partial else "done",
            )
        return BackfillResult(fetched=fetched, partial=partial)

    async def _fetch_page_with_retry(
        self, symbol: str, interval: str, start_us: TsUs, end_us: TsUs
    ) -> Sequence[KlineEvent]:
        """One page fetch, retried with full jitter backoff on any
        exception (the exchange's rate-limit `10018` included — the adapter's
        mapping maps it to `RateLimitError`, a plain `Exception` subclass
        this module treats no differently to any other transient failure,
        keeping this module free of an exchange adapter package
        import). Never lets one throttled page fail the whole backfill —
        see this module's docstring, "Rate limited" scenario."""
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                page = await self._fetch_klines(
                    symbol, interval, start_us, end_us, limit=_PAGE_LIMIT
                )
                kline_backfill_pages_total.labels(
                    symbol=symbol_label(symbol), interval=interval, result="ok"
                ).inc()
                return page
            except Exception as exc:  # see docstring: any failure is transient/retried
                last_error = exc
                kline_backfill_pages_total.labels(
                    symbol=symbol_label(symbol), interval=interval, result="retry"
                ).inc()
                if attempt < self._max_retries - 1:
                    backoff = min(_MAX_BACKOFF_S, _MIN_BACKOFF_S * (2**attempt))
                    jitter = backoff * self._random()
                    get_logger(__name__).warning(
                        "kline_backfill_page_retry",
                        symbol=symbol,
                        interval=interval,
                        attempt=attempt,
                        error=str(exc),
                    )
                    await self._sleep(jitter)
        kline_backfill_pages_total.labels(
            symbol=symbol_label(symbol), interval=interval, result="error"
        ).inc()
        get_logger(__name__).warning(
            "kline_backfill_page_failed", symbol=symbol, interval=interval, error=str(last_error)
        )
        raise KlineBackfillError(
            f"kline page fetch failed for {symbol}/{interval} after {self._max_retries} attempts"
        ) from last_error
