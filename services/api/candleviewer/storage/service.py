"""Lifecycle contract for the storage module (M10).

Wires the in-memory fakes when `Settings.storage_backend == "fake"`
(the CI/dev default — no database containers required, ticket acceptance
criterion 1). `"real"` engine clients (Postgres/QuestDB/cold tier) are
E07-T02/T03/T04's job; selecting `"real"` today raises `StorageTierUnavailable`
at `start()` rather than silently falling back to fakes, per the ticket's
"a tier client fails to connect at boot" acceptance criterion.

`stop(grace_s)` awaits any in-flight writes it is tracking (none exist yet on
the fake path — there is nothing to drain) and is idempotent: calling it
twice, or before `start()`, never raises.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.health import StorageHealthReport, TierHealth, TierState
from candleviewer.storage.repositories import (
    ColdTierRepository,
    MarketDataRepository,
    RelationalRepository,
    RetentionRepository,
)
from candleviewer.storage.testing import (
    FakeColdTierRepository,
    FakeMarketDataRepository,
    FakeRelationalRepository,
    FakeRetentionRepository,
)

if TYPE_CHECKING:
    from candleviewer.app import AppContext


class StorageService:
    """M10 `storage` module lifecycle: constructs and owns the three tier
    clients (market data, relational, cold) plus retention, per
    `docs/plan/20-architecture.md` Sec.6.1 ("no module constructs its own
    dependencies" — this *is* that construction site, injected into
    `AppContext` by `candleviewer.app.build_app_context`)."""

    def __init__(self, backend: str = "fake") -> None:
        self._backend = backend
        self._started = False
        self._market_data: MarketDataRepository | None = None
        self._relational: RelationalRepository | None = None
        self._cold: ColdTierRepository | None = None
        self._retention: RetentionRepository | None = None
        self._pending_writes: set[asyncio.Task[None]] = set()

    @property
    def market_data(self) -> MarketDataRepository:
        if self._market_data is None:
            raise StorageTierUnavailable("storage.start() has not been called")
        return self._market_data

    @property
    def relational(self) -> RelationalRepository:
        if self._relational is None:
            raise StorageTierUnavailable("storage.start() has not been called")
        return self._relational

    @property
    def cold(self) -> ColdTierRepository:
        if self._cold is None:
            raise StorageTierUnavailable("storage.start() has not been called")
        return self._cold

    @property
    def retention(self) -> RetentionRepository:
        if self._retention is None:
            raise StorageTierUnavailable("storage.start() has not been called")
        return self._retention

    async def start(self, ctx: AppContext) -> None:
        """Construct and "connect" the configured tier clients.

        On the `fake` backend this performs no I/O by construction — the
        fakes hold everything in memory. On `real` (not yet implemented by
        this ticket) this raises `StorageTierUnavailable` rather than
        silently degrading, so a misconfigured environment fails loudly at
        boot instead of serving with a missing tier.
        """
        if self._backend == "fake":
            self._market_data = FakeMarketDataRepository()
            self._relational = FakeRelationalRepository()
            self._cold = FakeColdTierRepository()
            self._retention = FakeRetentionRepository()
            self._started = True
            return
        raise StorageTierUnavailable(
            f"storage_backend={self._backend!r} has no client implementation yet "
            "(E07-T02/T03/T04 land the real engine clients)"
        )

    async def stop(self, grace_s: float) -> None:
        """Await in-flight writes (bounded by `grace_s`), then release clients.

        Deterministic drain, never leaves an "Event loop is closed" warning
        (ticket acceptance criterion 4): any tracked write task is awaited
        with a timeout and cancelled if it does not finish in time, and the
        cancellation is itself awaited so the task is fully unwound before
        this coroutine returns.
        """
        pending = list(self._pending_writes)
        if pending:
            _done, not_done = await asyncio.wait(pending, timeout=grace_s)
            for task in not_done:
                task.cancel()
            for task in not_done:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._pending_writes.clear()
        self._market_data = None
        self._relational = None
        self._cold = None
        self._retention = None
        self._started = False

    def track_write(self, task: asyncio.Task[None]) -> None:
        """Register an in-flight write task so `stop()` can drain it
        deterministically. Callers issuing fire-and-forget writes must use
        this instead of a bare `create_task` (C-2.18: every task is owned)."""
        self._pending_writes.add(task)
        task.add_done_callback(self._pending_writes.discard)

    def health(self) -> HealthReport:
        """Module-wide health for the supervisor (`HealthReport`).

        `ok` only once started with every configured tier healthy; a
        `postgres` tier reporting `down` degrades the whole module (ticket:
        "readiness requires postgres=ok"). See `tier_health()` for the
        finer-grained per-tier report `/readyz` and the health screen use.
        """
        report = self.tier_health()
        pg = report.tier("postgres")
        if not self._started:
            status = HealthStatus.STOPPED
        elif pg is not None and pg.state != TierState.DOWN:
            status = HealthStatus.OK
        else:
            status = HealthStatus.DEGRADED
        return HealthReport(module="storage", status=status, detail="")

    def tier_health(self) -> StorageHealthReport:
        """Per-tier health (`{tier, state, latency_ms, detail}`, ticket
        "Technical notes / design"). On the `fake` backend all three tiers
        (`postgres`, `questdb`, `cold`) report `ok`/`"fake/healthy"` — the
        ticket's acceptance criterion 1 wording exactly — with `latency_ms`
        ~0 since no I/O occurs."""
        if not self._started:
            return StorageHealthReport(tiers=())
        if self._backend == "fake":
            started = time.perf_counter()
            latency_ms = (time.perf_counter() - started) * 1000
            return StorageHealthReport(
                tiers=tuple(
                    TierHealth(
                        tier=tier,
                        state=TierState.OK,
                        latency_ms=latency_ms,
                        detail="fake/healthy",
                    )
                    for tier in ("postgres", "questdb", "cold")
                )
            )
        raise StorageTierUnavailable(  # pragma: no cover - unreachable until E07-T02/T03/T04 land
            f"storage_backend={self._backend!r} has no health probe implementation yet"
        )
