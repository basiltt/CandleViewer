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

import asyncio
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

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
    make_rules_router,
    make_ticker_router,
    make_trades_router,
)
from candleviewer.api.audit_principal import SessionAuditPrincipalResolver
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import (
    assert_app_routes_declared,
    declared_operations,
    make_deny_undeclared_dependency,
)
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.api.hotkey_audit import make_hotkey_audit_router
from candleviewer.api.invites import make_invites_router
from candleviewer.api.onboarding import make_onboarding_router
from candleviewer.api.onboarding_checklist import StepResult, bybit_key_restriction
from candleviewer.api.sessions import make_session_router
from candleviewer.api.step_up import make_read_only_guard, make_step_up_router
from candleviewer.api.support_bundle import make_support_bundle_router
from candleviewer.api.telemetry import SessionKeyResolver, make_telemetry_router
from candleviewer.api.users import SnapshotResolver, UserRoleStore, make_users_router
from candleviewer.auth.models import (
    InviteRecord,
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
from candleviewer.exchange.base.models import TickerEvent, TradeEvent
from candleviewer.exchange.base.service import ExchangeBaseService
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.health_wiring import (
    HealthSystemPublisher,
    PgSystemEventReader,
    PgSystemEventWriter,
    register_real_probes,
)
from candleviewer.ingestion.clock import ClockGuard, ServerTimeFetcher, rest_client_fetcher
from candleviewer.ingestion.connection import MAX_FRAME_BYTES, ConnectionManager
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.service import IngestionService
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import TradeStream
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
from candleviewer.observability.support_bundle import filter_config
from candleviewer.observability.support_bundle_wiring import build_support_bundle_service
from candleviewer.observability.telemetry import SessionRateLimiter, TelemetrySink
from candleviewer.oms.service import OmsService
from candleviewer.orderflow.service import OrderflowService
from candleviewer.paper.service import PaperService
from candleviewer.recorder.service import RecorderService
from candleviewer.replay.service import ReplayService
from candleviewer.risk.service import RiskService
from candleviewer.rules.service import RulesService
from candleviewer.settings import Environment, Settings, get_settings
from candleviewer.statechart.bindings.b16_session import set_audit_sink as set_b16_audit_sink
from candleviewer.statechart.gateway import GatewayOverloadedError
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.observability import LoggingSystemEventSink
from candleviewer.storage.cold.scrub import ScrubTask
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.instruments_sqlalchemy import (
    SqlAlchemyInstrumentsRepository,
)
from candleviewer.storage.repositories.invites_sqlalchemy import SqlAlchemyInviteRepository
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.onboarding_sqlalchemy import SqlAlchemyOnboardingStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.rows import TickerRow, TradeRow
from candleviewer.storage.repositories.rules_sqlalchemy import SqlAlchemyRulesRepository
from candleviewer.storage.repositories.sessions_sqlalchemy import (
    SqlAlchemySessionRepository,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from candleviewer.storage.retention.rule_prune import RulePruneTask
from candleviewer.storage.retention.schedule import RetentionSchedule
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
        invite_repository=SqlAlchemyInviteRepository(relational, _record_factory(InviteRecord)),
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


async def gateway_overloaded_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Map a refused statechart inbox to RFC 7807 HTTP 503 (E50-T15, CV-C33)."""
    return JSONResponse(
        status_code=GatewayOverloadedError.status_code,
        content={
            "type": "about:blank",
            "title": "Service Unavailable",
            "status": GatewayOverloadedError.status_code,
            "detail": str(exc),
        },
        headers={"Retry-After": "1"},
        media_type="application/problem+json",
    )


class _NoPositionStore:
    """Open-position provider for the reset preview while no position store
    exists on main (`oms/` is a scaffold; `positions` lands with
    `0006_trading_core`). Reports the state as unknown - never 0 - so the
    preview says so and the reset demands `acknowledge_unknown_positions`.
    Replace with the OMS read model when it lands."""

    source = "not_deployed"

    async def open_position_count(self, user_id: str) -> int | None:
        return None


class _OnboardingMetrics:
    """Adapts the metrics facade to the router's `inc(name, **labels)` port."""

    _SPECS: ClassVar[dict[str, tuple[str, ...]]] = {
        "onboarding_checklist_views_total": (),
        "onboarding_step_state_total": ("step", "state"),
        "onboarding_checklist_dismissed_total": (),
        "onboarding_probe_timeouts_total": ("step",),
    }
    _BUCKETS: ClassVar[tuple[float, ...]] = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0)

    def __init__(self, metrics: Metrics) -> None:
        self._m = {
            n: metrics.counter(n, f"E09-S06 {n}", labels) for n, labels in self._SPECS.items()
        }

        self._latency = metrics.histogram(
            "onboarding_checklist_duration_seconds",
            "E09-S06 checklist assembly latency",
            (),
            buckets=self._BUCKETS,
        )

    def observe_latency(self, seconds: float) -> None:
        self._latency.child().observe(seconds)

    def inc(self, name: str, **labels: str) -> None:
        metric = self._m[name]
        child = metric.labels(*labels.values()) if labels else metric.child()
        child.inc()


def _build_onboarding_router(
    settings: Settings,
    ctx: Any,
    principal_resolver: Any,
    metrics: _OnboardingMetrics,
    store_override: Any = None,
) -> Any:
    store = store_override
    probes: dict[str, Any] = {}
    if store is None and settings.storage_backend == "real":
        store = SqlAlchemyOnboardingStore(
            SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "onboarding")
        )
    if store is not None:

        async def tailscale(_u: Any) -> StepResult:
            # Run the E09-T04 binding self-check itself (read-only; no gate mutation).
            result = await asyncio.to_thread(ctx.mesh_self_check.check.run)
            if not result.safe:
                return StepResult("blocked", "The mesh-only network check is failing.")
            return StepResult("ok")

        async def totp(u: Any) -> StepResult:
            if await store.has_confirmed_totp(u):
                return StepResult("ok")
            return StepResult("pending", "Enrol an authenticator app.")

        async def sub_account(u: Any) -> StepResult:
            if await store.has_account_binding(u):
                return StepResult("ok")
            return StepResult("pending", "No sub-account is bound to you yet.")

        async def api_key(u: Any) -> StepResult:
            # Real probe: The exchange blocks key creation for 48 h after the sub-account
            # binding (US-ONB-007). Key inventory itself ships with E27.
            bound_at = await store.latest_binding_at(u)
            if bound_at is None:
                return StepResult("pending", "Bind a sub-account first.")
            # NOTE: exchange_accounts (E27) does not exist yet; binding time is the only
            # available proxy for account creation. Swap when E27 lands.
            restricted = bybit_key_restriction(bound_at, datetime.now(UTC))
            if restricted is not None:
                return restricted
            # Key inventory (E27) has not shipped: stay pending, never satisfied.
            return StepResult("pending", "API-key inventory is coming soon.")

        probes = {
            "tailscale": tailscale,
            "totp": totp,
            "sub_account": sub_account,
            "api_key": api_key,
        }

    # Steps whose owning epics (E39 limits, E27 demo sessions) have not shipped have
    # no probe and are switched off in the flag table: they render `pending`
    # ("coming soon") and keep the card incomplete/undismissable until they ship.
    flags: dict[str, bool] = {"profile_limits": False, "demo_session": False}
    return make_onboarding_router(
        store, principal_resolver, probes, flags, metrics, _LazyAuditEmitter(ctx.audit)
    )


