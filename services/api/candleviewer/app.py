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

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI

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
    make_health_report_router,
    make_health_router,
    make_instruments_router,
    make_log_level_router,
    make_market_router,
)
from candleviewer.api.audit_principal import SessionAuditPrincipalResolver
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import (
    assert_app_routes_declared,
    declared_operations,
    make_deny_undeclared_dependency,
)
from candleviewer.api.sessions import make_session_router
from candleviewer.api.telemetry import SessionKeyResolver, make_telemetry_router
from candleviewer.api.users import SnapshotResolver, UserRoleStore, make_users_router
from candleviewer.auth.models import (
    MfaChallengeRecord,
    MfaMethodRecord,
    SessionRecord,
    UserRecord,
)
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.bars.service import BarsService
from candleviewer.book.service import BookService
from candleviewer.bus.models import Topic
from candleviewer.bus.service import BusService
from candleviewer.domain.events import InstrumentUpdatedEvent
from candleviewer.exchange.base.instruments import InstrumentsFetcher
from candleviewer.exchange.base.service import ExchangeBaseService
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.health_wiring import (
    HealthSystemPublisher,
    PgSystemEventWriter,
    register_real_probes,
)
from candleviewer.ingestion.clock import ClockGuard, ServerTimeFetcher, rest_client_fetcher
from candleviewer.ingestion.connection import MAX_FRAME_BYTES, ConnectionManager
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.service import IngestionService
from candleviewer.ingestion.watchdog import StalenessWatchdog
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
from candleviewer.observability.health_metrics import bind_health_metrics
from candleviewer.observability.health_probes import HealthRegistry
from candleviewer.observability.latency import StageRecorder
from candleviewer.observability.log_level import LogLevelOverrides
from candleviewer.observability.metrics import CollectorRegistry, Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.observability.service import ObservabilityService
from candleviewer.observability.telemetry import SessionRateLimiter, TelemetrySink
from candleviewer.oms.service import OmsService
from candleviewer.orderflow.service import OrderflowService
from candleviewer.paper.service import PaperService
from candleviewer.recorder.service import RecorderService
from candleviewer.replay.service import ReplayService
from candleviewer.risk.service import RiskService
from candleviewer.rules.service import RulesService
from candleviewer.settings import Environment, Settings, get_settings
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.instruments_sqlalchemy import (
    SqlAlchemyInstrumentsRepository,
)
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import (
    SqlAlchemySessionRepository,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from candleviewer.storage.service import StorageService
from candleviewer.ws.gateway import Authenticate, make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry
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


def _decode_key(name: str, secret: Any) -> bytes | None:
    if secret is None:
        return None
    try:
        key = bytes.fromhex(secret.get_secret_value())
    except ValueError as exc:
        raise ValueError(f"{name} must be hex-encoded") from exc
    if len(key) != 32:
        raise ValueError(f"{name} must decode to exactly 32 bytes, got {len(key)}")
    return key


def build_auth_service(
    settings: Settings, *, clock: Callable[[], datetime] | None = None
) -> AuthService:
    """QA #1658: wire `AuthService` to Postgres when `storage_backend="real"`
    (no I/O at construction: the engine connects lazily). With the fake
    backend it stays the no-op scaffold so `create_app()` needs no database.
    Live refuses to start (any backend) without pepper + key material."""
    totp = settings.auth_totp_key_hex
    rc = settings.auth_recovery_hmac_key_hex
    pepper = settings.auth_pepper.get_secret_value()
    real = settings.storage_backend == "real"
    if settings.environment is Environment.LIVE or real:
        if totp is None or rc is None:
            raise ValueError(
                "CV_AUTH_TOTP_KEY_HEX and CV_AUTH_RECOVERY_HMAC_KEY_HEX are required "
                "(live or storage_backend=real); refusing to start auth (C-12 TOTP)"
            )
        if not pepper:
            raise ValueError(
                "a non-empty CV_AUTH_PEPPER is required (live or storage_backend=real); "
                "refusing to start auth"
            )
    totp_key = _decode_key("CV_AUTH_TOTP_KEY_HEX", totp)
    rc_key = _decode_key("CV_AUTH_RECOVERY_HMAC_KEY_HEX", rc)
    if not real:
        return AuthService()
    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "auth")
    return AuthService(
        SqlAlchemyUserRepository(
            relational, _record_factory(UserRecord), clock=clock or (lambda: datetime.now(UTC))
        ),
        pepper=settings.auth_pepper.get_secret_value(),
        mfa_repository=SqlAlchemyMfaRepository(
            relational, _record_factory(MfaMethodRecord), _record_factory(MfaChallengeRecord)
        ),
        totp_encryption_key=totp_key,
        recovery_code_hmac_key=rc_key,
        session_repository=SqlAlchemySessionRepository(relational, _record_factory(SessionRecord)),
        clock=clock,
    )


