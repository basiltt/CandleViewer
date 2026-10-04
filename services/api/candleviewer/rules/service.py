"""Lifecycle contract for the rules module (M15).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.rules.manager import (
    Audit,
    Broadcast,
    InMemoryRuleStore,
    RulesManager,
    RuleStore,
)
from candleviewer.rules.vocabulary import MetricRegistry, default_registry

if TYPE_CHECKING:
    from candleviewer.app import AppContext


class RulesService:
    """Empty scaffold for the M15 `rules` module lifecycle."""

    def __init__(self) -> None:
        self._started = False
        self._registry: MetricRegistry | None = None
        self._manager: RulesManager | None = None
        self._store: RuleStore = InMemoryRuleStore()
        self._audit: Audit | None = None
        self._broadcast: Broadcast | None = None

    def bind(
        self,
        *,
        store: RuleStore | None = None,
        audit: Audit | None = None,
        broadcast: Broadcast | None = None,
    ) -> None:
        """Composition-root wiring (store / audit / WS fan-out); call before `start`."""
        if store is not None:
            self._store = store
        self._audit, self._broadcast = audit, broadcast

    def manager(self) -> RulesManager | None:
        """The store/version/mode manager while the module runs; `None` otherwise (-> 503)."""
        return self._manager if self._started else None

    def registry(self) -> MetricRegistry | None:
        """Metric registry while the engine module is running; `None` otherwise (-> 503)."""
        return self._registry if self._started else None

    async def start(self, ctx: AppContext) -> None:
        """Start the module. No-op until the owning epic implements it."""
        self._registry = default_registry()
        self._manager = RulesManager(self._store, self._registry)
        if self._audit is not None:
            self._manager.set_hooks(audit=self._audit)
        if self._broadcast is not None:
            self._manager.set_hooks(broadcast=self._broadcast)
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        self._started = False
        self._registry = None
        self._manager = None

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")
