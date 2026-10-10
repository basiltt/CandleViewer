"""tests/xstate_contract/test_b08_position_protection.py — B8 contract module (#1650).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B8.3 arm (both service spellings) and the persist→restore round-trip run
from the generated suites. This module pins the §B8.7 ledger and adds the golden
traces for the *Corrected 2026-10-09* KILL design (owner decision #1778 item X,
redesigned per PR #2133 review): `sl.on.KILL` is audit-only so an in-flight
attach / verify / fallback / page always completes (C-2.6), and KILL flips the
parallel `amend_lock` region to the non-terminal `frozen`, which refuses
(audited) every SL amendment and publishes a plain bool (C-2.20).
"""

from __future__ import annotations

import asyncio

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
_EVENTS = sorted(e for e in all_events(CHART) if e != "KILL")
#: Where the `sl` region may come to rest: confirmed SL, audited page, or flat.
_SETTLED = {"flat", "protected", "naked_unrecoverable"}

INVARIANTS: dict[str, str] = {
    "INV-B8-a": "test_inv_b8_a_protected_only_from_exchange_read",
    "INV-B8-b": "test_inv_b8_b_tightens_only_is_deny_polarity",
    "INV-B8-c": "deferred:E32",
    "INV-B8-d": "test_inv_b8_d_unrecoverable_pages_and_considers_close",
    "INV-B8-e": "deferred:E32",
    "INV-B8-f": "deferred:E32",
    "INV-B8-g": "test_inv_b8_g_kill_never_abandons_sl_from_initial_property",
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
    assert arms[0]["guard"] == "amend_locked" and "target" not in arms[0]
    assert arms[-1] == {"actions": ["audit_guard_denied"]}
    assert b08.amend_locked({"frozen": True}, {}) is True
    assert b08.amend_locked({}, {}) is False


def test_inv_b8_d_unrecoverable_pages_and_considers_close() -> None:
    assert entry_of(CHART, "sl.naked_unrecoverable") == ["page_owner", "consider_reduce_only_close"]


def test_b08_kill_structure_keeps_sl_path_and_freezes_lock_region() -> None:
    assert CHART["meta"] == {"cv:slProtection": True}
    assert CHART["states"]["sl"]["on"]["KILL"] == {"actions": ["audit_kill_sl_continues"]}
    assert "frozen" not in CHART["states"]["sl"]["states"]
    frozen = node_at(CHART, "amend_lock.frozen")
    assert frozen.get("type") != "final"
    assert not ({"invoke", "after", "always", "states"} & set(frozen))
    assert all("target" not in arm for arm in frozen["on"].values())
    assert entry_of(CHART, "amend_lock.frozen") == ["audit_kill", "publish_frozen_flag"]


def _real(mp: pytest.MonkeyPatch) -> None:
    mp.setitem(b08.ACTIONS, "publish_frozen_flag", b08.publish_frozen_flag)
    mp.setitem(b08.GUARDS, "amend_locked", b08.amend_locked)


@pytest.mark.parametrize("state", ["attaching", "verifying", "naked"])
async def test_b08_kill_during_unconfirmed_sl_lets_attach_finish(
    state: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KILL while the SL is unconfirmed: the in-flight service is not cancelled, and
    its completion still drives `sl` to `protected` (C-2.6)."""
    gate = asyncio.Event()
    rec = instrument(
        "position_protection", monkeypatch, "async_def", guards={"exchange_reports_sl": True}
    )
    _real(monkeypatch)

    async def _gated(*_a: object, **_k: object) -> dict[str, object]:
        await gate.wait()
        return {}

    for name in ("attach_native_sl", "read_position_sl", "attach_fallback_sl"):
        monkeypatch.setitem(b08.SERVICES, name, _gated)
    res = await park("position_protection", CHART, f"sl.{state}", charts)
    interp = res.interpreter
    try:
        await settle()
        await interp.send("KILL", wait=True)
        await settle()
        assert f"position_protection.sl.{state}" in interp.current_state_ids
        assert "position_protection.amend_lock.frozen" in interp.current_state_ids
        assert rec.actions.count("audit_kill_sl_continues") == 1
        assert rec.actions.count("audit_kill") == 1
        gate.set()
        for _ in range(4):
            await settle()
        assert "position_protection.sl.protected" in interp.current_state_ids
        assert interp.error is None
    finally:
        await interp.stop()
        b08.clear_frozen_flags()


async def test_b08_frozen_refuses_amend_with_audit(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = instrument(
        "position_protection",
        monkeypatch,
        "async_def",
        guards={"tightens_only": True, "explicit_audited_override": True},
    )
    _real(monkeypatch)
    res = await park("position_protection", CHART, "sl.protected", charts)
    interp = res.interpreter
    try:
        await interp.send("KILL", wait=True)
        for ev in ("TIGHTEN_SL", "LOOSEN_SL"):
            await interp.send(ev, wait=True)
        await settle()
        assert "position_protection.sl.protected" in interp.current_state_ids
        assert rec.actions.count("audit_amend_refused_frozen") == 2
    finally:
        await interp.stop()
        b08.clear_frozen_flags()


async def _with_hook(seen: list[str]) -> None:
    async def _hook(name: str, _ctx: dict[str, object]) -> None:
        seen.append(name)

    b08.set_audit_hook(_hook)


async def test_b08_frozen_publishes_plain_bool_flag_keyed_by_ids(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrument("position_protection", monkeypatch, "async_def")
    _real(monkeypatch)
    seen: list[str] = []
    await _with_hook(seen)
    res = await park("position_protection", CHART, "sl.protected", charts)
    try:
        res.interpreter.context.update(account_id="acc-1", symbol="BTCUSDT")
        assert b08.is_frozen("acc-1", "BTCUSDT") is False
        await res.interpreter.send("KILL", wait=True)
        assert b08.is_frozen("acc-1", "BTCUSDT") is True
        assert b08.is_frozen("acc-2", "BTCUSDT") is False
        assert "frozen_flag_unkeyed" not in seen
    finally:
        await res.interpreter.stop()
        b08.set_audit_hook(None)
        b08.clear_frozen_flags()


async def test_b08_frozen_without_ids_publishes_no_anonymous_flag(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrument("position_protection", monkeypatch, "async_def")
    _real(monkeypatch)
    seen: list[str] = []
    await _with_hook(seen)
    res = await park("position_protection", CHART, "sl.protected", charts)
    try:
        await res.interpreter.send("KILL", wait=True)
        assert res.interpreter.context["frozen"] is True
        assert b08._FROZEN == {}
        assert seen == ["frozen_flag_unkeyed"]
    finally:
        await res.interpreter.stop()
        b08.set_audit_hook(None)
        b08.clear_frozen_flags()


def _sl_leaf(state_ids: set[str]) -> str:
    prefix = "position_protection.sl."
    return next(s[len(prefix) :] for s in state_ids if s.startswith(prefix))


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    data=st.data(),
    reports_sl=st.booleans(),
    attach_ok=st.booleans(),
    fallback_ok=st.booleans(),
    amend_allowed=st.booleans(),
)
async def test_inv_b8_g_kill_never_abandons_sl_from_initial_property(
    data: st.DataObject,
    reports_sl: bool,
    attach_ok: bool,
    fallback_ok: bool,
    amend_allowed: bool,
    charts: Charts,
) -> None:
    """Native-SL assertion (C-2.6) from the INITIAL state: POSITION_OPENED, an
    arbitrary event tail with KILL inserted anywhere (the first attach is held
    in flight until KILL arrives, so e.g. POSITION_OPENED → KILL → SL_OBSERVED is
    generated). After settling, `sl` rests in `protected` (confirmed SL),
    `naked_unrecoverable` with an audited page, or `flat`; and no SL amendment
    (`set_trading_stop`) ever starts once frozen."""
    tail = data.draw(st.lists(st.sampled_from(_EVENTS), max_size=8), label="tail")
    at = data.draw(st.integers(0, len(tail)), label="kill_at")
    events = ["POSITION_OPENED", *tail[:at], "KILL", *tail[at:]]
    gate = asyncio.Event()
    amends_while_frozen: list[bool] = []
    with pytest.MonkeyPatch.context() as mp:
        rec = instrument(
            "position_protection",
            mp,
            "async_def",
            guards={
                "exchange_reports_sl": reports_sl,
                "sl_observed": reports_sl,
                "tightens_only": amend_allowed,
                "explicit_audited_override": amend_allowed,
            },
        )
        _real(mp)

        async def _attach(*_a: object, **_k: object) -> dict[str, object]:
            await gate.wait()
            if not attach_ok:
                raise RuntimeError("attach failed")
            return {}

        async def _fallback(*_a: object, **_k: object) -> dict[str, object]:
            if not fallback_ok:
                raise RuntimeError("fallback failed")
            return {}

        async def _read(*_a: object, **_k: object) -> dict[str, object]:
            return {}

        async def _amend(_i: object, context: dict[str, object], *_a: object) -> None:
            if context.get("frozen") is True:
                amends_while_frozen.append(True)

        mp.setitem(b08.SERVICES, "attach_native_sl", _attach)
        mp.setitem(b08.SERVICES, "attach_fallback_sl", _fallback)
        mp.setitem(b08.SERVICES, "read_position_sl", _read)
        mp.setitem(b08.SERVICES, "set_trading_stop", _amend)
        res = await park("position_protection", CHART, "", charts)
        interp = res.interpreter
        try:
            for ev in events:
                await interp.send(ev, wait=True)
                if ev == "KILL":
                    gate.set()
                await settle()
            for _ in range(4):
                await settle()
            leaf = _sl_leaf(set(interp.current_state_ids))
            assert leaf in _SETTLED, (events, leaf)
            if leaf == "naked_unrecoverable":
                assert "page_owner" in rec.actions
            assert "position_protection.amend_lock.frozen" in interp.current_state_ids
            assert amends_while_frozen == []
            assert interp.error is None
        finally:
            await interp.stop()
            b08.clear_frozen_flags()
