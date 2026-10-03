"""tests/xstate_contract/test_b06_twap.py — B6 `twap` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B6.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B6.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E33) are recorded as `deferred:E33` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import find_state, is_terminal
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("twap")

INVARIANTS: dict[str, str] = {
    "INV-B6-a": "deferred:E33",
    "INV-B6-b": "deferred:E33",
    "INV-B6-c": "deferred:E33",
    "INV-B6-d": "test_inv_b6_d_price_blocked_is_a_state",
    "INV-B6-e": "deferred:E33",
}


def test_b06_invariant_ledger_matches_catalogue() -> None:
    check_ledger(6, INVARIANTS, globals())


def test_inv_b6_d_price_blocked_is_a_state() -> None:
    assert not is_terminal(CHART, find_state(CHART, "price_blocked"))
