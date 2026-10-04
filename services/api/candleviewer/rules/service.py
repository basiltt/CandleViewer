"""Lifecycle contract for the rules module (M15).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.rules.evaluator import Evaluator, SnapshotBuilder
from candleviewer.rules.evaluator.engine import EvaluationResult
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.manager import (
    Audit,
    Broadcast,
    InMemoryRuleStore,
    RulesManager,
    RuleStore,
)
from candleviewer.rules.runner import (
    EvalTick,
    PushedMetricSource,
    RuleEvaluationRunner,
    default_clocks,
)
from candleviewer.rules.vocabulary import MetricRegistry, default_registry

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from candleviewer.app import AppContext


class RulesService:
    """Empty scaffold for the M15 `rules` module lifecycle."""

    def __init__(self) -> None:
        self._started = False
        self._tasks: set[asyncio.Task[bool]] = set()
        self._registry: MetricRegistry | None = None
        self._manager: RulesManager | None = None
        self._store: RuleStore = InMemoryRuleStore()
        self._audit: Audit | None = None
        self._broadcast: Broadcast | None = None
        #: E35-S02-B1: set by `start()` only when `rules_evaluator_enabled` (C-4.13).
        self.metric_source: PushedMetricSource | None = None
        self.runner: RuleEvaluationRunner | None = None

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

    def evaluation_sink(self) -> Callable[[EvaluationResult], None]:
        """Sync `Evaluator(on_result=...)` consumer: schedules recording on the manager
        (per evaluation, off the hot path); dropped silently while the module is stopped."""

        def _sink(result: EvaluationResult) -> None:
            m = self.manager()
            if m is None:
                return
            task = asyncio.get_running_loop().create_task(m.consume_evaluation(result))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        return _sink

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
        if ctx is not None and ctx.settings.rules_evaluator_enabled:
            self._start_evaluator()

    def _start_evaluator(self) -> None:
        manager = self._manager
        if manager is None:
            raise RuntimeError("rules manager not built")
        wall, mono = default_clocks()
        self.metric_source = PushedMetricSource()

        def _factory(rule: Rule, snaps: SnapshotBuilder) -> Evaluator:
            # Fail-closed (#1806): no scope gate exists until E35-S04's `build_evaluator`,
            # so only simulate-mode rules are evaluated (see `_simulate_only`); armed rules
            # are never evaluated by this bare Evaluator.
            return Evaluator(rule, snaps, wall, mono, on_result=self.evaluation_sink())

        async def _simulate_only() -> list[Rule]:
            return await manager.evaluable_rules(("simulate",))

        def _on_error(exc: Exception) -> None:
            _log.error("rule evaluator tick failed", exc_info=exc)

        self.runner = RuleEvaluationRunner(
            _simulate_only, SnapshotBuilder(self.metric_source), _factory,
            self.evaluation_sink(), _on_error,
        )  # fmt: skip
        self.runner.start()

    def submit_tick(self, trigger_type: str, symbol: str | None = None) -> bool:
        """Producer entry point (market/bar/snapshot adapters): queue an evaluation tick.
        Returns False when the evaluator is disabled/stopped."""
        if self.runner is None:
            return False
        self.runner.submit(EvalTick(trigger_type, symbol))
        return True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds: stop the live B9 rule charts."""
        self._started = False
        if self.runner is not None:
            await self.runner.stop()
        self.runner = self.metric_source = None
        if self._manager is not None:
            await self._manager.lifecycle.stop()
        self._registry = None
        self._manager = None

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")
