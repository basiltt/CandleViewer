"""E35-T04: semantic validator scenarios and the compile/validate endpoints."""

# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.rules import make_rules_router
from candleviewer.rules.compiler import to_form_model, to_graph_model
from candleviewer.rules.ir import Rule, ir_hash
from candleviewer.rules.validator import estimate_evaluations_per_minute, validate_rule
from candleviewer.rules.vocabulary import default_registry

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
RULE_ID = "00000000-0000-4000-8000-000000000001"
REG = default_registry()
PRICE = {"metric": "price"}


def _rule(name: str = "form_simple_0.json", **over: Any) -> Rule:
    raw = json.loads((FIX / name).read_text(encoding="utf-8"), parse_float=str)
    return Rule.model_validate({**raw, **over})


def _codes(issues: list[Any]) -> list[str]:
    return [i.code for i in issues]


def _notify() -> dict[str, Any]:
    return {
        "node_id": "a1",
        "type": "send_notification",
        "params": {"channel": "ui", "severity": "info", "template": "x"},
    }


def _cmp(left: dict[str, Any], right: dict[str, Any], op: str = "gt") -> dict[str, Any]:
    return {"node_id": "c1", "op": op, "left": left, "right": right}


def _doc(cond: dict[str, Any], actions: list[dict[str, Any]] | None = None, **over: Any) -> Rule:
    return _rule(conditions=cond, actions=actions or [_notify()], **over)


def _jsonable(model: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(model, default=str))  # type: ignore[no-any-return]


def test_unit_incoherent_comparison_is_a_type_mismatch() -> None:
    """Scenario: Unit-incoherent comparison is a compile error"""
    res = validate_rule(_doc(_cmp({"metric": "atr", "params": {"n": 14}}, {"const": "5%"})), REG)
    assert not res.valid
    (e,) = [i for i in res.errors if i.code == "type_mismatch"]
    assert e.path == "conditions"
    assert "price" in e.message
    assert "pct" in e.message


def test_valid_rule_and_references() -> None:
    res = validate_rule(_doc(_cmp(PRICE, {"const": 5})), REG)
    assert res.valid
    assert res.referenced_variables == ["price"]
    assert res.referenced_actions == ["send_notification"]


def test_unknown_metric_and_operator_applicability() -> None:
    res = validate_rule(_doc(_cmp({"metric": "no_such_metric"}, {"const": 1})), REG)
    assert _codes(res.errors) == ["unknown_metric"]
    res = validate_rule(_doc(_cmp(PRICE, {"const": 1}, "is_true")), REG)
    assert "operator_not_applicable" in _codes(res.errors)
    res = validate_rule(_doc(_cmp(PRICE, {"metric": "rsi"})), REG)
    assert "type_mismatch" in _codes(res.errors)


def test_arithmetic_unit_mixing_and_set_membership() -> None:
    ar = {"node_id": "m1", "op": "add", "operands": [PRICE, {"metric": "rsi"}]}
    assert "type_mismatch" in _codes(validate_rule(_doc(_cmp(ar, {"const": 1})), REG).errors)
    no_set = {"node_id": "c1", "op": "in_set", "left": {"metric": "market_regime"}}
    assert "missing_action_param" in _codes(validate_rule(_doc(no_set), REG).errors)


def test_unreachable_branches() -> None:
    consts = validate_rule(_doc(_cmp({"const": 1}, {"const": 2})), REG)
    assert "unreachable_branch" in _codes(consts.warnings)
    btw = {
        "node_id": "c1",
        "op": "between",
        "left": PRICE,
        "right": {"const": 9},
        "right2": {"const": 1},
    }
    assert "unreachable_branch" in _codes(validate_rule(_doc(btw), REG).errors)
    nof = {"node_id": "g", "op": "n_of", "n": 3, "children": [_cmp(PRICE, {"const": 1})]}
    assert "unreachable_branch" in _codes(validate_rule(_doc(nof), REG).errors)


def test_missing_action_param() -> None:
    bad = {"node_id": "a1", "type": "send_notification", "params": {"channel": "ui"}}
    res = validate_rule(_doc(_cmp(PRICE, {"const": 1}), [bad]), REG)
    assert {i.path for i in res.errors} == {
        "actions[0].params.severity",
        "actions[0].params.template",
    }


