"""tests/xstate_contract/test_b15_paper_account.py — B15 `paper_account` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B15.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B15.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E38) are recorded as `deferred:E38` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import entry_of, exits, node_at
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("paper_account")

INVARIANTS: dict[str, str] = {
    "INV-B15-a": "deferred:E38",
    "INV-B15-b": "test_inv_b15_b_liquidated_is_terminal",
    "INV-B15-c": "test_inv_b15_c_journal_written_before_terminal",
    "INV-B15-d": "deferred:E38",
}


def test_b15_invariant_ledger_matches_catalogue() -> None:
    check_ledger(15, INVARIANTS, globals())


def test_inv_b15_b_liquidated_is_terminal() -> None:
    assert node_at(CHART, "liquidated").get("type") == "final"


def test_inv_b15_c_journal_written_before_terminal() -> None:
    assert "write_liquidation_journal" in entry_of(CHART, "liquidating")
    assert exits(CHART, "liquidating") == [("always", None, "paper_account.liquidated")]
