"""tests/xstate_contract/test_b12_replay.py — B12 `replay` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B12.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B12.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E26) are recorded as `deferred:E26` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import exits
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("replay")

INVARIANTS: dict[str, str] = {
    "INV-B12-a": "deferred:E26",
    "INV-B12-b": "test_inv_b12_b_only_seek_rewinds",
    "INV-B12-c": "deferred:E26",
    "INV-B12-d": "deferred:E26",
    "INV-B12-e": "deferred:E26",
}


def test_b12_invariant_ledger_matches_catalogue() -> None:
    check_ledger(12, INVARIANTS, globals())


def test_inv_b12_b_only_seek_rewinds() -> None:
    """Only SEEK may move a finished/errored session back to a cursor state."""
    for state in ("finished", "error"):
        assert {e for e, _g, t in exits(CHART, state) if t != "replay.destroyed"} == {"SEEK"}