def test_feedback_loop_guard() -> None:
    """Scenario: A self-retriggering rule is refused at save time"""
    place = {
        "node_id": "a1",
        "type": "place_order",
        "params": {"side": "buy", "order_type": "market", "qty_mode": "fixed"},
    }
    rule = _doc(_cmp(PRICE, {"const": 1}), [place], trigger={"type": "on_order_fill"})
    res = validate_rule(rule, REG, {"orders:write"})
    (e,) = [i for i in res.errors if i.code == "feedback_loop"]
    assert e.klass == "safety"
    assert "loop" in e.message
    me = {"node_id": "a1", "type": "enable_rule", "params": {"rule_id": RULE_ID}}
    assert "feedback_loop" in _codes(
        validate_rule(_doc(_cmp(PRICE, {"const": 1}), [me]), REG).errors
    )
    sig = {"node_id": "a1", "type": "emit_signal", "params": {"signal_name": "s"}}
    rule = _doc(_cmp(PRICE, {"const": 1}), [sig], trigger={"type": "on_signal"})
    assert "feedback_loop" in _codes(validate_rule(rule, REG).errors)


def test_warnings_do_not_block_saving_but_safety_blocks_arming() -> None:
    """Scenario: Warnings inform but do not block saving"""
    res = validate_rule(_doc(_cmp(PRICE, {"const": 1})), REG)
    (w,) = [i for i in res.warnings if i.code == "guard_missing"]
    assert res.valid
    assert w.path == "guards.cooldown_seconds"
    assert w.klass == "safety"
    assert res.blocks_arming
    ok = _doc(_cmp(PRICE, {"const": 1}), limits={"cooldown_ms": 5000})
    assert not validate_rule(ok, REG).blocks_arming


def test_require_native_stop_invariant() -> None:
    """Dedicated safety test: removing the native SL is never allowed."""
    for extra in ({"remove": True}, {"cancel": True}):
        a = {
            "node_id": "a1",
            "type": "modify_stop_loss",
            "params": {"mode": "absolute", "value": 1, **extra},
        }
        res = validate_rule(_doc(_cmp(PRICE, {"const": 1}), [a]), REG, {"*"})
        assert "native_stop_violation" in _codes(res.errors)
    params = {"side": "buy", "order_type": "market", "qty_mode": "x", "require_native_stop": False}
    po = {"node_id": "a1", "type": "place_order", "params": params}
    res = validate_rule(_doc(_cmp(PRICE, {"const": 1}), [po]), REG, {"*"})
    assert "native_stop_violation" in _codes(res.errors)


def test_only_tighten_false_needs_loosen_stop_permission() -> None:
    """Dedicated safety test: loosening a stop is permission gated."""
    params = {"mode": "absolute", "value": 1, "only_tighten": False}
    a = {"node_id": "a1", "type": "modify_stop_loss", "params": params}
    rule = _doc(_cmp(PRICE, {"const": 1}), [a])
    res = validate_rule(rule, REG, {"orders:write"})
    (e,) = [i for i in res.errors if i.code == "permission_required"]
    assert e.klass == "safety"
    granted = validate_rule(rule, REG, {"rules.loosen_stop"})
    assert "permission_required" not in _codes(granted.errors)
    tighten = {**a, "params": {"mode": "absolute", "value": 1}}
    assert validate_rule(_doc(_cmp(PRICE, {"const": 1}), [tighten]), REG).valid


def test_trigger_metric_validated() -> None:
    rule = _doc(_cmp(PRICE, {"const": 1}), trigger={"type": "on_metric_change", "metric": "ghost"})
    assert "unknown_metric" in _codes(validate_rule(rule, REG).errors)


@pytest.mark.parametrize(
    ("trigger", "expected"),
    [
        ({"type": "on_price_update"}, 600),
        ({"type": "on_price_update", "debounce_ms": 1000}, 60),
        ({"type": "on_bar_close", "timeframe": "1m"}, 1),
        ({"type": "on_timer", "interval_ms": 5000}, 12),
        ({"type": "on_schedule", "cron": "* * * * *"}, 1),
        ({"type": "on_order_fill"}, 60),
        ({"type": "on_order_fill", "debounce_ms": 2000}, 30),
    ],
)
def test_estimated_evaluations_per_minute(trigger: dict[str, Any], expected: int) -> None:
    assert estimate_evaluations_per_minute(_rule(trigger=trigger)) == expected


