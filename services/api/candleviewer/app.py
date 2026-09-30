"""Composition root (M1 + Sec.6, `docs/plan/20-architecture.md`).

Builds `AppContext` and the FastAPI application. "No module constructs its
own dependencies; everything is injected, which makes every module
unit-testable with fakes" (Sec.6.1).

This ticket (E02-T05) wires the frozen `AppContext`, a minimal supervisor
that starts/stops modules in the documented order, and a FastAPI factory
exposing only `/healthz`, `/readyz` and build-info. Every other module here
is a scaffold (no real logic) — the fields exist so E02-T06's import-linter
contracts and every later epic have a concrete injection point.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from candleviewer.accounts.service import AccountsService
from candleviewer.admin.service import AdminService
from candleviewer.admin.wiring import (
    AuditHandle,
    SecretsHandle,
    build_audit_service,
    build_secrets_service,
)
from candleviewer.alerts.service import AlertsService
from candleviewer.api import (
    make_audit_router,
    make_auth_router,
    make_health_router,
    make_instruments_router,
    make_log_level_router,
    make_market_router,
)
from candleviewer.api.sessions import make_session_router
from candleviewer.auth.service import AuthService
from candleviewer.bars.service import BarsService
from candleviewer.book.service import BookService
from candleviewer.bus.models import Topic
from candleviewer.bus.service import BusService
from candleviewer.domain.events import InstrumentUpdatedEvent
from candleviewer.exchange.base.instruments import InstrumentsFetcher
from candleviewer.exchange.base.service import ExchangeBaseService
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.service import IngestionService
from candleviewer.journal.service import JournalService
from candleviewer.net import (
    BindingSelfCheck,
    CidrAllowList,
    MeshOnlyMiddleware,
    MeshSelfCheckScheduler,
    ReadOnlyGate,
    SystemTopicPublisher,
    net_binding_safe,
    real_socket_enumerator,
    register_system_topic_subscriber,
)
from candleviewer.observability.correlation import CorrelationMiddleware
from candleviewer.observability.log_level import LogLevelOverrides
from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.observability.service import ObservabilityService
from candleviewer.oms.service import OmsService
from candleviewer.orderflow.service import OrderflowService
from candleviewer.paper.service import PaperService
from candleviewer.recorder.service import RecorderService
from candleviewer.replay.service import ReplayService
from candleviewer.risk.service import RiskService
from candleviewer.rules.service import RulesService
from candleviewer.settings import Settings, get_settings
from candleviewer.storage.repositories.instruments_sqlalchemy import (
    SqlAlchemyInstrumentsRepository,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.service import StorageService
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.service import WsService


@dataclass(frozen=True)
class AppContext:
    """Everything a module needs, injected — never a global (Sec.6.1).

    Fields mirror `docs/plan/20-architecture.md` Sec.6.1: settings, bus,
    storage clients, key vault, metric registry, clock guard, and the module
    instances. Storage clients/key vault/clock guard are not yet implemented
    (owned by later epics) so they are omitted here rather than faked with a
    wrong shape; `metrics` (a real `CollectorRegistry`) and every M2-M24
    module's `service.py` scaffold are wired now so downstream tickets have a
    concrete constructor to extend.
    """

    settings: Settings
    metrics: CollectorRegistry

    secrets: SecretsHandle
    exchange_base: ExchangeBaseService
    exchange_bybit: ExchangeBybitService
    bus: BusService
    ingestion: IngestionService
    book: BookService
    bars: BarsService
    orderflow: OrderflowService
    storage: StorageService
    recorder: RecorderService
    replay: ReplayService
    accounts: AccountsService
    oms: OmsService
    rules: RulesService
    paper: PaperService
    risk: RiskService
    auth: AuthService
    audit: AuditHandle
    journal: JournalService
    admin: AdminService
    alerts: AlertsService
    observability: ObservabilityService
    ws: WsService

    # E09-T04: Tailscale-only reachability guard (US-ONB-008). `oms` never
    # imports `candleviewer.net` directly (outside its §3 allow-list); this
    # is the one instance it is injected with, structurally typed as
    # `oms.validator.ReadOnlyCheck` so no import edge is created.
    oms_read_only_gate: ReadOnlyGate
    # Owns the boot + hourly re-check loop (AC5, "drift after resume").
    # `services/api/candleviewer/main.py`'s lifespan runs `run_once()` once
    # at startup (the boot check) then `start()` for the hourly loop, and
    # `stop()` on shutdown.
    mesh_self_check: MeshSelfCheckScheduler
    # QA defect #1578 blocker 1: the one production subscriber wiring
    # `oms_read_only_gate` transitions onto the `system` WS topic
    # (`23-ws-protocol.md` §6) so the mandatory blocking banner is actually
    # published, not merely mechanically possible via `ReadOnlyGate.subscribe`.
    mesh_system_topic_publisher: SystemTopicPublisher


class _LazyAuditEmitter:
    """Resolves `audit.writer` per call: it only exists once `AuditService.start()` ran."""

    def __init__(self, audit: AuditHandle) -> None:
        self._audit = audit

    async def emit(self, action: str, **kwargs: Any) -> None:
        await self._audit.writer.emit(action, **kwargs)


def build_app_context(settings: Settings | None = None) -> AppContext:
    """Construct an `AppContext` with real scaffold modules, no I/O performed.

    Every field is a live instance of its module's scaffold `service.py` —
    constructing them does no network/DB work (each `__init__` only sets
    `_started = False`), which is what keeps `create_app()` fast and
    fake-only per the acceptance criteria.
    """
    resolved = settings or get_settings()
    read_only_gate = ReadOnlyGate()
    mesh_self_check = MeshSelfCheckScheduler(
        check=BindingSelfCheck(
            address_enumerator=real_socket_enumerator(),
            allow_list=CidrAllowList(list(resolved.mesh_cidrs)),
        ),
        read_only_gate=read_only_gate,
        gauge=net_binding_safe,
        interval_s=resolved.mesh_self_check_interval_s,
    )
    bus_service = BusService()
    mesh_system_topic_publisher = register_system_topic_subscriber(
        bus=bus_service.bus,
        env=resolved.environment.value,
        read_only_gate=read_only_gate,
    )
    return AppContext(
        settings=resolved,
        metrics=CollectorRegistry(),
        secrets=build_secrets_service(),
        exchange_base=ExchangeBaseService(),
        exchange_bybit=ExchangeBybitService(),
        bus=bus_service,
        ingestion=IngestionService(),
        book=BookService(),
        bars=BarsService(),
        orderflow=OrderflowService(),
        storage=StorageService(backend=resolved.storage_backend),
        recorder=RecorderService(),
        replay=ReplayService(),
        accounts=AccountsService(),
        oms=OmsService(),
        rules=RulesService(),
        paper=PaperService(),
        risk=RiskService(),
        auth=AuthService(),
        audit=build_audit_service(),
        journal=JournalService(),
        admin=AdminService(),
        alerts=AlertsService(),
        observability=ObservabilityService(),
        ws=WsService(),
        oms_read_only_gate=read_only_gate,
        mesh_self_check=mesh_self_check,
        mesh_system_topic_publisher=mesh_system_topic_publisher,
    )


# Start order per Sec.6.2: storage -> auth -> admin/key vault -> bus ->
# ingestion -> book -> bars -> order-flow -> recorder -> OMS -> paper ->
# rules -> replay -> gateway. `secrets`/`exchange_base`/`exchange_bybit`/
# `accounts`/`risk`/`audit`/`journal`/`alerts`/`observability` are not named
# explicitly in that sentence; they are placed at the earliest point their
# CONSTITUTION.md C-3.1 dependency edges allow, immediately before their
# first dependant.
_SUPERVISOR_ORDER: tuple[str, ...] = (
    "storage",
    "secrets",
    "auth",
    "admin",
    "bus",
    "exchange_base",
    "exchange_bybit",
    "ingestion",
    "book",
    "bars",
    "orderflow",
    "recorder",
    "accounts",
    "risk",
    "audit",
    "oms",
    "paper",
    "rules",
    "alerts",
    "journal",
    "replay",
    "observability",
    "ws",
)


class Supervisor:
    """Starts modules in dependency order, stops them in reverse (Sec.6.2)."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    async def start_all(self) -> None:
        for name in _SUPERVISOR_ORDER:
            module = getattr(self._ctx, name)
            await module.start(self._ctx)

    async def stop_all(self, grace_s: float = 15.0) -> None:
        for name in reversed(_SUPERVISOR_ORDER):
            module = getattr(self._ctx, name)
            await module.stop(grace_s)


