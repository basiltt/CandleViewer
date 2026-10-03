"""tests/xstate_contract/test_b18_kill_switch.py — B18 `kill_switch` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B18.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B18.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E39) are recorded as `deferred:E39` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import entry_of, exits
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("kill_switch")

INVARIANTS: dict[str, str] = {
    "INV-B18-a": "test_inv_b18_a_block_runs_first_on_engaging_entry",
    "INV-B18-b": "deferred:E39",
    "INV-B18-c": "test_inv_b18_c_engaged_only_when_all_flat",
    "INV-B18-d": "deferred:E39",
    "INV-B18-e": "deferred:E39",
    "INV-B18-f": "test_b10_b20_kill_fallthrough.py::test_guard_denied_event_takes_audit_arm",
}


def test_b18_invariant_ledger_matches_catalogue() -> None:
    check_ledger(18, INVARIANTS, globals())


def test_inv_b18_a_block_runs_first_on_engaging_entry() -> None:
    assert entry_of(CHART, "engaging")[0] == "block_new_orders_immediately"


def test_inv_b18_c_engaged_only_when_all_flat() -> None:
    """Once flattening is requested, `engaged` is reachable only through the
    `all_accounts_flat` guard; every other outcome is `engaged_incomplete`."""
    arms = exits(CHART, "flattening")
    assert [(g, t) for _e, g, t in arms if t == "kill_switch.engaged"] == [
        ("all_accounts_flat", "kill_switch.engaged")
    ]
    others = {t for _e, g, t in arms if g is None}
    assert others == {"kill_switch.engaged_incomplete"}
