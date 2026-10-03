"""tests/xstate_contract/test_b02_trade_group.py — B2 `trade_group` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B2.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B2.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E34) are recorded as `deferred:E34` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import exits
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("trade_group")

INVARIANTS: dict[str, str] = {
    "INV-B2-a": "deferred:E34",
    "INV-B2-b": "deferred:E34",
    "INV-B2-c": "test_inv_b2_c_all_or_none_never_rests_partially_open",
    "INV-B2-d": "deferred:E34",
    "INV-B2-e": "deferred:E34",
}


def test_b02_invariant_ledger_matches_catalogue() -> None:
    check_ledger(2, INVARIANTS, globals())


def test_inv_b2_c_all_or_none_never_rests_partially_open() -> None:
    """`policy_all_or_none_and_any_failed` is evaluated ahead of every
    EVALUATE arm into `partially_open` and routes elsewhere (the unwind)."""
    arms = [(g, t) for e, g, t in exits(CHART, "submitting") if e == "EVALUATE"]
    guards = [g for g, _t in arms]
    aon = guards.index("policy_all_or_none_and_any_failed")
    into_partial = [i for i, (_g, t) in enumerate(arms) if t == "trade_group.partially_open"]
    assert all(i > aon for i in into_partial)
    assert arms[aon][1] != "trade_group.partially_open"