def _hub_publisher(hub: RevocationHub) -> Callable[[str, str], Awaitable[None]]:
    async def _publish(session_id: str, reason: str) -> None:
        await hub.revoke(session_id, reason)

    return _publish


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application without touching Postgres/QuestDB/network.

    Per E02-T05 acceptance criterion 3: constructing the app with fakes-only
    settings must not perform I/O, and `GET /healthz` must return 200 with a
    build-info body. The module supervisor is *not* started here — that is
    driven by the ASGI lifespan in `services/api/main.py` (or a test's own
    fixture), keeping `create_app()` itself synchronous and side-effect-free.

    E09-T04: `MeshOnlyMiddleware` is mounted here (not in the lifespan) so it
    protects every request, including ones that arrive before the lifespan's
    boot self-check has finished — a request is checked against the mesh
    CIDR allow-list before authentication regardless of process readiness.
    The audit sink stays the `NullAuditSink` default until the real M19
    `audit` module implements a concrete `emit()` (tracked by that module's
    own ticket); wiring a real sink here is a one-line change once it lands.
    """
    resolved = settings or get_settings()
    app = FastAPI(
        title="CandleViewer API",
        version=resolved.version,
    )
    ctx = build_app_context(resolved)
    app.state.app_context = ctx
    # E04-T02: outermost (added last) so every request - even a mesh rejection -
    # gets a correlation id and the X-Correlation-Id response header.
    app.add_middleware(
        MeshOnlyMiddleware,
        allow_list=CidrAllowList(list(resolved.mesh_cidrs)),
        trusted_proxy_header=resolved.mesh_trusted_proxy_header,
        trusted_proxy_address=resolved.mesh_trusted_proxy_address,
    )
    overrides = LogLevelOverrides()
    app.state.log_level_overrides = overrides
    # `principal_resolver=None` -> fails closed with 501 until E09-S03 (as /admin/audit).
    app.include_router(make_log_level_router(overrides, _LazyAuditEmitter(ctx.audit)))
    app.include_router(
        make_health_router(resolved, ctx.metrics, mesh_read_only_gate=ctx.oms_read_only_gate)
    )
    app.include_router(make_auth_router(ctx.auth, ctx.audit))
    # E09-S03: session routes; revocation is pushed to sockets via the hub
    # (4401). Identity provider is E09-T03, so refresh/session return 501 and
    # every route answers 503 until a session repository is wired.
    revocation_hub = RevocationHub()
    app.state.revocation_hub = revocation_hub
    app.include_router(
        make_session_router(ctx.auth, ctx.audit, publish_revocation=_hub_publisher(revocation_hub))
    )
    # `principal_resolver` stays `None` here: session verification is E09-S03
    # scope (`auth/login_service.py`'s own docstring — "non-MFA session
    # issuance is E09-S03 scope"), not this router's. Every `/admin/audit*`
    # request therefore fails closed with `501` until that lands and this
    # call is updated to inject the real resolver (PR #1608 review finding 1
    # / QA defect #1596 blocker 1 — tracked as still partially open until
    # E09-S03 wires a resolver here).
    app.include_router(make_audit_router(ctx.audit))
    # QA defect #1622 blocker: `/market/klines` (E08-S06 core deliverable)
    # was missing entirely — cache-only reads today (`ctx.storage.
    # market_data`); backfilling from the exchange itself is wired once
    # E08-T02 lands a real `exchange.bybit` adapter (see `api/market.py`
    # module docstring). `principal_resolver` stays `None` for the same
    # reason as `make_audit_router` above (no session-verification module
    # wired yet) — every request fails closed with `501`, not with a silent
    # unauthenticated read (C-12.4, PR #1626 review finding: this route was
    # previously reachable by any mesh caller with no RBAC check at all).
    app.include_router(make_market_router(lambda: ctx.storage.market_data))
    # E08-S01-2: served from the scheduler's in-memory snapshot; `503` until
    # `wire_instrument_catalogue()` attaches one (needs a real Postgres +
    # exchange REST client). Resolver `None` -> fail-closed `501` (see above).
    app.include_router(make_instruments_router(lambda: ctx.ingestion.instruments))
    app.add_middleware(CorrelationMiddleware)
    return app


def wire_instrument_catalogue(
    ctx: AppContext,
    *,
    fetch_instruments: InstrumentsFetcher,
    relational: SqlAlchemyRelationalRepository,
) -> InstrumentsRefreshScheduler:
    """Compose the E08-S01-2 catalogue: the exchange adapter's neutral
    instruments fetcher (M4, built by the adapter and passed in as the
    neutral `InstrumentsFetcher` port) + Postgres repository (M10) + bus
    publisher (M5) -> ingestion (M6) scheduler. Only this composition root
    sees all four modules (C-3.1)."""
    bus = ctx.bus.bus
    env = ctx.settings.environment.value

    async def _publish(event: InstrumentUpdatedEvent) -> None:
        topic = Topic(env=env, domain="instruments", symbol=event.symbol, detail="updated")
        await bus.publish(topic, event)

    scheduler = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch_instruments,
        repository=SqlAlchemyInstrumentsRepository(relational),
        publish=_publish,
    )
    ctx.ingestion.attach_instruments(scheduler)
    return scheduler
