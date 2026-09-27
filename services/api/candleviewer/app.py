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

from dataclasses import dataclass

from fastapi import FastAPI
from prometheus_client import CollectorRegistry

from candleviewer.accounts.service import AccountsService
from candleviewer.admin.service import AdminService
from candleviewer.admin.wiring import (
    AuditHandle,
    SecretsHandle,
    build_audit_service,
    build_secrets_service,
)
from candleviewer.alerts.service import AlertsService
from candleviewer.api import make_health_router
from candleviewer.auth.service import AuthService
from candleviewer.bars.service import BarsService
from candleviewer.book.service import BookService
from candleviewer.bus.service import BusService
from candleviewer.exchange.base.service import ExchangeBaseService
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.ingestion.service import IngestionService
from candleviewer.journal.service import JournalService
from candleviewer.observability.service import ObservabilityService
from candleviewer.oms.service import OmsService
from candleviewer.orderflow.service import OrderflowService
from candleviewer.paper.service import PaperService
from candleviewer.recorder.service import RecorderService
from candleviewer.replay.service import ReplayService
from candleviewer.risk.service import RiskService
from candleviewer.rules.service import RulesService
from candleviewer.settings import Settings, get_settings
from candleviewer.storage.service import StorageService
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


def build_app_context(settings: Settings | None = None) -> AppContext:
    """Construct an `AppContext` with real scaffold modules, no I/O performed.

    Every field is a live instance of its module's scaffold `service.py` —
    constructing them does no network/DB work (each `__init__` only sets
    `_started = False`), which is what keeps `create_app()` fast and
    fake-only per the acceptance criteria.
    """
    resolved = settings or get_settings()
    return AppContext(
        settings=resolved,
        metrics=CollectorRegistry(),
        secrets=build_secrets_service(),
        exchange_base=ExchangeBaseService(),
        exchange_bybit=ExchangeBybitService(),
        bus=BusService(),
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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application without touching Postgres/QuestDB/network.

    Per E02-T05 acceptance criterion 3: constructing the app with fakes-only
    settings must not perform I/O, and `GET /healthz` must return 200 with a
    build-info body. The module supervisor is *not* started here — that is
    driven by the ASGI lifespan in `services/api/main.py` (or a test's own
    fixture), keeping `create_app()` itself synchronous and side-effect-free.
    """
    resolved = settings or get_settings()
    app = FastAPI(
        title="CandleViewer API",
        version=resolved.version,
    )
    app.state.app_context = build_app_context(resolved)
    app.include_router(make_health_router(resolved, app.state.app_context.metrics))
    return app
