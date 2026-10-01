"""`CvMetricsPlugin` — exports the `cv_machine_*` Prometheus families (E50-T60).

Names come from the metric catalogue (`observability/metrics_catalogue.py`,
mirrored in 20-architecture.md §12.1) and are registered through the
`Metrics` facade (env label, cardinality guard). Counters only ever go up
from hooks; nothing here polls `last_error` (CV-C50/C59).
"""

from __future__ import annotations

from typing import Any, Final

from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.statechart.plugins._base import HookFailureCounter, contained

#: The families this plugin owns (all `planned`/E50 in the catalogue).
FAMILIES: Final[tuple[str, ...]] = (
    "cv_machine_transitions_total",
    "cv_machine_send_refused_total",
    "cv_machine_chain_trips_total",
    "cv_machine_timer_handles",
    "cv_machine_dropped_receipts_total",
)

#: Internal library init record — not a committed transition.
_INIT_EVENT: Final = "___xstate_statemachine_init___"


def register_machine_families(metrics: Metrics) -> dict[str, BoundedMetric]:
    """Idempotently register the plugin's families on *metrics*."""
    specs = {s.name: s for s in CATALOGUE}
    out: dict[str, BoundedMetric] = {}
    for name in FAMILIES:
        spec = specs[name]
        if spec.kind == "counter":
            out[name] = metrics.counter(name, spec.help, spec.labels, max_series=spec.max_series)
        else:
            out[name] = metrics.gauge(name, spec.help, spec.labels, max_series=spec.max_series)
    return out


class CvMetricsPlugin(HookFailureCounter):
    """One instance per interpreter; children are pre-bound per `kind`."""

    def __init__(self, *, machine_kind: str, metrics: Metrics) -> None:
        super().__init__()
        self.machine_kind = machine_kind
        fam = register_machine_families(metrics)
        self._refused = fam["cv_machine_send_refused_total"]
        self._transitions = fam["cv_machine_transitions_total"].labels(machine_kind)
        self._chain_trips = fam["cv_machine_chain_trips_total"].labels(machine_kind)
        self._timer_handles = fam["cv_machine_timer_handles"].labels(machine_kind)
        self._dropped_receipts = fam["cv_machine_dropped_receipts_total"].labels(machine_kind)

    def record_send_refused(self, reason: str) -> None:
        """Called by the gateway when `send()` raised (e.g. `QueueOverflowError`
        under `overflow_policy="refuse"`, reason `queue_full`)."""
        self._refused.labels(self.machine_kind, reason).inc()

    @contained
    def on_transition(
        self, interpreter: Any, from_states: Any, to_states: Any, transition: Any
    ) -> None:
        if str(getattr(transition, "event", "")) != _INIT_EVENT:
            self._transitions.inc()
        self._sample_timers(interpreter)

    def _sample_timers(self, interpreter: Any) -> None:
        handles = getattr(interpreter, "_timer_handles", None) or {}
        self._timer_handles.set(sum(len(v) for v in handles.values()))

    @contained
    def on_event_dropped(self, interpreter: Any, event: Any, reason: str) -> None:
        self._refused.labels(self.machine_kind, str(reason)).inc()

    @contained
    def on_invalid_event(self, interpreter: Any, error: BaseException, raw_event: Any) -> None:
        self._refused.labels(self.machine_kind, "invalid_event").inc()

    @contained
    def on_chain_budget_exceeded(self, interpreter: Any, error: BaseException, event: Any) -> None:
        self._chain_trips.inc()

    @contained
    def on_receipt_dropped(self, interpreter: Any, event_type: str) -> None:
        self._dropped_receipts.inc()

    @contained
    def on_interpreter_stop(self, interpreter: Any) -> None:
        self._timer_handles.set(0)