def build_identity_provider(settings: Settings) -> SqlAlchemyIdentityProvider | None:
    """QA #1658: the SQL `User`/permissions read path for `/auth/session` and
    the post-MFA `AuthenticatedResponse`; `None` (routes fail closed with 501)
    on the fake backend."""
    if settings.storage_backend != "real":
        return None
    return SqlAlchemyIdentityProvider(
        SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "identity")
    )


def _build_audit(settings: Settings) -> AuditHandle:
    """QA #1658 (C-2.9): the real hash-chained audit sink on the real backend."""
    if settings.storage_backend != "real":
        return build_audit_service()
    return build_audit_service(
        SqlAlchemyAuditRepository(
            SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "audit")
        )
    )


def _record_factory(model: Any) -> Callable[..., Any]:
    return lambda **fields: model.model_validate(fields)


def build_app_context(
    settings: Settings | None = None, *, auth_clock: Callable[[], datetime] | None = None
) -> AppContext:
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
        auth=build_auth_service(resolved, clock=auth_clock),
        audit=_build_audit(resolved),
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


@lru_cache(maxsize=1)
def _cached_spec() -> dict[str, Any]:
    """The 500 KB contract parse costs ~2 s; parse once per process."""
    return load_openapi_spec()


async def _deny_all_snapshot(user_id: uuid.UUID) -> PrincipalSnapshot:
    """Fail closed until the session/identity store (E09-S03) resolves real snapshots."""
    return PrincipalSnapshot(user_id, frozenset(), frozenset())


def _now_ms() -> int:
    return int(time.time() * 1000)


def _session_authenticator(ctx: AppContext) -> Authenticate:
    """Opaque bearer token -> (session_id, user_id) via the session service;
    raises (fail closed) while no session repository is wired."""

    async def _authenticate(token: str) -> tuple[str, uuid.UUID]:
        record = await ctx.auth.sessions.authenticate_access_token(token)
        return str(record.id), record.user_id

    return _authenticate


SnapshotLoader = Callable[[uuid.UUID], Awaitable[PrincipalSnapshot]]


def create_app(
    settings: Settings | None = None,
    *,
    snapshot_loader: SnapshotLoader | None = None,
    user_role_store: UserRoleStore | None = None,
    principal_resolver: SnapshotResolver | None = None,
    ws_authenticate: Authenticate | None = None,
    auth_clock: Callable[[], datetime] | None = None,
) -> FastAPI:
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
    spec = _cached_spec()
    app = FastAPI(
        title="CandleViewer API",
        version=resolved.version,
        dependencies=[Depends(make_deny_undeclared_dependency(declared_operations(spec)))],
    )
    ctx = build_app_context(resolved, auth_clock=auth_clock)
    app.state.app_context = ctx
    if resolved.ingestion_ws_enabled:
        wire_public_ws(ctx)
    identity = build_identity_provider(resolved)
    app.state.identity_provider = identity
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
    # E04-T04: cached component health. Unbuilt modules register `not_deployed`
    # probes; the ticker is started/stopped by the lifespan (`app.state`).
    health_pg = (
        SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "health")
        if resolved.storage_backend == "real"
        else None
    )
    app.state.health_pg = health_pg
    health_registry = HealthRegistry(
        events=PgSystemEventWriter(health_pg) if health_pg is not None else None,
        on_snapshot=HealthSystemPublisher(ctx.bus.bus, resolved.environment.value),
    )
    health_registry.register_placeholders()
    if health_pg is not None:
        q_host, _, q_port = resolved.questdb_pg.partition(":")
        register_real_probes(
            health_registry,
            pg_repo=health_pg,
            questdb_host=q_host,
            questdb_port=int(q_port or 8812),
            parquet_root=resolved.parquet_root,
            disk_path=resolved.parquet_root,
        )
    bind_health_metrics(health_registry, ctx.metrics, resolved)
    app.state.health_registry = health_registry
    app.include_router(
        make_health_report_router(
            health_registry,
            version=resolved.version,
            git_sha=resolved.git_sha,
            environment=resolved.environment.value,
        )
    )
    app.include_router(make_auth_router(ctx.auth, ctx.audit, identity=identity))
    # E09-S03: session routes; revocation is pushed to sockets via the hub
    # (4401). Identity provider is E09-T03, so refresh/session return 501 and
    # every route answers 503 until a session repository is wired.
    revocation_hub = RevocationHub()
    app.state.revocation_hub = revocation_hub
    app.include_router(
        make_session_router(
            ctx.auth,
            ctx.audit,
            identity=identity,
            publish_revocation=_hub_publisher(revocation_hub),
            allowed_origins=resolved.allowed_origin_set,
        )
    )
    # QA #1648 d1: live WS gateway. Role changes (`PUT /users/{id}/roles`)
    # notify the registry, which pushes `permission_change` and revokes
    # now-forbidden subscriptions. Snapshots fail closed (no permissions)
    # until the identity store is injected.
    ws_registry = ConnectionRegistry(snapshot_loader or _deny_all_snapshot, _now_ms)
    app.state.ws_registry = ws_registry
    app.include_router(
        make_ws_router(
            authenticate=ws_authenticate or _session_authenticator(ctx),
            registry=ws_registry,
            revocation_hub=revocation_hub,
        )
    )
    # Audit emitter + notifier are mandatory; store/resolver `None` -> 501.
    app.include_router(
        make_users_router(
            user_role_store, _LazyAuditEmitter(ctx.audit), principal_resolver, ws_registry
        )
    )
    # QA #1596: real session-backed resolver; without an identity provider
    # (fake backend) it stays `None` and every call fails closed with 501.
    audit_resolver = (
        SessionAuditPrincipalResolver(lambda: ctx.auth.sessions, identity)
        if identity is not None
        else None
    )
    app.include_router(make_audit_router(ctx.audit, audit_resolver))
    # E04-T06: frontend telemetry push. One facade per process on ctx.metrics
    # (the lifespan's MetricsRuntime reuses it). Session-authenticated via the
    # same session resolver; `None` (fake backend) fails closed with 501.
    # Process collectors read /proc; the lifespan adds them (no I/O here).
    metrics_facade = Metrics(resolved.environment.value, registry=ctx.metrics)
    app.state.metrics_facade = metrics_facade
    # E04-T06: per-stage tick latency on the real ingestion publish path.
    # Offset = ClockGuard's measured exchange-local offset (E08 wires it via
    # `ctx.ingestion.clock_offset_ms`); the synthetic feed reports 0.
    register_r0(metrics_facade)  # idempotent; the lifespan reuses this facade
    ctx.ingestion.attach_latency(
        StageRecorder(metrics_facade.get("ingest_stage_seconds"), resolved.telemetry_sample_n)
    )
    app.include_router(
        make_telemetry_router(
            TelemetrySink(metrics_facade),
            SessionRateLimiter(time.monotonic),
            SessionKeyResolver(audit_resolver) if audit_resolver is not None else None,
            enabled=resolved.telemetry_enabled,
        )
    )
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
    # E09-T03 / #1648: a served route without an RBAC declaration fails the build.
    assert_app_routes_declared(app, spec)
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


