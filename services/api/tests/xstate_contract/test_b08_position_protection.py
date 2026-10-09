"""tests/xstate_contract/test_b08_position_protection.py — B8 contract module (#1650).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B8.3 arm (both service spellings) and the persist→restore round-trip run
from the generated suites. This module pins the §B8.7 ledger and adds the golden
traces for the *Corrected 2026-10-09* KILL arm (owner decision #1778 item X):
`sl.on.KILL` → non-terminal `sl.frozen`, native SL untouched (C-2.6, C-4.14),
audited, plain-bool flag published (C-2.20). Explicit native-SL assertion:
from `frozen`, no event sequence runs a service or an SL-changing action.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.statechart.bindings import b08_position_protection as b08
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import (
    Charts,
    all_events,
    entry_of,
    exits,
    instrument,
    node_at,
    park,
    settle,
    walk,
)
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("position_protection")
SL_STATES = tuple(p.split(".", 1)[1] for p, _n in walk(CHART) if p.startswith("sl."))
_EVENTS = sorted(all_events(CHART))
#: Anything that could attach/amend/cancel/detach an SL or act on the position.
_SL_EFFECTS = {
    "arm_sl_deadline",
    "bump_attach_attempts",
    "consider_reduce_only_close",
    "stamp_naked_since",
    "bump_fallback_attempts",
}
_FROZEN_ALLOWED = {"audit_amend_refused_frozen", "audit_frozen_event"}

INVARIANTS: dict[str, str] = {
    "INV-B8-a": "test_inv_b8_a_protected_only_from_exchange_read",
    "INV-B8-b": "test_inv_b8_b_tightens_only_is_deny_polarity",
    "INV-B8-c": "deferred:E32",
    "INV-B8-d": "test_inv_b8_d_unrecoverable_pages_and_considers_close",
    "INV-B8-e": "deferred:E32",
    "INV-B8-f": "deferred:E32",
    "INV-B8-g": "test_inv_b8_g_frozen_never_touches_native_sl_property",
}


def test_b08_invariant_ledger_matches_catalogue() -> None:
    check_ledger(8, INVARIANTS, globals())


def test_inv_b8_a_protected_only_from_exchange_read() -> None:
    into = {
        (p, e)
        for p, _n in walk(CHART)
        for e, _g, t in exits(CHART, p)
        if t == "position_protection.sl.protected"
    }
    assert into == {("sl.verifying", "onDone"), ("sl.naked_unrecoverable", "SL_OBSERVED")}
    assert all(
        t != "position_protection.sl.protected" for _e, _g, t in exits(CHART, "sl.attaching")
    )


def test_inv_b8_b_tightens_only_is_deny_polarity() -> None:
    assert b08.GUARDS["tightens_only"](CHART["context"], {}) is False
    arms = node_at(CHART, "sl.protected")["on"]["TIGHTEN_SL"]
    assert arms[-1] == {"actions": ["audit_guard_denied"]}


def test_inv_b8_d_unrecoverable_pages_and_considers_close() -> None:
    assert entry_of(CHART, "sl.naked_unrecoverable") == ["page_owner", "consider_reduce_only_close"]


def test_b08_chart_is_sl_protection_tagged_and_frozen_is_not_final() -> None:
    assert CHART["meta"] == {"cv:slProtection": True}
    frozen = node_at(CHART, "sl.frozen")
    assert frozen.get("type") != "final"
    assert not ({"invoke", "after", "always", "states"} & set(frozen))
    assert all("target" not in arm for arm in frozen["on"].values())
    assert entry_of(CHART, "sl.frozen") == ["audit_kill", "publish_frozen_flag"]


@pytest.mark.parametrize("state", SL_STATES)
async def test_b08_kill_from_every_sl_state_freezes_and_audits(
    state: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = instrument("position_protection", monkeypatch, "async_def")
    monkeypatch.setitem(b08.ACTIONS, "publish_frozen_flag", b08.publish_frozen_flag)
    res = await park("position_protection", CHART, f"sl.{state}", charts)
    interp = res.interpreter
    try:
        rec.actions.clear()  # parking at `frozen` already ran its entry
        await interp.send("KILL", wait=True)
        await settle()
        assert "position_protection.sl.frozen" in interp.current_state_ids
        assert interp.context["frozen"] is True
        expected = 1 if state != "frozen" else 0  # self-KILL in frozen only audits
        assert rec.actions.count("audit_kill") == expected
        assert interp.error is None
    finally:
        await interp.stop()
        b08.clear_frozen_flags()


async def test_b08_frozen_publishes_plain_bool_flag(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrument("position_protection", monkeypatch, "async_def")
    monkeypatch.setitem(b08.ACTIONS, "publish_frozen_flag", b08.publish_frozen_flag)
    res = await park("position_protection", CHART, "sl.protected", charts)
    try:
        res.interpreter.context.update(account_id="acc-1", symbol="BTCUSDT")
        assert b08.is_frozen("acc-1", "BTCUSDT") is False
        await res.interpreter.send("KILL", wait=True)
        assert b08.is_frozen("acc-1", "BTCUSDT") is True
        assert b08.is_frozen("acc-2", "BTCUSDT") is False
    finally:
        await res.interpreter.stop()
        b08.clear_frozen_flags()


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(events=st.lists(st.sampled_from(_EVENTS), min_size=1, max_size=12))
async def test_inv_b8_g_frozen_never_touches_native_sl_property(
    events: list[str], charts: Charts
) -> None:
    """Native-SL assertion (C-2.6): any event sequence delivered to `frozen` leaves
    the `sl` region in `frozen`, starts no service, and runs only audit actions in
    that region — never an SL attach/amend/cancel."""
    started: list[str] = []
    with pytest.MonkeyPatch.context() as mp:
        rec = instrument("position_protection", mp, "async_def")
        for name in list(b08.SERVICES):

            async def _svc(*_a: object, _n: str = name, **_k: object) -> None:
                started.append(_n)

            mp.setitem(b08.SERVICES, name, _svc)
        res = await park("position_protection", CHART, "sl.frozen", charts)
        interp = res.interpreter
        try:
            rec.actions.clear()
            for ev in events:
                await interp.send(ev, wait=True)
            await settle()
            assert "position_protection.sl.frozen" in interp.current_state_ids
            assert started == []
            assert not _SL_EFFECTS & set(rec.actions)
            sl_actions = {a for a in rec.actions if a.startswith("audit_")}
            assert sl_actions <= _FROZEN_ALLOWED
            assert interp.error is None
        finally:
            await interp.stop()