def test_high_frequency_performance_warning() -> None:
    res = validate_rule(_doc(_cmp(PRICE, {"const": 1})), REG)
    assert any(w.klass == "performance" for w in res.warnings)


class _P:
    def __init__(self, *perms: str) -> None:
        self.perms = set(perms)

    def has(self, p: str) -> bool:
        return p in self.perms


class _R:
    def __init__(self, p: _P) -> None:
        self.p = p

    def resolve(self, request: object) -> _P:
        return self.p


def _client(p: _P | None = None, empty: bool = False) -> TestClient:
    app = FastAPI()
    reg = None if empty else REG
    principal = _P("rules:read") if p is None else p
    app.include_router(make_rules_router(lambda: reg, principal_resolver=_R(principal)))
    return TestClient(app)


def _cycle_graph() -> tuple[dict[str, Any], list[str]]:
    g = _jsonable(to_graph_model(_rule("form_all_of_any_of.json")))
    b = [n["id"] for n in g["nodes"] if n["type"] == "boolean"]
    g["edges"] += [
        {"from": b[0], "to": b[1], "port": "in"},
        {"from": b[1], "to": b[0], "port": "in"},
    ]
    return g, b


def test_compile_endpoint_hash_equality_between_editors() -> None:
    ir = _rule("form_all_of_any_of.json")
    c, url = _client(), f"/rules/{RULE_ID}/compile"
    f = c.post(url, json={"editor": "form", "model": _jsonable(to_form_model(ir))})
    g = c.post(url, json={"editor": "graph", "model": _jsonable(to_graph_model(ir))})
    assert f.status_code == g.status_code == 200
    assert f.json()["ir_hash"] == g.json()["ir_hash"] == ir_hash(ir)
    assert isinstance(f.json()["issues"], list)


def test_compile_endpoint_cycle_is_422_rule_ir_invalid() -> None:
    g, b = _cycle_graph()
    r = _client().post(f"/rules/{RULE_ID}/compile", json={"editor": "graph", "model": g})
    body = r.json()
    assert r.status_code == 422
    assert body["code"] == "rule_ir_invalid"
    assert "ir" not in body
    assert body["errors"][0]["rule"] == "cycle_detected"
    assert body["errors"][0]["field"]
    assert set(b) <= set(body["errors"][0]["node_ids"])


def test_validate_endpoint_shapes_and_examples() -> None:
    ir = json.loads(_rule().model_dump_json())
    ir["limits"] = {}
    ir["actions"] = [_notify()]
    body = _client().post("/rules/validate", json={"ir": ir}).json()
    assert body["valid"] is True
    assert body["warnings"][0]["code"] == "guard_missing"
    assert body["warnings"][0]["path"] == "guards.cooldown_seconds"
    for key in (
        "errors",
        "referenced_variables",
        "referenced_actions",
        "estimated_evaluations_per_minute",
    ):
        assert key in body
    ir["conditions"]["left"] = {"metric": "atr"}
    ir["conditions"]["right"] = {"const": "5%"}
    bad = _client().post("/rules/validate", json={"ir": ir}).json()
    assert bad["valid"] is False
    assert bad["errors"][0]["code"] == "type_mismatch"
    broken = _client().post("/rules/validate", json={"ir": {"nope": 1}}).json()
    assert broken["valid"] is False
    assert broken["errors"][0]["code"] == "schema_error"


def test_endpoints_rbac_and_bad_requests() -> None:
    for path in ("/rules/validate", f"/rules/{RULE_ID}/compile"):
        assert _client(_P("orders:read")).post(path, json={}).status_code == 403
        assert _client().post(path, content=b"not json").status_code == 400
        assert _client().post(path, json={}).status_code == 400
        assert _client(empty=True).post(path, json={}).status_code == 503
    bad = {"editor": "x", "model": {}}
    assert _client().post(f"/rules/{RULE_ID}/compile", json=bad).status_code == 400
