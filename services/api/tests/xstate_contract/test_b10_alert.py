"""tests/xstate_contract/test_b10_alert.py — B10 `alert` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B10.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B10.7 invariant ledger to the catalogue. E40-T03 filled in the
binding bodies, so every invariant is proven here: structurally on the chart,
as golden traces on the library (through `statechart.factory.build` and
`statechart.gateway`), and as hypothesis properties over the guards.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from xstate_statemachine import SimulatedClock

from candleviewer.alerts.lifecycle import _Refusals
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b10_alert as b10
from candleviewer.statechart.gateway import Gateway
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import entry_of, exits, is_terminal, node_at, settle
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("alert")

INVARIANTS: dict[str, str] = {
    "INV-B10-a": "test_inv_b10_a_exhaustion_reaches_visible_delivery_failed",
    "INV-B10-b": "test_inv_b10_b_delivered_channels_subset_property",
    "INV-B10-c": "test_inv_b10_c_suppression_is_counted_and_metricised",
    "INV-B10-d": "test_inv_b10_d_fired_row_persisted_on_firing_entry",
}


def test_b10_invariant_ledger_matches_catalogue() -> None:
    check_ledger(10, INVARIANTS, globals())


def test_inv_b10_a_exhaustion_reaches_visible_delivery_failed() -> None:
    err = [(g, t) for e, g, t in exits(CHART, "firing") if e == "onError"]
    assert err[-1] == (None, "alert.delivery_failed")
    assert not is_terminal(CHART, "delivery_failed")  # visible, acknowledgeable


def test_inv_b10_c_suppression_is_counted_and_metricised() -> None:
    assert {"bump_storm_count", "emit_suppression_metric"} <= set(entry_of(CHART, "suppressed"))


def test_inv_b10_d_fired_row_persisted_on_firing_entry() -> None:
    """Entry actions run before the state's invoke starts."""
    assert entry_of(CHART, "firing")[0] == "persist_fired_row"
    assert node_at(CHART, "firing")["invoke"]["src"] == "dispatch_to_channels"


# --- E40-T03: invariants on the real bindings ------------------------------------------

_CH = st.lists(st.sampled_from(["in_app", "email", "webhook", "push", "desktop"]),
               unique=True, max_size=5)  # fmt: skip


@given(want=_CH, got=_CH)
def test_inv_b10_b_delivered_channels_subset_property(want: list[str], got: list[str]) -> None:
    """Full delivery (`delivered`) only when delivered == channels (non-empty); anything
    else takes the `partially_delivered` arm."""
    ok = b10.all_channels_ok({"channels": want}, {"delivered_channels": got})
    assert ok == (bool(want) and set(got) == set(want))


@given(attempts=st.integers(-3, 12), cap=st.integers(0, 10))
def test_inv_b10_a_attempts_never_exceed_cap_property(attempts: int, cap: int) -> None:
    ctx = {"delivery_attempts": attempts, "max_delivery_attempts": cap}
    assert b10.delivery_attempts_left(ctx, {}) == (attempts < cap)


@given(n=st.integers(0, 20), cap=st.integers(1, 6))
async def test_inv_b10_a_bump_is_capped_property(n: int, cap: int) -> None:
    ctx: dict[str, Any] = {"delivery_attempts": 0, "max_delivery_attempts": cap}
    for _ in range(n):
        await b10.bump_delivery_attempts(None, ctx, None, None)
    assert ctx["delivery_attempts"] == min(n, cap) <= cap


def test_b10_guards_are_total_on_malformed_input() -> None:
    bad: Any = {"channels": 5}
    assert b10.all_channels_ok(bad, {}) is False
    assert b10.delivery_attempts_left({}, {}) is False
    assert b10.in_storm_window({}, object()) is False
    assert b10.in_storm_window({}, {"storm": True}) is True


async def _chart() -> tuple[Any, Gateway]:
    interp = (await build("alert", clock=SimulatedClock(), lane="platform")).interpreter
    gw = Gateway()
    gw.register("k", interp, kind="alert", lane="platform", metrics=_Refusals())
    return interp, gw


def _leaf(interp: Any) -> str:
    return str(next(iter(interp.current_state_ids))).split(".", 1)[1]


async def _trace(events: list[dict[str, Any]]) -> list[str]:
    interp, gw = await _chart()
    out = [_leaf(interp)]
    for ev in events:
        await gw.send("k", ev, wait=True)
        await settle()
        out.append(_leaf(interp))
    await interp.stop()
    return out


_MET = {"type": "CONDITION_MET", "storm": False, "delivery_ids": [7], "channels": ["in_app"]}
#: Golden traces on the library with the real bindings: every §B10.3 arm.
GOLDEN: dict[str, tuple[list[dict[str, Any]], list[str]]] = {
    "fire_deliver_ack_resolve": (
        [_MET, {"type": "ACK"}, {"type": "RESOLVE"}],
        ["armed", "delivered", "acknowledged", "resolved"]),
    "fire_deliver_resolve": ([_MET, {"type": "RESOLVE"}], ["armed", "delivered", "resolved"]),
    "storm_suppress_expire": (
        [{"type": "CONDITION_MET", "storm": True}, {"type": "SUPPRESSION_EXPIRED"}],
        ["armed", "suppressed", "armed"]),
    "storm_then_disable_enable": (
        [{"type": "CONDITION_MET", "storm": True}, {"type": "DISABLE"}, {"type": "ENABLE"}],
        ["armed", "suppressed", "disabled", "armed"]),
    "disable": ([{"type": "DISABLE"}], ["armed", "disabled"]),
    "kill": ([{"type": "KILL"}], ["armed", "disabled"]),
    "partial": (
        [{**_MET, "channels": []}, {"type": "ACK"}],
        ["armed", "partially_delivered", "acknowledged"]),
}  # fmt: skip


