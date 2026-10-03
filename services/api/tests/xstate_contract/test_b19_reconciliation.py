"""tests/xstate_contract/test_b19_reconciliation.py — B19 `reconciliation` contract (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B19.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B19.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E45) are recorded as `deferred:E45` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import entry_of
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("reconciliation")

INVARIANTS: dict[str, str] = {
    "INV-B19-a": "deferred:E45",
    "INV-B19-b": "test_inv_b19_b_stale_lockout_locks_account",
    "INV-B19-c": "deferred:E45",
    "INV-B19-d": "deferred:E45",
    "INV-B19-e": "deferred:E45",
    "INV-B19-f": "test_inv_b19_f_every_sweep_persists_a_report",
}


def test_b19_invariant_ledger_matches_catalogue() -> None:
    check_ledger(19, INVARIANTS, globals())


def test_inv_b19_b_stale_lockout_locks_account() -> None:
    assert "lock_account_for_new_orders" in entry_of(CHART, "stale_lockout")


def test_inv_b19_f_every_sweep_persists_a_report() -> None:
    assert entry_of(CHART, "reporting")[0] == "persist_report"