_PUBLIC_REST_BASE = {
    "live": "https://api.bybit.com",
    "demo": "https://api.bybit.com",
    "testnet": "https://api-testnet.bybit.com",
}


def wire_public_ws(ctx: AppContext) -> ConnectionManager:
    """E08-T04 (flag `ingestion_ws_enabled`, default off — C-4.13): compose the
    public WS skeleton. The exchange adapter (M4) supplies the socket factory and
    topic vocabulary; ingestion (M6) owns the connection lifecycle and is
    started/stopped by the module supervisor (tracked tasks, bounded frame
    queue — C-2.18). Public stream only: no credentials are involved."""
    env = ctx.settings.environment.value
    clock = time.monotonic
    adapter = ctx.exchange_bybit
    manager = ConnectionManager(
        adapter.public_socket_factory(env, max_frame_bytes=MAX_FRAME_BYTES),
        SubscriptionPlanner(),
        StalenessWatchdog(clock, lambda _e: None, kind_of=adapter.topic_kind),
        ReconnectPolicy(),
        ConnectionRateGuard(clock),
        ctx.ingestion.offer_frame,
        bus=ctx.bus.bus,
        env=env,
    )
    ctx.ingestion.attach_ws(manager)
    # E04-T06: measure the exchange clock offset (public /v5/market/time, no
    # credentials) so the exchange latency stage is available; started and
    # stopped with ingestion. Public data always uses the live host (demo has
    # no separate public feed).
    base = _PUBLIC_REST_BASE.get(env, _PUBLIC_REST_BASE["live"])
    rest = BybitRestClient(RestClientConfig(base_url=base))
    wire_clock_offset(ctx, rest_client_fetcher(rest))
    ctx.ingestion.attach_closer(rest.aclose)
    return manager


def wire_clock_offset(ctx: AppContext, fetch_server_time: ServerTimeFetcher) -> ClockGuard:
    """E04-T06: compose ClockGuard over the adapter's REST server-time fetcher
    (`rest_client_fetcher`); its offset corrects the exchange latency stage.
    The guard's periodic task is started by whoever owns the REST client."""
    guard = ClockGuard(fetch_server_time)
    ctx.ingestion.attach_clock(guard)
    return guard
