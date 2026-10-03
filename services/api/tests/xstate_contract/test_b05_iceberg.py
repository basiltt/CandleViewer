"""tests/xstate_contract/test_b05_iceberg.py — B5 `iceberg` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B5.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B5.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E33) are recorded as `deferred:E33` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("iceberg")

INVARIANTS: dict[str, str] = {
    "INV-B5-a": "deferred:E33",
    "INV-B5-b": "deferred:E33",
    "INV-B5-c": "deferred:E33",
    "INV-B5-d": "deferred:E33",
    "INV-B5-e": "deferred:E33",
}


def test_b05_invariant_ledger_matches_catalogue() -> None:
    check_ledger(5, INVARIANTS, globals())
