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
from candleviewer.exchange.base.instruments import InstrumentsFetcher
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
from candleviewer.observability import spawn

logger = structlog.get_logger(__name__)

_MIN_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 30.0


#: Neutral fetcher port (`exchange.base.instruments.InstrumentsFetcher`):
#: returns already-normalised `Instrument`s plus rejected rows. The concrete
#: exchange adapter's fetcher is injected by the composition root, so this
#: module never sees a raw exchange payload, the parser or the transport.
InstrumentsInfoFetcher = InstrumentsFetcher


class InstrumentsRepositoryLike(Protocol):
    """Structural type for `candleviewer.storage.repositories.
    instruments_sqlalchemy.SqlAlchemyInstrumentsRepository` (M10). Rows cross
    the boundary as plain JSON-mode mappings (`Instrument.model_dump(mode=
    "json")`) because M10 may depend on M1 only (C-3.1) and so cannot import
    the domain model; this module re-validates them on load."""

    async def upsert_snapshot(self, rows: Sequence[Mapping[str, Any]]) -> None: ...

    async def record_version(
        self,
        row: Mapping[str, Any],
        *,
        changed_fields: Sequence[str],
    ) -> None: ...

    async def mark_stale(self, *, stale_since_us: int) -> None: ...

    async def load_all(self) -> Sequence[Mapping[str, Any]]: ...


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
        on_demand_cooldown_s: float = 60.0,
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

        self._on_demand_cooldown_s = on_demand_cooldown_s
        self._last_on_demand_us: int | None = None
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
            persisted = [
                Instrument.model_validate(row) for row in await self._repository.load_all()
            ]
        except Exception:  # storage tier down or a row fails validation
            logger.warning("instruments_startup_load_failed")
            persisted = []
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
        self._task = spawn(self._run_periodic(), name="instruments-refresh")

    async def stop(self, grace_s: float = 5.0) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            task, self._task = self._task, None
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=grace_s)
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                # The shield absorbs the *periodic task's* own cancellation;
                # if the caller of `stop()` was cancelled, propagate it.
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise

    # -- on-demand refresh (ticket "unknown symbol" + "Refresh does not ----
    # -- stall readers" scenarios) -------------------------------------------

    def snapshot(self) -> CatalogueSnapshot | None:
        """Current snapshot (O(1), no I/O) for readers such as the API."""
        return self.cache.current()

    async def ensure_symbol(self, symbol: str) -> Instrument | None:
        """ "Refresh without restart" on-demand path: if `symbol` is not in
        the current snapshot, force one refresh and re-check. Returns the
        (possibly newly-fetched) instrument, or `None` if it still is not
        found after the refresh (unknown to the exchange, not just stale)."""
        current = self.cache.current()
        if current is not None and current.get(symbol) is not None:
            return current.get(symbol)
        # Unknown-symbol lookups are caller-controlled: throttle the upstream
        # fetch so a burst of bogus symbols cannot exhaust the REST budget.
        now = self._now_us()
        if (
            self._last_on_demand_us is not None
            and now - self._last_on_demand_us < self._on_demand_cooldown_s * 1_000_000
        ):
            instruments_refresh_total.labels(result="throttled").inc()
            return None
        self._last_on_demand_us = now
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
        # Keep the *first* failure time: `stale_since` means "since when",
        # so consecutive failures must not keep pushing it forward.
        snap = self.cache.current()
        prior = snap.stale_since_us if snap is not None else None
        stale_since_us = prior if prior is not None else self._now_us()
        self.cache.mark_stale(stale_since_us=stale_since_us)
        try:
            await self._repository.mark_stale(stale_since_us=stale_since_us)
        except Exception:
            logger.warning("instruments_mark_stale_persist_failed")
        logger.warning("instruments_refresh_failed", error=str(last_error))
        raise InstrumentRefreshError(
            f"instrument catalogue refresh failed after {self._max_retries} attempts"
        ) from last_error

    async def _refresh_once(self) -> None:
        result = await self._fetch_instruments_info(self._now_us)
        fetched_at_us = max((i.fetched_at for i in result.instruments), default=self._now_us())
        current = self.cache.current()

        for rejected in result.rejected:
            logger.warning(
                "instruments_refresh_skipped_row",
                symbol=rejected.symbol,
                error=rejected.reason,
            )

        parsed: dict[str, Instrument] = {}
        for item in result.instruments:
            previous = current.get(item.symbol) if current is not None else None
            versioned, changed_fields = next_version(previous, item)
            parsed[versioned.symbol] = versioned
            if changed_fields:
                await self._repository.record_version(
                    versioned.model_dump(mode="json"), changed_fields=changed_fields
                )
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
            raise InstrumentRefreshError("instrument fetch returned zero parseable rows")

        # Symbols the cache already had that did not reappear in this fetch
        # keep their last-known record (never silently dropped mid-refresh —
        # a transient short page must not make a symbol vanish); the exchange
        # normally only *adds* symbols or flips `status` to `Closed`, so this is a
        # defensive merge, not the normal path.
        if current is not None:
            for symbol, instrument in current.by_symbol.items():
                parsed.setdefault(symbol, instrument)

        await self._repository.upsert_snapshot([i.model_dump(mode="json") for i in parsed.values()])
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
