"""tests/xstate_contract/test_b09_rule_instance.py — B9 `rule_instance` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B9.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B9.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E35) are recorded as `deferred:E35` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import entry_of, exits
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("rule_instance")

INVARIANTS: dict[str, str] = {
    "INV-B9-a": "deferred:E35",
    "INV-B9-b": "deferred:E35",
    "INV-B9-c": "test_inv_b9_c_safety_limits_on_acting_entry",
    "INV-B9-d": "test_inv_b9_d_kill_switched_exits_only_by_elevated_rearm",
    "INV-B9-e": "deferred:E35",
    "INV-B9-f": "deferred:E35",
}


def test_b09_invariant_ledger_matches_catalogue() -> None:
    check_ledger(9, INVARIANTS, globals())


def test_inv_b9_c_safety_limits_on_acting_entry() -> None:
    assert entry_of(CHART, "acting")[0] == "assert_safety_limits"


def test_inv_b9_d_kill_switched_exits_only_by_elevated_rearm() -> None:
    assert [(e, g) for e, g, _t in exits(CHART, "kill_switched")] == [
        ("HUMAN_REARM", "rearm_permitted_and_elevated")
    ]
