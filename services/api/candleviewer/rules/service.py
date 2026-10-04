"""Lifecycle contract for the rules module (M15).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

import asyncio
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
from candleviewer.rules.runner import PushedMetricSource, RuleEvaluationRunner, default_clocks
from candleviewer.rules.vocabulary import MetricRegistry, default_registry

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
            # E35-S04 (#1806): swap for `build_evaluator` so the scope gate is mandatory.
            return Evaluator(rule, snaps, wall, mono, on_result=self.evaluation_sink())

        self.runner = RuleEvaluationRunner(
            manager.evaluable_rules, SnapshotBuilder(self.metric_source), _factory,
            lambda _r: None,
        )  # fmt: skip
        self.runner.start()

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
