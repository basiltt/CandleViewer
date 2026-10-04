"""E35-S02: deterministic evaluator (24-internal-schemas.md 11.5). Scenario names in docstrings."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.rules.evaluator import (
    Evaluator,
    MetricSnapshot,
    MetricValue,
    SnapshotBuilder,
    metric_key,
)
from candleviewer.rules.evaluator.engine import PAUSED_MESSAGE, scope_instance
from candleviewer.rules.ir.models import MetricRef, Rule

RID = str(uuid.UUID(int=7))


def m(name: str, **kw: Any) -> dict[str, Any]:
    return {"metric": name, **kw}


def c(v: Any) -> dict[str, Any]:
    return {"const": v}


def cmp(nid: str, op: str, left: Any, right: Any = None, **kw: Any) -> dict[str, Any]:
    d = {"node_id": nid, "op": op, "left": left, **kw}
    if right is not None:
        d["right"] = right
    return d


def rule(cond: dict[str, Any], **limits: Any) -> Rule:
    return Rule.model_validate(
        {
            "rule_id": RID, "version": 1, "name": "r", "enabled": True, "mode": "simulate",
            "scope": {"level": "symbol", "symbols": ["BTCUSDT"]},
            "trigger": {"type": "on_price_update"}, "conditions": cond,
            "actions": [{"node_id": "a1", "type": "send_notification", "params": {}}],
            "limits": {"cooldown_ms": 0, **limits},
        }
    )  # fmt: skip


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000

    def __call__(self) -> int:
        return self.t


class Source:
    """Fake memoised metric source; ``reads`` counts real computations."""

    def __init__(self, clock: Clock, **values: Any) -> None:
        self.clock = clock
        self.values: dict[str, Any] = dict(values)
        self.reasons: dict[str, str] = {}
        self.ages: dict[str, int] = {}
        self.reads = 0

    def read(self, ref: MetricRef) -> MetricValue:
        self.reads += 1
        v = self.values.get(ref.metric)
        val = Decimal(str(v)) if isinstance(v, int | float) and not isinstance(v, bool) else v
        return MetricValue(
            val, self.clock() - self.ages.get(ref.metric, 0), 0, self.reasons.get(ref.metric)
        )


def make(cond: dict[str, Any], src_vals: dict[str, Any] | None = None, **limits: Any) -> tuple[
    Evaluator, Source, Clock, list[tuple[str, str]]
]:  # fmt: skip
    clk = Clock()
    src = Source(clk, **(src_vals or {}))
    alerts: list[tuple[str, str]] = []
    ev = Evaluator(rule(cond, **limits), SnapshotBuilder(src), clk, clk,
                   lambda r, msg: alerts.append((r, msg)))  # fmt: skip
    return ev, src, clk, alerts


INST = scope_instance("BTCUSDT", "acct-3f2a")


def run(ev: Evaluator) -> Any:
    ev._snapshots.new_tick()
    return ev.on_trigger(INST, "on_price_update")


def test_one_snapshot_per_evaluation() -> None:
    """Scenario: One snapshot per evaluation."""
    cond = {
        "node_id": "b",
        "op": "all_of",
        "children": [
            cmp("c1", "gt", m("last_price"), c(10)),
            cmp("c2", "lt", m("last_price"), c(1000)),
        ],
    }
    ev, src, _, _ = make(cond, {"last_price": 100})

    orig = src.read

    def drifting(ref: MetricRef) -> MetricValue:
        out = orig(ref)
        src.values["last_price"] = 5000  # price moves after the first read
        return out

    src.read = drifting  # type: ignore[method-assign]  # inject wall-clock drift
    res = run(ev)
    assert res.fired
    assert src.reads == 1
    vals = [t.left_value for t in res.condition_trace if t.node_id in ("c1", "c2")]
    assert vals == [Decimal(100), Decimal(100)]


def test_snapshot_is_immutable_and_memoised_across_rules() -> None:
    clk = Clock()
    src = Source(clk, atr=3)
    b = SnapshotBuilder(src)
    ref = MetricRef(metric="atr", params={"n": 14})
    s1 = b.build([ref, ref], clk())
    s2 = b.build([ref], clk())
    assert src.reads == 1 and b.cache_hits == 1 and b.computations == 1
    assert s1.get(ref) == s2.get(ref)
    with pytest.raises(TypeError):
        s1.values[metric_key(ref)] = MetricValue(None, 0)  # type: ignore[index]


@pytest.mark.parametrize("reason", ["warmup", "no_position"])
def test_none_is_false_never_zero(reason: str) -> None:
    """Scenario: None is false, never zero."""
    ev, src, _, _ = make(cmp("c", "lt", m("rsi"), c(1)), {"rsi": None})
    src.reasons["rsi"] = reason
    res = run(ev)
    assert res.fired is False and res.skipped_reason == reason and res.error is None


def test_none_propagates_through_arithmetic() -> None:
    arith = {"node_id": "x", "op": "add", "operands": [m("rsi"), c(5)]}
    ev, _, _, _ = make(cmp("c", "lt", arith, c(100)), {"rsi": None})
    assert run(ev).fired is False


def test_short_circuit_still_produces_complete_trace() -> None:
    """Scenario: Short-circuit still produces a complete trace."""
    cond = {
        "node_id": "b",
        "op": "all_of",
        "children": [
            cmp("c1", "gt", m("pv"), c(10)),
            cmp("c2", "gt", m("pv"), c(0)),
            {"node_id": "b2", "op": "any_of", "children": [cmp("c3", "gt", m("pv"), c(0))]},
        ],
    }
    res = run(make(cond, {"pv": 1})[0])
    by = {t.node_id: t.result for t in res.condition_trace}
    assert by == {"b": False, "c1": False, "c2": None, "b2": None, "c3": None}


def test_frozen_feed_never_triggers_action() -> None:
    """Scenario: A frozen feed never triggers action (failure case)."""
    ev, src, _, _ = make(cmp("c", "gt", m("pv"), c(0)), {"pv": 1})
    src.ages["pv"] = 5_001
    res = run(ev)
    assert res.fired is False and res.skipped_reason == "stale_data"
    assert res.condition_trace == () and ev.stats.skipped["stale_data"] == 1


def test_stale_threshold_uses_three_times_cadence() -> None:
    snap = MetricSnapshot(100_000, {"k": MetricValue(Decimal(1), 100_000 - 20_000, 10_000)})
    assert snap.stale_keys() == ()
    snap = MetricSnapshot(100_000, {"k": MetricValue(Decimal(1), 100_000 - 30_001, 10_000)})
    assert snap.stale_keys() == ("k",)


@pytest.mark.parametrize("op", ["crosses_above", "crosses_below"])
def test_no_phantom_crosses_after_restart(op: str) -> None:
    """Scenario: No phantom crosses after a restart (edge case)."""
    ev, src, _, _ = make(cmp("c", op, m("pv"), c(50)), {"pv": 100 if op == "crosses_above" else 1})
    assert run(ev).fired is False  # no previous snapshot
    src.values["pv"] = 1 if op == "crosses_above" else 100
    assert run(ev).fired is False
    src.values["pv"] = 100 if op == "crosses_above" else 1
    assert run(ev).fired is True


def test_slow_evaluation_is_aborted_and_counted() -> None:
    """Scenario: A slow evaluation is aborted and counted (failure case)."""
    ev, src, clk, alerts = make(
        cmp("c", "gt", m("pv"), c(0)),
        {"pv": 1},
        evaluation_timeout_ms=10,
        kill_switch_on_error_count=3,
    )
    orig = src.read

    def slow(ref: MetricRef) -> MetricValue:
        clk.t += 50
        return orig(ref)

    src.read = slow  # type: ignore[method-assign]  # simulate slow metric computation
    for i in range(3):
        res = run(ev)
        assert res.error == "evaluation_timeout" and res.fired is False
        assert (ev.disabled_reason is not None) == (i == 2)
    assert alerts == [(RID, "auto_disabled:evaluation_timeout")]
    assert run(ev).skipped_reason == "disabled"
    ev.rearm()
    src.read = orig  # type: ignore[method-assign]
    assert run(ev).fired is True


def test_error_counter_is_consecutive_not_cumulative() -> None:
    ev, src, _, alerts = make(
        cmp("c", "gt", m("pv"), c(0)), {"pv": 1}, kill_switch_on_error_count=2
    )
    orig = src.read

    def boom(ref: MetricRef) -> MetricValue:
        raise RuntimeError

    for _ in range(3):
        src.read = boom  # type: ignore[method-assign]
        assert run(ev).error == "RuntimeError"
        src.read = orig  # type: ignore[method-assign]
        assert run(ev).fired is True
    assert alerts == [] and ev.stats.errors == 3


def test_reconnect_does_not_replay_history() -> None:
    """Scenario: Reconnect does not replay history (edge case)."""
    ev, _, clk, _ = make(cmp("c", "gt", m("pv"), c(0)), {"pv": 1}, once=True)
    assert ev.pause() == PAUSED_MESSAGE
    for _ in range(30):
        clk.t += 1000
        assert run(ev).skipped_reason == "paused"
    assert ev.stats.missed_triggers == 30
    res = ev.resume(INST, "on_price_update")
    assert res.fired is True and ev.paused is False
    assert ev.stats.evaluations == 31
    assert run(ev).skipped_reason == "once"  # dedupe prevents a duplicate fire


def test_deterministic_ordering() -> None:
    """Scenario: Deterministic ordering."""
    cond = {
        "node_id": "b",
        "op": "any_of",
        "children": [cmp(f"c{i}", "gt", m("pv"), c(i)) for i in (5, 3, 1)],
    }
    a, b = make(cond, {"pv": 2})[0], make(cond, {"pv": 2})[0]
    ra, rb = run(a), run(b)
    assert [t.node_id for t in ra.condition_trace] == ["b", "c5", "c3", "c1"]
    assert ra == rb


def test_per_scope_instances_are_independent() -> None:
    ev, _, _, _ = make(cmp("c", "gt", m("pv"), c(0)), {"pv": 1}, once=True)
    assert ev.on_trigger("BTCUSDT@a", "t").fired
    assert ev.on_trigger("ETHUSDT@a", "t").fired
    assert ev.on_trigger("BTCUSDT@a", "t").skipped_reason == "once"
    assert scope_instance(None, None) == "*@*"


def test_cooldown_rate_limits_and_debounce() -> None:
    ev, _, clk, _ = make(
        cmp("c", "gt", m("pv"), c(0)),
        {"pv": 1},
        cooldown_ms=100,
        max_fires_per_hour=2,
        max_fires_per_day=3,
    )
    assert run(ev).fired
    assert run(ev).skipped_reason == "cooldown"
    clk.t += 200
    assert run(ev).fired
    clk.t += 200
    assert run(ev).skipped_reason == "rate_limit"
    clk.t += 3_600_000
    assert run(ev).fired
    clk.t += 3_600_000
    assert run(ev).skipped_reason == "rate_limit"  # daily cap
    clk.t += 86_400_000
    assert run(ev).fired
    r = rule(cmp("c", "gt", m("pv"), c(0)))
    r2 = r.model_copy(update={"trigger": r.trigger.model_copy(update={"debounce_ms": 500})})
    ev.set_active_version(r2)
    clk.t += 600
    assert run(ev).skipped_reason is None
    assert run(ev).skipped_reason == "debounce"


def test_new_version_drops_temporal_state() -> None:
    cond = {
        "node_id": "t",
        "op": "sustained_for",
        "window_ms": 1000,
        "child": cmp("c", "gt", m("pv"), c(0)),
    }
    ev, _, clk, _ = make(cond, {"pv": 1})
    run(ev)
    clk.t += 1000
    assert run(ev).fired
    ev.set_active_version(ev.rule.model_copy(update={"version": 2}))
    assert run(ev).fired is False
