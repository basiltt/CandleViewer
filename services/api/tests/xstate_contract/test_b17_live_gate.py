"""tests/xstate_contract/test_b17_live_gate.py — B17 `live_gate` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B17.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B17.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E44) are recorded as `deferred:E44` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import exits
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("live_gate")

INVARIANTS: dict[str, str] = {
    "INV-B17-a": "deferred:E44",
    "INV-B17-b": "deferred:E44",
    "INV-B17-c": "test_inv_b17_c_evidence_invalidated_demotes",
    "INV-B17-d": "test_inv_b17_d_emergency_disable_never_gated",
    "INV-B17-e": "deferred:E44",
}


def test_b17_invariant_ledger_matches_catalogue() -> None:
    check_ledger(17, INVARIANTS, globals())


def test_inv_b17_c_evidence_invalidated_demotes() -> None:
    for state in ("eligible", "enabled"):
        assert ("EVIDENCE_INVALIDATED", None, "live_gate.locked") in exits(CHART, state)


def test_inv_b17_d_emergency_disable_never_gated() -> None:
    arms = [g for e, g, _t in exits(CHART, "enabled") if e == "EMERGENCY_DISABLE"]
    assert arms == [None]
