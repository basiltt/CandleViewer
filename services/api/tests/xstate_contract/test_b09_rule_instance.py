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

from candleviewer.statechart.bindings.b09_rule_instance import (
    GUARDS,
    promotion_gate_satisfied_and_permitted,
    rearm_permitted_and_elevated,
)
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import entry_of, exits
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("rule_instance")

INVARIANTS: dict[str, str] = {
    "INV-B9-a": "deferred:E35",
    "INV-B9-b": "deferred:E35",
    "INV-B9-c": "test_inv_b9_c_safety_limits_on_acting_entry",
    "INV-B9-d": "test_inv_b9_d_kill_switched_exits_only_by_elevated_rearm",
    "INV-B9-e": "test_inv_b9_e_promotion_gate_is_deny_polarity",
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


class _Ctx:
    def __init__(self, **kw: object) -> None:
        self.context = dict(kw)


_HOUR_US = 3_600_000_000


def test_inv_b9_e_promotion_gate_is_deny_polarity() -> None:
    gate = promotion_gate_satisfied_and_permitted
    assert GUARDS["promotion_gate_satisfied_and_permitted"] is gate
    ok = {"permitted": True, "now_us": 1}
    assert gate(_Ctx(simulation_fires=5), ok) is True  # fires gate
    assert gate(_Ctx(simulation_fires=0, simulation_started_us=0), {**ok, "now_us": 24 * _HOUR_US})
    assert (
        gate(_Ctx(simulation_fires=4, simulation_started_us=0), {**ok, "now_us": _HOUR_US}) is False
    )
    assert gate(_Ctx(simulation_fires=9), {"permitted": False}) is False  # not permitted
    assert gate(_Ctx(simulation_fires=9), {}) is False  # unevaluable never promotes
    assert gate(_Ctx(simulation_fires="x"), ok) is False  # malformed -> deny, never raise
    assert gate() is False
    own = {"permitted": True, "is_owner": True, "owner_override_reason": "why"}
    assert gate(_Ctx(simulation_fires=0), own) is True  # audited Owner override
    assert gate(_Ctx(simulation_fires=0), {**own, "is_owner": False}) is False


def test_inv_b9_d_rearm_guard_needs_permission_and_step_up() -> None:
    g = rearm_permitted_and_elevated
    assert g(_Ctx(), {"permitted": True, "elevated": True}) is True
    assert g(_Ctx(), {"permitted": True}) is False
    assert g(_Ctx(), {"elevated": True}) is False
    assert g() is False
