"""tests/xstate_contract/test_b10_alert.py — B10 `alert` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B10.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B10.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E40) are recorded as `deferred:E40` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import entry_of, exits, is_terminal, node_at
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("alert")

INVARIANTS: dict[str, str] = {
    "INV-B10-a": "test_inv_b10_a_exhaustion_reaches_visible_delivery_failed",
    "INV-B10-b": "deferred:E40",
    "INV-B10-c": "test_inv_b10_c_suppression_is_counted_and_metricised",
    "INV-B10-d": "test_inv_b10_d_fired_row_persisted_on_firing_entry",
}


def test_b10_invariant_ledger_matches_catalogue() -> None:
    check_ledger(10, INVARIANTS, globals())


def test_inv_b10_a_exhaustion_reaches_visible_delivery_failed() -> None:
    err = [(g, t) for e, g, t in exits(CHART, "firing") if e == "onError"]
    assert err[-1] == (None, "alert.delivery_failed")
    assert not is_terminal(CHART, "delivery_failed")  # visible, acknowledgeable


def test_inv_b10_c_suppression_is_counted_and_metricised() -> None:
    assert {"bump_storm_count", "emit_suppression_metric"} <= set(entry_of(CHART, "suppressed"))


def test_inv_b10_d_fired_row_persisted_on_firing_entry() -> None:
    """Entry actions run before the state's invoke starts."""
    assert entry_of(CHART, "firing")[0] == "persist_fired_row"
    assert node_at(CHART, "firing")["invoke"]["src"] == "dispatch_to_channels"
