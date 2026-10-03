"""tests/xstate_contract/test_b20_risk_lockout.py — B20 `risk_lockout` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B20.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B20.7 invariant ledger to the catalogue: invariants the chart
structure proves are tested here; those that depend on binding bodies (stubs
until E39) are recorded as `deferred:E39` and fail the gate the moment the
catalogue gains an unmapped row.
"""

from __future__ import annotations

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import exits
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("risk_lockout")

INVARIANTS: dict[str, str] = {
    "INV-B20-a": "deferred:E39",
    "INV-B20-b": "deferred:E39",
    "INV-B20-c": "test_inv_b20_c_daily_cap_checked_first",
    "INV-B20-d": "deferred:E39",
    "INV-B20-e": "test_inv_b20_e_manual_lock_never_cleared_by_clock",
    "INV-B20-f": "deferred:E39",
}


def test_b20_invariant_ledger_matches_catalogue() -> None:
    check_ledger(20, INVARIANTS, globals())


def test_inv_b20_c_daily_cap_checked_first() -> None:
    """Deny polarity: the breach guard is evaluated ahead of any band arm."""
    for state in ("clear", "warning"):
        pnl = [g for e, g, _t in exits(CHART, state) if e == "PNL_UPDATE"]
        assert pnl[0] == "breaches_daily_loss_cap"


def test_inv_b20_e_manual_lock_never_cleared_by_clock() -> None:
    expiry = [g for e, g, _t in exits(CHART, "locked") if e == "EXPIRY_DUE"]
    assert expiry and all(g == "until_mode_is_time_based" for g in expiry)
