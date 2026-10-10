"""tests/xstate_contract/test_b11_recording.py — B11 `recording` contract module (E50-T31).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B11.3 arm, both service spellings, the persist→restore round-trip at
every quiescence point, envelope refusal, guard-denied / unhandled audit and
latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`). This module
pins the §B11.7 invariant ledger to the catalogue and, since E16-T02 filled the
binding bodies, drives the REAL bindings through `cv.statechart.factory.build`:
the R14-03 G2 golden trace plus a hypothesis property per invariant.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from xstate_statemachine import SimulatedClock

import candleviewer.statechart.bindings.b11_recording as b11
from candleviewer.statechart import build
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import entry_of, exits
from tests.xstate_contract.membership import check_ledger

CHART = Registry().get("recording")

INVARIANTS: dict[str, str] = {
    "INV-B11-a": "test_inv_b11_a_never_stops_with_reason_or_position",
    "INV-B11-b": "test_inv_b11_b_reason_added_cancels_linger",
    "INV-B11-c": "test_inv_b11_c_every_gap_counted_and_metricised",
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


_REASONS = st.sampled_from(["manual", "position_open", "chart_open"])


class _Hooks:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, name: str, _ctx: dict[str, Any]) -> None:
        self.calls.append(name)


async def _drive(events: list[dict[str, Any]]) -> tuple[Any, _Hooks]:
    hooks = _Hooks()
    b11.set_hook(hooks)
    interp = (await build("recording", clock=SimulatedClock(), lane="platform")).interpreter
    for ev in events:
        if interp.can(ev):
            await interp.send(ev, wait=True)
        for _ in range(64):
            await asyncio.sleep(0)
    return interp, hooks


def _leaf(interp: Any) -> str:
    return str(next(iter(interp.current_state_ids))).split(".")[1]


async def test_b11_g2_golden_trace_with_real_bindings() -> None:
    """R14-03 G2: start, degrade, gap while degraded, recover, linger, stop."""
    interp, hooks = await _drive(
        [
            {"type": "REASON_ADDED", "reason": "chart_open", "symbol": "BTCUSDT"},
            {"type": "STREAM_UNHEALTHY", "stream": "trades"},
            {"type": "GAP_DETECTED", "stream": "trades"},
            {"type": "STREAM_HEALTHY", "stream": "trades"},
            {"type": "REASON_REMOVED", "reason": "chart_open"},
            {"type": "LINGER_DUE", "position_open": False},
        ]
    )
    try:
        assert _leaf(interp) == "stopped"
        assert interp.context["gap_count_24h"] == 1 and interp.chain_trips == 0
        assert hooks.calls.count("subscribe") == 1 and hooks.calls.count("unsubscribe") == 1
    finally:
        await interp.stop()
        b11.set_hook(None)


@settings(max_examples=40, deadline=None)
@given(ops=st.lists(st.tuples(st.sampled_from(["add", "rm", "due"]), _REASONS, st.booleans())))
async def test_inv_b11_a_never_stops_with_reason_or_position(
    ops: list[tuple[str, str, bool]],
) -> None:
    events: list[dict[str, Any]] = []
    for op, reason, pos in ops:
        if op == "add":
            events.append({"type": "REASON_ADDED", "reason": reason, "symbol": "BTCUSDT"})
        elif op == "rm":
            events.append({"type": "REASON_REMOVED", "reason": reason})
        else:
            events.append({"type": "LINGER_DUE", "position_open": pos})
    hooks = _Hooks()
    b11.set_hook(hooks)
    interp = (await build("recording", clock=SimulatedClock(), lane="platform")).interpreter
    try:
        for ev in events:
            before = list(interp.context.get("reasons") or ())
            if not interp.can(ev):
                continue
            await interp.send(ev, wait=True)
            for _ in range(64):
                await asyncio.sleep(0)
            if _leaf(interp) in ("stopping", "stopped") and ev["type"] == "LINGER_DUE":
                assert not before and ev["position_open"] is False
    finally:
        await interp.stop()
        b11.set_hook(None)


@settings(max_examples=25, deadline=None)
@given(n=st.integers(min_value=0, max_value=12), degraded_at=st.integers(min_value=0, max_value=12))
async def test_inv_b11_c_every_gap_counted_and_metricised(n: int, degraded_at: int) -> None:
    events: list[dict[str, Any]] = [{"type": "REASON_ADDED", "reason": "manual", "symbol": "X"}]
    for i in range(n):
        if i == degraded_at:
            events.append({"type": "STREAM_UNHEALTHY", "stream": "trades"})
        events.append({"type": "GAP_DETECTED", "stream": "trades"})
    interp, hooks = await _drive(events)
    try:
        assert interp.context["gap_count_24h"] == n
        assert hooks.calls.count("gap") == n
    finally:
        await interp.stop()
        b11.set_hook(None)


@given(
    reasons=st.lists(_REASONS, unique=True),
    gone=_REASONS,
    health=st.dictionaries(st.sampled_from(["trades", "book", "tickers"]), st.booleans()),
    stream=st.sampled_from(["trades", "book", "tickers"]),
)
def test_b11_guards_are_event_aware_and_total(
    reasons: list[str], gone: str, health: dict[str, bool], stream: str
) -> None:
    assert b11.reasons_remain({"reasons": reasons}, {"reason": gone}) is any(
        r != gone for r in reasons
    )
    merged = {**health, stream: True}
    assert b11.all_streams_healthy({"streams_healthy": health}, {"stream": stream}) is all(
        merged.values()
    )
    assert b11.reasons_remain({"reasons": 5}, {}) is False  # A6: total, never raises
    assert b11.all_streams_healthy({"streams_healthy": 5}, {}) is False
