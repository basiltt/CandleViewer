"""tests/xstate_contract/test_b01_order.py — B1 `order` contract module (#1650).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B1.3 arm (both service spellings) and the persist→restore round-trip run
from the generated suites (`test_contract_transitions.py`,
`test_contract_persistence.py`). This module pins the §B1.7 ledger and adds the
golden traces for the *Corrected 2026-10-09* KILL arm (owner decision #1778
item X, option a): root `KILL` → final `killed`, `halted_by_kill` set, exactly
one exchange cancel and one audit, `protection` region untouched.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import (
    Charts,
    all_events,
    entry_of,
    exits,
    instrument,
    is_terminal,
    node_at,
    park,
    settle,
    walk,
)
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("order")
TERMINALS = ("filled", "cancelled", "rejected", "expired", "killed")
LIVE = tuple(
    p.split(".", 1)[1]
    for p, _n in walk(CHART)
    if p.startswith("lifecycle.") and p.split(".", 1)[1] not in TERMINALS
)
_REAL_KILL_ACTIONS = ("mark_halted_by_kill", "issue_kill_cancel")
_SL_ACTIONS = {"request_fallback_sl", "arm_sl_deadline", "raise_naked_position_alert"}

INVARIANTS: dict[str, str] = {
    "INV-B1-a": "deferred:E29",
    "INV-B1-b": "deferred:E29",
    "INV-B1-c": "test_inv_b1_c_amend_rejected_never_terminal",
    "INV-B1-d": "test_inv_b1_d_cancel_pending_handles_exec",
    "INV-B1-e": "test_inv_b1_e_unknown_resolved_only_by_recon",
    "INV-B1-f": "test_inv_b1_f_sl_present_only_from_exchange_read",
    "INV-B1-g": "deferred:E29",
    "INV-B1-h": "test_inv_b1_h_kill_from_any_live_state_cancels_once_and_audits",
    "INV-B1-i": "test_inv_b1_i_kill_never_touches_protection_property",
}


def test_b01_invariant_ledger_matches_catalogue() -> None:
    check_ledger(1, INVARIANTS, globals())


def test_inv_b1_c_amend_rejected_never_terminal() -> None:
    out = [t for e, _g, t in exits(CHART, "lifecycle.amend_pending") if e == "AMEND_REJECTED"]
    assert out and all(t is not None and t.rsplit(".", 1)[-1] not in TERMINALS for t in out)


def test_inv_b1_d_cancel_pending_handles_exec() -> None:
    assert "EXEC" in node_at(CHART, "lifecycle.cancel_pending")["on"]


def test_inv_b1_e_unknown_resolved_only_by_recon() -> None:
    leaving = {e for e, _g, _t in exits(CHART, "lifecycle.unknown")}
    assert leaving <= {e for e in leaving if e.startswith("RECON_")}
    assert "SEND" not in leaving


def test_inv_b1_f_sl_present_only_from_exchange_read() -> None:
    into = [
        (p, e)
        for p, _n in walk(CHART)
        if p.startswith("protection.")
        for e, _g, t in exits(CHART, p)
        if t == "order.protection.sl_present"
    ]
    assert ("protection.sl_missing", "SL_OBSERVED") in into


def test_b01_killed_is_final_terminal_with_cancel_and_audit() -> None:
    assert node_at(CHART, "lifecycle.killed")["type"] == "final"
    assert is_terminal(CHART, "lifecycle.killed")
    entry = entry_of(CHART, "lifecycle.killed")
    for name in ("mark_halted_by_kill", "issue_kill_cancel", "audit_kill"):
        assert entry.count(name) == 1
    assert CHART["context"]["halted_by_kill"] is False


def _restore_real(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    cancels: list[str] = []

    async def _cancel(*_a: object, **_k: object) -> None:
        cancels.append("cancel_order")

    for name in _REAL_KILL_ACTIONS:
        monkeypatch.setitem(b01.ACTIONS, name, getattr(b01, name))
    monkeypatch.setitem(b01.SERVICES, "cancel_order", _cancel)
    return cancels


@pytest.mark.parametrize("state", LIVE)
async def test_inv_b1_h_kill_from_any_live_state_cancels_once_and_audits(
    state: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = instrument("order", monkeypatch, "async_def")
    cancels = _restore_real(monkeypatch)
    res = await park("order", CHART, f"lifecycle.{state}", charts)
    interp = res.interpreter
    try:
        await interp.send("KILL", wait=True)
        await settle()
        assert "order.lifecycle.killed" in interp.current_state_ids
        assert interp.context["halted_by_kill"] is True
        assert cancels == ["cancel_order"]
        assert rec.actions.count("audit_kill") == 1
        assert interp.error is None
    finally:
        await interp.stop()


async def test_b01_kill_cancel_failure_is_audited_not_rolled_back(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrument("order", monkeypatch, "async_def")
    _restore_real(monkeypatch)
    seen: list[str] = []

    async def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("exchange down")

    async def _hook(name: str, _ctx: dict[str, object]) -> None:
        seen.append(name)

    monkeypatch.setitem(b01.SERVICES, "cancel_order", _boom)
    b01.set_audit_hook(_hook)
    try:
        res = await park("order", CHART, "lifecycle.submitted", charts)
        await res.interpreter.send("KILL", wait=True)
        await settle()
        assert "order.lifecycle.killed" in res.interpreter.current_state_ids
        assert seen == ["kill_cancel_failed"]
        await res.interpreter.stop()
    finally:
        b01.set_audit_hook(None)


@pytest.mark.parametrize("state", TERMINALS)
async def test_b01_kill_on_terminal_only_audits(
    state: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = instrument("order", monkeypatch, "async_def")
    res = await park("order", CHART, f"lifecycle.{state}", charts)
    try:
        rec.actions.clear()
        await res.interpreter.send("KILL", wait=True)
        await settle()
        assert f"order.lifecycle.{state}" in res.interpreter.current_state_ids
        assert sorted(rec.actions) == [
            "audit_kill_ignored_terminal",
            "audit_kill_protection_retained",
        ]
    finally:
        await res.interpreter.stop()


_PROTECTION = ("not_required", "sl_pending", "sl_present", "sl_missing")
_EVENTS = sorted(all_events(CHART))


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(prot=st.sampled_from(_PROTECTION), events=st.lists(st.sampled_from(_EVENTS), max_size=6))
async def test_inv_b1_i_kill_never_touches_protection_property(
    prot: str, events: list[str], charts: Charts
) -> None:
    """Whatever came before, a KILL leaves the protection leaf as it found it and
    runs no SL action (C-2.6, C-4.14)."""
    with pytest.MonkeyPatch.context() as mp:
        rec = instrument("order", mp, "async_def")
        _restore_real(mp)
        res = await park("order", CHART, f"protection.{prot}", charts)
        interp = res.interpreter
        try:
            for ev in events:
                if ev != "KILL":
                    await interp.send(ev, wait=True)
            await settle()
            before = {s for s in interp.current_state_ids if ".protection." in s}
            mark = len(rec.actions)
            await interp.send("KILL", wait=True)
            await settle()
            after = {s for s in interp.current_state_ids if ".protection." in s}
            assert after == before
            assert not _SL_ACTIONS & set(rec.actions[mark:])
            assert "audit_kill_protection_retained" in rec.actions[mark:]
        finally:
            await interp.stop()
