"""tests/xstate_contract/test_b04_oco.py — B4 `oco` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B4.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B4.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E33) are recorded as `deferred:E33` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import exits, walk
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("oco")

INVARIANTS: dict[str, str] = {
    "INV-B4-a": "deferred:E33",
    "INV-B4-b": "test_inv_b4_b_completed_only_via_children_terminal",
    "INV-B4-c": "deferred:E33",
    "INV-B4-d": "deferred:E33",
}


def test_b04_invariant_ledger_matches_catalogue() -> None:
    check_ledger(4, INVARIANTS, globals())


def test_inv_b4_b_completed_only_via_children_terminal() -> None:
    into = [(p, e) for p, _n in walk(CHART) for e, _g, t in exits(CHART, p) if t == "oco.completed"]
    assert into == [("completing", "CHILDREN_TERMINAL")]
