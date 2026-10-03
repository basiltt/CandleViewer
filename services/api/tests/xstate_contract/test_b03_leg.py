"""tests/xstate_contract/test_b03_leg.py — B3 `leg` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B3.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B3.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E34) are recorded as `deferred:E34` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import exits, is_terminal
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("leg")

INVARIANTS: dict[str, str] = {
    "INV-B3-a": "deferred:E34",
    "INV-B3-b": "deferred:E34",
    "INV-B3-c": "deferred:E34",
    "INV-B3-d": "deferred:E34",
    "INV-B3-e": "test_inv_b3_e_close_exhaustion_reaches_visible_error",
}


def test_b03_invariant_ledger_matches_catalogue() -> None:
    check_ledger(3, INVARIANTS, globals())


def test_inv_b3_e_close_exhaustion_reaches_visible_error() -> None:
    """Once `close_attempts_left` is denied, `verify_flat` leaves the retry
    loop for `verify_sl` (INV-B3-d: SL verified after every close attempt),
    whose only exits are the visible terminal `error`."""
    arms = exits(CHART, "unwinding.verify_flat")
    retry = [t for _e, g, t in arms if g == "close_attempts_left"]
    assert retry == ["leg.unwinding.close_position"]
    fall = {t for e, g, t in arms if g is None}
    assert fall == {"leg.unwinding.verify_sl"}
    assert {t for _e, _g, t in exits(CHART, "unwinding.verify_sl")} == {"leg.error"}
    assert is_terminal(CHART, "error")
