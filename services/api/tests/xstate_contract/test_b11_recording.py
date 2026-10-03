"""tests/xstate_contract/test_b11_recording.py — B11 `recording` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B11.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B11.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E16) are recorded as `deferred:E16` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import entry_of, exits
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("recording")

INVARIANTS: dict[str, str] = {
    "INV-B11-a": "deferred:E16",
    "INV-B11-b": "test_inv_b11_b_reason_added_cancels_linger",
    "INV-B11-c": "deferred:E16",
    "INV-B11-d": "test_inv_b11_d_degraded_exits_only_when_all_healthy",
}


def test_b11_invariant_ledger_matches_catalogue() -> None:
    check_ledger(11, INVARIANTS, globals())


def test_inv_b11_b_reason_added_cancels_linger() -> None:
    assert ("REASON_ADDED", None, "recording.recording") in exits(CHART, "lingering")
    assert "cancel_linger" in entry_of(CHART, "recording")


def test_inv_b11_d_degraded_exits_only_when_all_healthy() -> None:
    healthy = [g for e, g, _t in exits(CHART, "degraded") if e == "STREAM_HEALTHY"]
    assert healthy == ["all_streams_healthy"]