async def test_b10_golden_traces_with_real_bindings() -> None:
    for name, (events, expected) in GOLDEN.items():
        assert await _trace(events) == expected, name


async def test_b10_persist_fired_row_pins_committed_ids_and_channels() -> None:
    interp, gw = await _chart()
    await gw.send("k", {**_MET, "alert_id": "a1"}, wait=True)
    await settle()
    assert interp.context["delivery_ids"] == [7] and interp.context["alert_id"] == "a1"
    assert interp.context["delivered_channels"] == []  # set at entry, before dispatch
    await interp.stop()


async def test_inv_b10_c_suppression_hook_fires_and_storm_counted() -> None:
    seen: list[str] = []

    async def hook(name: str, _ctx: dict[str, Any]) -> None:
        seen.append(name)

    b10.set_hook(hook)
    try:
        interp, gw = await _chart()
        await gw.send("k", {"type": "CONDITION_MET", "storm": True,
                             "storm_window_end_us": 9}, wait=True)  # fmt: skip
        assert interp.context["storm_count"] == 1 and interp.context["suppressed_until_us"] == 9
        await gw.send("k", {"type": "KILL"}, wait=True)
        assert seen == ["suppressed", "killed"]
        await interp.stop()
    finally:
        b10.set_hook(None)


async def test_b10_retry_exhaustion_bindings() -> None:
    ctx: dict[str, Any] = {"channels": ["in_app"]}
    await b10.stamp_storm_window(None, ctx, {"storm_window_end_us": 5}, None)
    await b10.schedule_backoff_deadline(None, ctx, None, None)
    await b10.emit_delivery_failure_metric(None, ctx, None, None)
    assert ctx["suppressed_until_us"] == 5
    assert await b10.dispatch_to_channels(None, ctx, None) == {"delivered_channels": ["in_app"]}


# --- B10.3 arms reached only through a failing / partial delivery ----------------------


async def _failing(_i: Any, _c: dict[str, Any], _e: Any) -> dict[str, Any]:
    raise RuntimeError("channel down")


async def _trace_failing(events: list[dict[str, Any]], monkeypatch: Any) -> list[str]:
    monkeypatch.setitem(b10.SERVICES, "dispatch_to_channels", _failing)
    return await _trace(events)


async def test_b10_retrying_retry_due_refires(monkeypatch: Any) -> None:
    got = await _trace_failing([_MET, {"type": "RETRY_DUE"}], monkeypatch)
    assert got[:3] == ["armed", "retrying", "retrying"]  # RETRY_DUE -> firing -> fails -> retrying


async def test_b10_retrying_ack_acknowledges(monkeypatch: Any) -> None:
    got = await _trace_failing([_MET, {"type": "ACK"}], monkeypatch)
    assert got == ["armed", "retrying", "acknowledged"]


async def test_b10_retrying_bumps_attempts_on_entry(monkeypatch: Any) -> None:
    monkeypatch.setitem(b10.SERVICES, "dispatch_to_channels", _failing)
    interp, gw = await _chart()
    await gw.send("k", _MET, wait=True)
    await settle()
    assert _leaf(interp) == "retrying" and interp.context["delivery_attempts"] == 1
    await interp.stop()


async def test_b10_partially_delivered_resolve() -> None:
    got = await _trace([{**_MET, "channels": []}, {"type": "RESOLVE"}])
    assert got == ["armed", "partially_delivered", "resolved"]


async def test_b10_delivery_failed_ack_after_exhaustion(monkeypatch: Any) -> None:
    monkeypatch.setitem(b10.SERVICES, "dispatch_to_channels", _failing)
    interp, gw = await _chart()
    interp.context["max_delivery_attempts"] = 1
    await gw.send("k", _MET, wait=True)
    await settle()
    assert _leaf(interp) == "retrying"
    await gw.send("k", {"type": "RETRY_DUE"}, wait=True)
    await settle()
    assert _leaf(interp) == "delivery_failed"
    await gw.send("k", {"type": "ACK"}, wait=True)
    await settle()
    assert _leaf(interp) == "acknowledged"
    await interp.stop()


#: (state, event) pairs the traces in this file and the arms above drive.
_EXERCISED: set[tuple[str, str]] = {
    ("armed", "CONDITION_MET"), ("armed", "DISABLE"), ("suppressed", "SUPPRESSION_EXPIRED"),
    ("suppressed", "DISABLE"), ("retrying", "RETRY_DUE"), ("retrying", "ACK"),
    ("delivered", "ACK"), ("delivered", "RESOLVE"), ("partially_delivered", "ACK"),
    ("partially_delivered", "RESOLVE"), ("delivery_failed", "ACK"),
    ("acknowledged", "RESOLVE"), ("disabled", "ENABLE"),
}  # fmt: skip


def test_b10_every_state_event_arm_is_exercised() -> None:
    declared = {(s, e) for s, node in CHART["states"].items() for e in (node.get("on") or {})}
    assert declared <= _EXERCISED, sorted(declared - _EXERCISED)
