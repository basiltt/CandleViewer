"""Lifecycle for the alerts module (M22): starts/stops the `AlertEvaluator` (E40-T03).

The composition root `bind()`s a factory; `start()` warms the evaluator up (one
subscription per distinct `condition_hash`) and runs it in its own tracked task;
`stop()` drains so an in-flight firing completes or rolls back whole. Without a bound
factory (or with `alerts_evaluator_enabled` off, C-4.13) the module stays idle.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from candleviewer.alerts.evaluator import AlertEvaluator, AlertTick
from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext

EvaluatorFactory = Callable[[], Awaitable[AlertEvaluator | None]]


class AlertsService:
    def __init__(self) -> None:
        self._started = False
        self._factory: EvaluatorFactory | None = None
        self.evaluator: AlertEvaluator | None = None

    def bind(self, factory: EvaluatorFactory) -> None:
        self._factory = factory

    async def start(self, ctx: AppContext) -> None:
        self._started = True
        if self._factory is None:
            return
        ev = await self._factory()
        if ev is not None:
            await ev.warm_up()
            ev.start()
        self.evaluator = ev

    async def on_alert_changed(self, alert_id: str) -> None:
        """The in-process create/update/delete/enable event emitted by `/alerts`."""
        if self.evaluator is not None:
            await self.evaluator.on_alert_changed(alert_id)

    def submit_tick(self, tick: AlertTick) -> bool:
        if self.evaluator is None:
            return False
        self.evaluator.submit(tick)
        return True

    async def stop(self, grace_s: float) -> None:
        ev, self.evaluator = self.evaluator, None
        if ev is not None:
            await ev.stop(grace_s)
        self._started = False

    def health(self) -> HealthReport:
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        detail = "evaluator running" if self.evaluator is not None else "evaluator idle"
        return HealthReport(module="", status=status, detail=detail)
