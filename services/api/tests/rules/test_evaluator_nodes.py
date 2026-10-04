"""E35-S02: operator table, boolean, arithmetic and temporal node semantics."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from tests.rules.test_evaluator import c, cmp, m, make, run

D = Decimal


@pytest.mark.parametrize(
    ("op", "left", "right", "extra", "expected"),
    [
        ("gt", 2, 1, {}, True), ("gt", 1, 1, {}, False),
        ("gte", 1, 1, {}, True), ("lt", 1, 2, {}, True), ("lte", 2, 2, {}, True),
        ("lte", 3, 2, {}, False),
        ("eq", 1, 1, {}, True), ("eq", "1.04", 1, {"tolerance": "0.05"}, True),
        ("eq", "1.06", 1, {"tolerance": "0.05"}, False), ("neq", 1, 2, {}, True),
        ("eq", "trend", "trend", {}, True), ("neq", True, False, {}, True),
        ("between", 5, 1, {"right2": c(10)}, True), ("between", 10, 10, {"right2": c(1)}, True),
        ("between", 11, 1, {"right2": c(10)}, False), ("outside", 11, 1, {"right2": c(10)}, True),
        ("outside", 5, 1, {"right2": c(10)}, False), ("between", 5, 1, {}, False),
        ("is_true", True, None, {}, True), ("is_true", False, None, {}, False),
        ("is_false", False, None, {}, True),
        ("in_set", "up", None, {"set_values": ["up", "flat"]}, True),
        ("not_in_set", "up", None, {"set_values": ["down"]}, True),
        ("in_set", 1, None, {"set_values": ["1"]}, False),
        ("gt", "up", 1, {}, False), ("gt", 1, None, {}, False),
    ],
)  # fmt: skip
def test_comparison_operator_table(
    op: str, left: Any, right: Any, extra: dict[str, Any], expected: bool
) -> None:
    lv = D(left) if isinstance(left, str) and left[0].isdigit() else left
    rv = None if right is None else c(right)
    ev, _, _, _ = make(cmp("c", op, m("xv"), rv, **extra), {"xv": lv})
    assert run(ev).fired is expected


def test_changed_operator() -> None:
    ev, src, _, _ = make(cmp("c", "changed", m("xv")), {"xv": "up"})
    assert run(ev).fired is False
    assert run(ev).fired is False
    src.values["xv"] = "down"
    assert run(ev).fired is True
    src.values["xv"] = None
    assert run(ev).fired is False


def test_cross_with_unavailable_operand_is_false() -> None:
    ev, src, _, _ = make(cmp("c", "crosses_above", m("xv"), m("yv")), {"xv": 1, "yv": 5})
    run(ev)
    src.values["yv"] = None
    assert run(ev).fired is False


@pytest.mark.parametrize(
    ("op", "vals", "expected"),
    [("all_of", [1, 1], True), ("any_of", [0, 0], False), ("none_of", [0, 0], True),
     ("none_of", [0, 1], False), ("n_of:1", [0, 1, 0], True), ("n_of:3", [1, 1, 1], True),
     ("n_of:2", [1, 0, 0], False), ("n_of:2", [0, 0, 1], False)],
)  # fmt: skip
def test_boolean_nodes(op: str, vals: list[int], expected: bool) -> None:
    name, _, n = op.partition(":")
    node: dict[str, Any] = {
        "node_id": "b",
        "op": name,
        "children": [cmp(f"c{i}", "is_true", c(bool(v))) for i, v in enumerate(vals)],
    }
    if n:
        node["n"] = int(n)
    assert run(make(node)[0]).fired is expected


@pytest.mark.parametrize(
    ("op", "operands", "expected"),
    [("add", [1, 2, 3], 6), ("sub", [10, 3, 2], 5), ("mul", [2, 3], 6), ("div", [9, 3], 3),
     ("div", [1, 0], None), ("abs", [-4], 4), ("neg", [4], -4), ("min", [3, 1], 1),
     ("max", [3, 1], 3), ("pct_of", [5, 20], 25), ("pct_of", [5, 0], None),
     ("pct_of", [5], None), ("add", [True, 1], None)],
)  # fmt: skip
def test_arithmetic(op: str, operands: list[Any], expected: Any) -> None:
    arith = {"node_id": "a", "op": op, "operands": [c(v) for v in operands]}
    res = run(make(cmp("c", "eq", arith, c(0)))[0])
    left = res.condition_trace[0].left_value
    assert left == (None if expected is None else D(expected))


def test_arithmetic_invalid_operation_is_none() -> None:
    arith = {"node_id": "a", "op": "div", "operands": [m("xv"), m("yv")]}
    ev, _, _, _ = make(cmp("c", "eq", arith, c(0)), {"xv": D("Infinity"), "yv": D("Infinity")})
    assert run(ev).condition_trace[0].left_value is None


def _temporal(op: str, window: int, **kw: Any) -> dict[str, Any]:
    return {"node_id": "t", "op": op, "window_ms": window, "child": cmp("c", "is_true", m("xv")),
            **kw}  # fmt: skip


def test_sustained_for() -> None:
    ev, src, clk, _ = make(_temporal("sustained_for", 1000), {"xv": True})
    assert run(ev).fired is False
    clk.t += 999
    assert run(ev).fired is False
    clk.t += 1
    assert run(ev).fired is True
    src.values["xv"] = False
    assert run(ev).fired is False


def test_occurred_within_and_count_within() -> None:
    ev, src, clk, _ = make(_temporal("occurred_within", 1000), {"xv": True})
    assert run(ev).fired
    src.values["xv"] = False
    clk.t += 1000
    assert run(ev).fired
    clk.t += 1
    assert run(ev).fired is False
    ev2, _, clk2, _ = make(_temporal("count_within", 1000, min_count=2), {"xv": True})
    assert run(ev2).fired is False
    clk2.t += 500
    assert run(ev2).fired is True


def test_stable_for() -> None:
    ev, src, clk, _ = make(_temporal("stable_for", 1000), {"xv": True})
    assert run(ev).fired is False
    clk.t += 1000
    assert run(ev).fired is True
    src.values["xv"] = False
    assert run(ev).fired is False