class _RuleCompileTelemetry:
    """E35-T04: compile counters + a high-severity telemetry event on form/graph divergence."""

    def __init__(self, metrics: Metrics) -> None:
        self._compiles = metrics.counter(
            "rule_compile_total", "E35-T04 rule compiles", ("editor", "result")
        )
        self._diverged = metrics.counter(
            "rule_roundtrip_divergence_total", "E35-T04 form/graph divergences (high severity)",
            ("editor",),
        )  # fmt: skip

    def on_compile(self, editor: str, result: str) -> None:
        self._compiles.labels(editor, result).inc()

    def on_divergence(self, editor: str, n_diffs: int) -> None:
        self._diverged.labels(editor).inc()
        structlog.get_logger("candleviewer.rules").error(
            "rule_roundtrip_divergence", editor=editor, diffs=n_diffs, severity="high"
        )


def create_app(
    settings: Settings | None = None,
    *,
    snapshot_loader: SnapshotLoader | None = None,
    user_role_store: UserRoleStore | None = None,
    principal_resolver: SnapshotResolver | None = None,
    ws_authenticate: Authenticate | None = None,
    auth_clock: Callable[[], datetime] | None = None,
    onboarding_store: Any = None,
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
    app.add_exception_handler(GatewayOverloadedError, gateway_overloaded_handler)
    install_error_redaction(app)  # E43-T06: no secret echo via 422/500 bodies
    ctx = build_app_context(resolved, auth_clock=auth_clock)
    app.state.app_context = ctx
    if resolved.ingestion_ws_enabled:
        wire_public_ws(ctx)
    # E07-X02 (SR-094): supervised weekly scrub; started/stopped by the lifespan.
    app.state.scrub_task = (
        ScrubTask(
            DatasetRegistry(resolved.parquet_root),
            LoggingSystemEventSink(),
            interval_s=float(resolved.scrub_interval_s),
        )
        if resolved.scrub_enabled
        else None
    )
    # E35-T02: unmatched rule-run retention prune; started by the lifespan only
    # when `retention_enabled` (RetentionSchedule.rule_jobs()).
    app.state.rule_prune_task = RulePruneTask(
        SqlAlchemyRulesRepository(
            SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "rules")
        ),
        RetentionSchedule.from_settings(resolved),
    )
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
    # E09-S04: step-up, owner TOTP reset and the read-only write guard.
    app.include_router(
        make_step_up_router(
            ctx.auth,
            _LazyAuditEmitter(ctx.audit),
            principal_resolver=principal_resolver,
            positions=_NoPositionStore(),
            users=user_role_store,
        )
    )
    # B16 audit actions write through the M19 emitter (PR #1674 finding 3).
    set_b16_audit_sink(_LazyAuditEmitter(ctx.audit))
    app.middleware("http")(make_read_only_guard(ctx.auth, _LazyAuditEmitter(ctx.audit)))
    # Audit emitter + notifier are mandatory; store/resolver `None` -> 501.
    app.include_router(
        make_users_router(
            user_role_store, _LazyAuditEmitter(ctx.audit), principal_resolver, ws_registry
        )
    )
    app.include_router(
        make_invites_router(ctx.auth, _LazyAuditEmitter(ctx.audit), principal_resolver)
    )
    # QA #1596: real session-backed resolver; without an identity provider
    # (fake backend) it stays `None` and every call fails closed with 501.
    audit_resolver = (
        SessionAuditPrincipalResolver(lambda: ctx.auth.sessions, identity)
        if identity is not None
        else None
    )
    app.include_router(make_audit_router(ctx.audit, audit_resolver))
    app.include_router(make_hotkey_audit_router(_LazyAuditEmitter(ctx.audit), audit_resolver))
    # E04-T06: frontend telemetry push. One facade per process on ctx.metrics
    # (the lifespan's MetricsRuntime reuses it). Session-authenticated via the
    # same session resolver; `None` (fake backend) fails closed with 501.
    # Process collectors read /proc; the lifespan adds them (no I/O here).
    metrics_facade = Metrics(resolved.environment.value, registry=ctx.metrics)
    app.state.metrics_facade = metrics_facade
    # E09-S06: server-evaluated first-run checklist. Steps whose owning epic
    # has not shipped (E27 api_key/demo, E39 profile limits) have no probe and
    # render `pending` ("coming soon") via the flag table, never a client stub.
    app.include_router(
        _build_onboarding_router(
            resolved,
            ctx,
            principal_resolver,
            _OnboardingMetrics(metrics_facade),
            onboarding_store,
        )
    )
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
    # E04-S02: support bundle. Real collectors (log ring, /metrics registry,
    # health snapshot, system_events); RBAC via the session resolver, `None`
    # (fake backend) fails closed with 501.
    support_bundle = build_support_bundle_service(
        registry=ctx.metrics,
        metrics=metrics_facade,
        health=health_registry,
        events_query=PgSystemEventReader(health_pg) if health_pg is not None else None,
        config=filter_config(os.environ),
        build_info={
            "version": resolved.version,
            "git_sha": resolved.git_sha,
            "environment": resolved.environment.value,
        },
        out_dir=Path(resolved.parquet_root).parent / "support_bundles",
    )
    app.state.support_bundle = support_bundle
    app.include_router(
        make_support_bundle_router(support_bundle, _LazyAuditEmitter(ctx.audit), audit_resolver)
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
    # E08-S03: merged ticker snapshot; session-backed resolver (501 only without identity).
    app.include_router(
        make_ticker_router(lambda: ctx.ingestion.tickers, principal_resolver=audit_resolver)
    )
    # E08-S04: in-memory hot tape (newest-first); same resolver/fail-closed rules.
    app.include_router(
        make_trades_router(lambda: ctx.ingestion.trades, principal_resolver=audit_resolver)
    )
    # E35-T03: rule vocabulary + IR schema (fail-closed 501 without a resolver).
    rule_telemetry = _RuleCompileTelemetry(metrics_facade)
    app.include_router(
        make_rules_router(
            lambda: ctx.rules.registry(),
            principal_resolver=audit_resolver,
            recorded_symbols=lambda: ctx.recorder.recorded_symbols(),
            on_compile=rule_telemetry.on_compile,
            on_divergence=rule_telemetry.on_divergence,
        )
    )
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


def wire_public_ws(ctx: AppContext) -> ConnectionManager:
    """E08-T04 (flag `ingestion_ws_enabled`, default off — C-4.13): compose the
    public WS skeleton. The exchange adapter (M4) supplies the socket factory and
    topic vocabulary; ingestion (M6) owns the connection lifecycle and is
    started/stopped by the module supervisor (tracked tasks, bounded frame
    queue — C-2.18). Public stream only: no credentials are involved."""
    env = ctx.settings.environment.value
    clock = time.monotonic
    adapter = ctx.exchange_bybit
    watchdog = StalenessWatchdog(clock, lambda _e: None, kind_of=adapter.topic_kind)
    manager = ConnectionManager(
        adapter.public_socket_factory(env, max_frame_bytes=MAX_FRAME_BYTES),
        SubscriptionPlanner(),
        watchdog,
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
    rest = adapter.public_rest_client(env)
    wire_clock_offset(ctx, rest_client_fetcher(rest))
    ctx.ingestion.attach_closer(rest.aclose)

    def _is_listed(symbol: str) -> bool:
        # Only catalogue symbols may become topics (E08-S03 security note).
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        inst = snap.get(symbol) if snap is not None else None
        return inst is not None and inst.status == "trading"

    class _TickerWriter:
        """Write-behind to the hot tier incl. best bid/ask (21-database-schema.md `tickers`)."""

        async def write_ticker(self, event: TickerEvent) -> None:
            zero = "0"
            await ctx.storage.market_data.write_tickers(
                [
                    TickerRow(
                        ts_us=event.ts_event,
                        symbol=event.symbol,
                        last_price=str(event.last_price or zero),
                        mark_price=str(event.mark_price or zero),
                        index_price=str(event.index_price or zero),
                        funding_rate=str(event.funding_rate or zero),
                        open_interest=str(event.open_interest or zero),
                        bid1_price=None if event.bid1_price is None else str(event.bid1_price),
                        bid1_size=None if event.bid1_qty is None else str(event.bid1_qty),
                        ask1_price=None if event.ask1_price is None else str(event.ask1_price),
                        ask1_size=None if event.ask1_qty is None else str(event.ask1_qty),
                    )
                ]
            )

    # Each stream owns a slice of the upstream topic set; the socket gets the union.
    demand: dict[str, set[str]] = {}

    def _set_desired(stream: str, topics: set[str]) -> None:
        demand[stream] = set(topics)
        manager.set_desired(set().union(*demand.values()))

    class _TradeWriter:
        """Batched write-behind to the hot tier (21-database-schema.md `trades`)."""

        async def write_trades(self, events: Sequence[TradeEvent]) -> None:
            await ctx.storage.market_data.write_trades(
                [
                    TradeRow(
                        ts_us=e.ts_event,
                        symbol=e.symbol,
                        price=str(e.price),
                        qty=str(e.qty),
                        side=e.side,
                        trade_id=e.trade_id,
                    )
                    for e in events
                ]
            )

    def _tick_size(symbol: str) -> Decimal | None:
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        inst = snap.get(symbol) if snap is not None else None
        return None if inst is None else inst.tick_size

    ctx.ingestion.attach_trades(
        TradeStream(
            bus=ctx.bus.bus,
            env=env,
            set_desired=lambda topics: _set_desired("trade", topics),
            parse_frame=adapter.parse_trade_frame,
            topic_for=adapter.trade_topic,
            is_listed=_is_listed,
            touch=watchdog.touch,
            fetch_recent=adapter.recent_trades_fetcher(rest.get_public),
            tick_size=_tick_size,
            clock=clock,
            writer=_TradeWriter(),
        )
    )
    ctx.ingestion.attach_tickers(
        TickerStream(
            bus=ctx.bus.bus,
            env=env,
            set_desired=lambda topics: _set_desired("ticker", topics),
            parse_frame=adapter.parse_ticker_frame,
            topic_for=adapter.ticker_topic,
            is_listed=_is_listed,
            touch=watchdog.touch,
            clock=clock,
            writer=_TickerWriter(),
        )
    )
    return manager


def wire_clock_offset(ctx: AppContext, fetch_server_time: ServerTimeFetcher) -> ClockGuard:
    """E04-T06: compose ClockGuard over the adapter's REST server-time fetcher
    (`rest_client_fetcher`); its offset corrects the exchange latency stage.
    The guard's periodic task is started by whoever owns the REST client."""
    guard = ClockGuard(fetch_server_time)
    ctx.ingestion.attach_clock(guard)
    return guard
