"""tests/xstate_contract/test_b14_book.py — B14 `book` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B14.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B14.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E08) are recorded as `deferred:E08` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import entry_of, exits
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("book")

INVARIANTS: dict[str, str] = {
    "INV-B14-a": "deferred:E08",
    "INV-B14-b": "deferred:E08",
    "INV-B14-c": "test_inv_b14_c_gap_always_drops_and_resnapshots",
    "INV-B14-d": (
        "test_e50_t14b_round5_fixes.py::test_oc08_property_inv_b14_d_buffer_never_exceeds_bound"
    ),
    "INV-B14-e": "test_inv_b14_e_resync_count_exported",
}


def test_b14_invariant_ledger_matches_catalogue() -> None:
    check_ledger(14, INVARIANTS, globals())


def test_inv_b14_c_gap_always_drops_and_resnapshots() -> None:
    assert [g for e, g, _t in exits(CHART, "live") if e == "SEQUENCE_GAP"] == [None]
    assert exits(CHART, "desynced") == [("always", None, "book.snapshot_pending")]
    assert "clear_buffer" in entry_of(CHART, "snapshot_pending")


def test_inv_b14_e_resync_count_exported() -> None:
    assert {"bump_resync_count", "emit_resync_metric"} <= set(entry_of(CHART, "desynced"))
