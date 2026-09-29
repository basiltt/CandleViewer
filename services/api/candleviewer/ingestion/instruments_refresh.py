"""Instrument catalogue refresh scheduler (E08-S01-2).

Owns the periodic (12 h TTL) + on-demand refresh of the E08-S01 in-memory
`InstrumentCatalogueCache`, persisting each fetch through a storage
repository and publishing `InstrumentUpdatedEvent` on the E08-T03 bus when a
refresh detects a metadata change (ticket "Tick size changes" scenario).

Kept in `ingestion` (M6) per the ticket's own scope line, and — per C-3.1 —
M6 may not import `candleviewer.storage` or `candleviewer.api` directly. The
repository and bus dependencies are therefore narrow, locally-declared
`Protocol`s (mirrors `ingestion/clock.py`'s `ServerTimeFetcher` pattern):
the composition root (`candleviewer.app`) wires the concrete
`SqlAlchemyInstrumentsRepository` (M10) and `Bus.publish` (M5) in, without
this module ever importing either package.

Design notes tying back to the ticket's Gherkin:
- "Catalogue loaded at startup": `refresh_now()` is awaited once, inline,
  before `start()` returns, so `GET /instruments` never serves an empty
  catalogue after boot.
- "Refresh without restart": `start()` schedules a periodic task at
  `ttl_seconds`; `refresh_now()` is also exposed for the "unknown symbol"
  on-demand path (the router calls it directly).
- "Refresh fails": a failed fetch marks the existing snapshot stale via
  `InstrumentCatalogueCache.mark_stale` rather than clearing it, increments
  `instruments_refresh_total{result="error"}`, and logs a warning — the
  previous snapshot keeps serving.
- "Refresh does not stall readers": the fetch + parse + diff work all
  happens before the single atomic `cache.swap()` call; nothing here ever
  blocks a concurrent `cache.current()` read.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol
from uuid import uuid4

import structlog

from candleviewer.domain.events import Instrument
from candleviewer.exchange.bybit.instruments import InstrumentParseError, parse_instrument
from candleviewer.ingestion.errors import IngestionError
from candleviewer.ingestion.instruments import (
    CatalogueSnapshot,
    InstrumentCatalogueCache,
    build_updated_event,
    next_version,
    utc_now_us,
)
from candleviewer.ingestion.metrics import (
    instruments_cache_age_seconds,
    instruments_catalogue_size,
    instruments_refresh_total,
)

logger = structlog.get_logger(__name__)

_MIN_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 30.0


class InstrumentsInfoFetcher(Protocol):
    """Returns the raw Bybit `instruments-info` (`category=linear`) list-item
    payloads for one page. Implemented by a thin closure over
    `BybitRestClient.get_public` (E08-T02) at the composition root, kept as
    a narrow Protocol here so this module never imports `exchange.bybit`'s
    REST transport directly."""

    async def __call__(self) -> Sequence[Mapping[str, Any]]: ...


class InstrumentsRepositoryLike(Protocol):
    """Structural type for `candleviewer.storage.repositories.instruments.
    InstrumentsRepository` (M10) — see this module's docstring for why this
    is a local Protocol rather than an import."""

    async def upsert_snapshot(self, instruments: Sequence[Instrument]) -> None: ...

    async def record_version(
        self,
        instrument: Instrument,
        *,
        changed_fields: Sequence[str],
    ) -> None: ...

    async def load_all(self) -> Sequence[Instrument]: ...


class BusPublisherLike(Protocol):
    """Structural type for `Bus.publish`, bound to the `{env}.instruments.
    {symbol}.updated` topic by the composition root — this module only ever
    calls the injected callable, never constructs a `Topic` itself, so it
    stays free of the `candleviewer.bus` import edge (C-3.1)."""

    async def __call__(self, event: Any) -> None: ...


class InstrumentRefreshError(IngestionError):
    """A refresh attempt failed after every retry (fetch, parse, or
    persistence). The previous snapshot is left serving; see this module's
    docstring, "Refresh fails" scenario."""


class InstrumentsRefreshScheduler:
    """Owns the instrument catalogue: fetch -> parse -> version-diff ->
    persist -> publish -> atomic cache swap, on a 12 h TTL schedule plus
    on-demand triggers.

    Every dependency is injected (clock, sleep, jitter source, fetcher,
    repository, publisher) so this class is unit-testable without a network
    call, a database, or a real bus (C-13.2)."""

    def __init__(
        self,
        *,
        fetch_instruments_info: InstrumentsInfoFetcher,
        repository: InstrumentsRepositoryLike,
        publish: BusPublisherLike | None = None,
        cache: InstrumentCatalogueCache | None = None,
        ttl_seconds: float = 43_200.0,  # 12 h, ticket acceptance criterion
        max_retries: int = 3,
        now_us: Callable[[], int] = utc_now_us,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self._fetch_instruments_info = fetch_instruments_info
        self._repository = repository
        self._publish = publish
        self.cache = (
            cache if cache is not None else InstrumentCatalogueCache(ttl_seconds=ttl_seconds)
        )
        self._ttl_seconds = ttl_seconds
        self._max_retries = max(1, max_retries)
        self._now_us = now_us
        self._sleep = sleep
        self._random = random_fn

        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._refresh_lock = asyncio.Lock()

    # -- lifecycle (M6 `ingestion` conventions, 20-architecture.md §3) ------

    async def start(self) -> None:
        """Load whatever is already persisted (so a restart is never a
        cold, empty catalogue — belt-and-braces alongside the immediate
        `refresh_now()` below), then perform the startup fetch, then
        schedule the periodic TTL refresh task."""
        try:
            persisted = await self._repository.load_all()
        except Exception:  # pragma: no cover - defensive, storage tier down
            logger.warning("instruments_startup_load_failed")
            persisted = ()
        if persisted:
            self.cache.swap(
                CatalogueSnapshot(
                    by_symbol={i.symbol: i for i in persisted}, fetched_at_us=self._now_us()
                )
            )
        try:
            await self.refresh_now()
        except InstrumentRefreshError:
            # "Catalogue loaded at startup" still wants *some* snapshot to
            # serve; the persisted load above already covered that. A
            # startup fetch failure is not fatal — the periodic task keeps
            # retrying on schedule.
            logger.warning("instruments_startup_refresh_failed")
        self._stopping = False
        self._task = asyncio.create_task(self._run_periodic(), name="instruments-refresh")

    async def stop(self, grace_s: float = 5.0) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=grace_s)
            except (asyncio.CancelledError, TimeoutError):
                pass
            self._task = None

    # -- on-demand refresh (ticket "unknown symbol" + "Refresh does not ----
    # -- stall readers" scenarios) -------------------------------------------

    async def ensure_symbol(self, symbol: str) -> Instrument | None:
        """ "Refresh without restart" on-demand path: if `symbol` is not in
        the current snapshot, force one refresh and re-check. Returns the
        (possibly newly-fetched) instrument, or `None` if it still is not
        found after the refresh (unknown to the exchange, not just stale)."""
        current = self.cache.current()
        if current is not None and current.get(symbol) is not None:
            return current.get(symbol)
        try:
            await self.refresh_now()
        except InstrumentRefreshError:
            pass
        refreshed = self.cache.current()
        return refreshed.get(symbol) if refreshed is not None else None

    async def refresh_now(self) -> None:
        """One refresh attempt, retried with full jitter up to
        `max_retries` times. Never lets two concurrent callers (the
        periodic task and an on-demand trigger) race each other's fetch —
        guarded by `self._refresh_lock`."""
        async with self._refresh_lock:
            await self._refresh_with_retry()

    # -- internals -----------------------------------------------------------

    async def _refresh_with_retry(self) -> None:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                await self._refresh_once()
                instruments_refresh_total.labels(result="ok").inc()
                return
            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries - 1:
                    backoff = min(_MAX_BACKOFF_S, _MIN_BACKOFF_S * (2**attempt))
                    jitter = backoff * self._random()
                    await self._sleep(jitter)
        instruments_refresh_total.labels(result="error").inc()
        self.cache.mark_stale(stale_since_us=self._now_us())
        logger.warning("instruments_refresh_failed", error=str(last_error))
        raise InstrumentRefreshError(
            f"instrument catalogue refresh failed after {self._max_retries} attempts"
        ) from last_error

    async def _refresh_once(self) -> None:
        raw_items = await self._fetch_instruments_info()
        fetched_at_us = self._now_us()
        current = self.cache.current()

        parsed: dict[str, Instrument] = {}
        for raw in raw_items:
            try:
                item = parse_instrument(raw, fetched_at_us=fetched_at_us)
            except InstrumentParseError as exc:
                logger.warning(
                    "instruments_refresh_skipped_row",
                    symbol=raw.get("symbol"),
                    error=str(exc),
                )
                continue
            previous = current.get(item.symbol) if current is not None else None
            versioned, changed_fields = next_version(previous, item)
            parsed[versioned.symbol] = versioned
            if changed_fields:
                await self._repository.record_version(versioned, changed_fields=changed_fields)
                if self._publish is not None:
                    event = build_updated_event(
                        event_id=uuid4(),
                        symbol=versioned.symbol,
                        metadata_version=versioned.metadata_version,
                        changed_fields=changed_fields,
                        ts_now_us=fetched_at_us,
                    )
                    await self._publish(event)

        if not parsed:
            raise InstrumentRefreshError("instruments-info returned zero parseable rows")

        # Symbols the cache already had that did not reappear in this fetch
        # keep their last-known record (never silently dropped mid-refresh —
        # a transient short page must not make a symbol vanish); Bybit only
        # ever *adds* symbols or flips `status` to `Closed`, so this is a
        # defensive merge, not the normal path.
        if current is not None:
            for symbol, instrument in current.by_symbol.items():
                parsed.setdefault(symbol, instrument)

        await self._repository.upsert_snapshot(list(parsed.values()))
        self.cache.swap(CatalogueSnapshot(by_symbol=parsed, fetched_at_us=fetched_at_us))
        instruments_cache_age_seconds.set(0.0)
        instruments_catalogue_size.set(len(parsed))

    async def _run_periodic(self) -> None:
        while not self._stopping:
            jitter = self._ttl_seconds * 0.05 * self._random()
            try:
                await self._sleep(self._ttl_seconds + jitter)
            except asyncio.CancelledError:
                return
            if self._stopping:
                return
            try:
                await self.refresh_now()
            except InstrumentRefreshError:
                pass  # already logged + metriced in `_refresh_with_retry`
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("instruments_periodic_refresh_unexpected_error")
            current = self.cache.current()
            if current is not None:
                instruments_cache_age_seconds.set(current.age_seconds(now_us=self._now_us()))
