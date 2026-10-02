"""THROWAWAY: ~20-document hand-built IR corpus (promoted to tests/fixtures/rule_ir by E35-T01)."""
from __future__ import annotations

import json
from typing import Any

ACTIONS = [
    "open_position", "close_position", "reduce_position", "cancel_orders", "move_stop_loss",
    "set_take_profit", "place_limit", "place_market", "pause_rule", "notify", "webhook",
    "arm_algo", "disarm_algo", "flatten_all", "set_leverage", "kill_switch_request", "tag_trade",
    "log_event", "snooze_alert", "raise_alert", "cancel_algo", "adjust_size", "trail_stop",
    "scale_in", "scale_out",
]  # 25 placeholder action types (vocabulary itself is owned by 24-internal-schemas.md 11.6)


def cmp_(i: int, left: str, op: str, right: str) -> dict[str, Any]:
    return {"node_id": f"c{i}", "type": "compare", "op": op,
            "left": {"metric": left, "params": {"window": "5m"}}, "right": {"const": right}}


def make_doc(name: str, cond: dict[str, Any], actions: list[dict[str, Any]], layout: int = 0) -> str:
    return json.dumps({
        "schema_version": 1, "name": name,
        "trigger": {"type": "bar_close", "timeframe": "1m", "symbol": "BTCUSDT"},
        "condition": cond, "actions": actions, "limits": {"max_fires": 3, "cooldown_s": 60},
        "presentation": {"graph_layout": {"c1": {"x": layout, "y": layout}}, "editor": "form"},
    }, ensure_ascii=False)


def corpus() -> list[tuple[str, str]]:
    d: list[tuple[str, str]] = []
    notify = [{"node_id": "a1", "type": "notify", "channel": "ui"}]
    simple = [("price", ">", "65000.50"), ("rsi", "<", "30"), ("cvd", ">=", "1000"),
              ("funding", "<", "-0.0001"), ("volume", ">", "1500.00")]
    for i, (m, op, v) in enumerate(simple):
        d.append((f"form_simple_{i}", make_doc(f"form{i}", cmp_(1, m, op, v), notify, layout=i)))
    d.append(("form_all_of_any_of", make_doc("f2", {"node_id": "g1", "type": "all_of", "children": [
        {"node_id": "g2", "type": "any_of",
         "children": [cmp_(1, "price", ">", "1.50"), cmp_(2, "rsi", "<", "20")]},
        cmp_(3, "cvd", ">", "0")]}, notify)))
    d.append(("temporal_sustained", make_doc("t", {
        "node_id": "s1", "type": "sustained_for", "seconds": 30,
        "child": cmp_(1, "price", ">", "100")}, notify)))
    d.append(("nested_arith", make_doc("ar", {
        "node_id": "x1", "type": "compare", "op": ">",
        "left": {"node_id": "x2", "type": "arith", "op": "sub", "operands": [
            {"metric": "high"},
            {"node_id": "x3", "type": "arith", "op": "mul",
             "operands": [{"metric": "atr"}, {"const": "2.0"}]}]},
        "right": {"const": "0.10"}}, notify)))
    d.append(("shared_subexpr", make_doc("sh", {
        "node_id": "g1", "type": "all_of", "children": [
            cmp_(1, "price", ">", "10"),
            {"node_id": "g2", "type": "any_of",
             "children": [{"ref": "c1"}, cmp_(2, "rsi", "<", "5")]}]}, notify)))
    d.append(("n_of", make_doc("n", {"node_id": "g1", "type": "n_of", "n": 2, "children": [
        cmp_(i, "price", ">", str(i)) for i in range(1, 6)]}, notify)))
    d.append(("max_children_32", make_doc("mx", {
        "node_id": "g1", "type": "all_of",
        "children": [cmp_(i, "price", ">", f"{i}.0") for i in range(1, 33)]}, notify)))
    d.append(("max_operands_8", make_doc("mo", {
        "node_id": "x1", "type": "compare", "op": ">",
        "left": {"node_id": "x2", "type": "arith", "op": "add",
                 "operands": [{"const": f"{i}.50"} for i in range(8)]},
        "right": {"const": "1"}}, notify)))
    d.append(("all_25_actions", make_doc("act", cmp_(1, "price", ">", "1"),
              [{"node_id": f"a{i}", "type": t, "qty": "0.010"} for i, t in enumerate(ACTIONS)])))
    d.append(("unicode_name", make_doc("règle-ネ", cmp_(1, "price", ">", "1"), notify)))
    d.append(("large_decimal", make_doc("ld", cmp_(1, "price", ">", "123456789012345678.123456789"),
                                        notify)))
    d.append(("negative_zero", make_doc("nz", cmp_(1, "price", ">", "-0.0"), notify)))
    d.append(("small_decimal", make_doc("sd", cmp_(1, "funding", "<", "0.00000001"), notify)))
    for k in range(5):
        d.append((f"mixed_{k}", make_doc(f"mix{k}", {
            "node_id": "g1", "type": "any_of",
            "children": [cmp_(1, "price", ">", f"{k}.{k}0"), cmp_(2, "rsi", "<", str(10 * k))]},
            notify, layout=k * 7)))
    return d
