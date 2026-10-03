"""E35-T04: compilers, decompilers, semantic validator and the compile/validate endpoints."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from candleviewer.rules.compiler import compile_form, compile_graph, to_form_model, to_graph_model
from candleviewer.rules.ir import Rule, form_compatible, ir_hash
from candleviewer.rules.issues import RuleCompileError
from candleviewer.rules.vocabulary import default_registry

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
RULE_ID = "00000000-0000-4000-8000-000000000001"
REG = default_registry()
ALL = sorted(FIX.glob("*.json"))
PRICE = {"metric": "price"}


def _raw(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=str)  # type: ignore[no-any-return]


def _rule(name: str = "form_simple_0.json", **over: Any) -> Rule:
    return Rule.model_validate({**_raw(FIX / name), **over})


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


# ---- round trip -------------------------------------------------------------------------------
@pytest.mark.parametrize("path", ALL, ids=lambda p: p.stem)
def test_graph_round_trip_preserves_hash(path: Path) -> None:
    ir = Rule.model_validate(_raw(path))
    assert ir_hash(compile_graph(to_graph_model(ir), ir.rule_id)) == ir_hash(ir)


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.stem)
def test_form_round_trip_for_form_subset(path: Path) -> None:
    ir = Rule.model_validate(_raw(path))
    if not form_compatible(ir):
        with pytest.raises(ValueError, match="not form-compatible"):
            to_form_model(ir)
        return
    assert ir_hash(compile_form(to_form_model(ir), ir.rule_id)) == ir_hash(ir)


def test_both_editors_compile_to_the_same_hash() -> None:
    """Scenario: Both editors compile to the same hash"""
    ir = _rule("form_all_of_any_of.json")
    via_form = compile_form(to_form_model(ir), ir.rule_id)
    via_graph = compile_graph(to_graph_model(ir), ir.rule_id)
    assert ir_hash(via_form) == ir_hash(via_graph)


def test_auto_layout_is_deterministic_and_preserved() -> None:
    ir = _rule("form_all_of_any_of.json", graph_layout=None)
    a, b = to_graph_model(ir), to_graph_model(ir)
    assert a["graph_layout"] == b["graph_layout"]
    assert a["graph_layout"]["auto"] is True
    laid = _rule("form_simple_0.json")
    assert to_graph_model(laid)["graph_layout"] == laid.graph_layout


# ---- graph well-formedness --------------------------------------------------------------------
def _graph() -> dict[str, Any]:
    return to_graph_model(_rule("form_all_of_any_of.json"))


def _bools(g: dict[str, Any]) -> list[str]:
    return [n["id"] for n in g["nodes"] if n["type"] == "boolean"]


def test_cycle_is_refused_with_a_readable_path() -> None:
    """Scenario: A cycle is refused with a readable path"""
    g = _graph()
    bools = _bools(g)
    assert len(bools) >= 2
    g["edges"] += [
        {"from": bools[0], "to": bools[1], "port": "in"},
        {"from": bools[1], "to": bools[0], "port": "in"},
    ]
    with pytest.raises(RuleCompileError) as ei:
        compile_graph(g, RULE_ID)
    (issue,) = ei.value.issues
    assert issue.code == "cycle_detected"
    assert set(bools) <= set(issue.node_ids)
    assert "->" in issue.message


@pytest.mark.parametrize("n", [1, 2, 5])
def test_cycle_of_any_length_and_self_loop(n: int) -> None:
    nodes = [{"id": f"b{i}", "type": "boolean", "data": {"op": "all_of"}} for i in range(n)]
    edges = [{"from": f"b{i}", "to": f"b{(i + 1) % n}", "port": "in"} for i in range(n)]
    edges.append({"from": "b0", "to": "a", "port": "when"})
    g = {"nodes": [*nodes, {"id": "a", "type": "action", "data": {}}], "edges": edges}
    with pytest.raises(RuleCompileError) as ei:
        compile_graph(g)
    assert ei.value.issues[0].code == "cycle_detected"


def test_dangling_port_and_orphan_are_listed_by_node() -> None:
    g = _graph()
    g["nodes"].append({"id": "lonely", "type": "comparison", "data": {"op": "gt"}})
    with pytest.raises(RuleCompileError) as ei:
        compile_graph(g, RULE_ID)
    assert {i.code for i in ei.value.issues} == {"dangling_port"}
    assert ei.value.issues[0].node_ids == ("lonely",)
    g = _graph()
    g["nodes"].append({"id": "stray", "type": "operand", "data": {"const": 1}})
    with pytest.raises(RuleCompileError) as ei2:
        compile_graph(g, RULE_ID)
    assert ei2.value.issues[0].code == "orphan_node"
    assert ei2.value.issues[0].node_ids == ("stray",)


def test_multiple_sinks_and_missing_actions_are_errors() -> None:
    g = _graph()
    action = next(n for n in g["nodes"] if n["type"] == "action")
    g["nodes"].append({"id": "a2", "type": "action", "data": copy.deepcopy(action["data"])})
    other = next(n["id"] for n in g["nodes"] if n["type"] == "comparison")
    g["edges"].append({"from": other, "to": "a2", "port": "when"})
    with pytest.raises(RuleCompileError) as ei:
        compile_graph(g, RULE_ID)
    assert "multiple_sinks" in _codes(ei.value.issues)
    with pytest.raises(RuleCompileError):
        compile_graph({"nodes": [{"id": "x", "type": "operand", "data": {}}], "edges": []})


@pytest.mark.parametrize(
    "model",
    [
        {},
        {"nodes": [], "edges": []},
        {"nodes": [{"id": 1}], "edges": []},
        {"nodes": [{"id": "a", "type": "nope"}], "edges": []},
        {
            "nodes": [{"id": "a", "type": "action"}],
            "edges": [{"from": "a", "to": "z", "port": "in"}],
        },
        {"nodes": [{"id": "a", "type": "action"}, {"id": "a", "type": "action"}], "edges": []},
    ],
)
def test_malformed_graph_models_never_crash(model: dict[str, Any]) -> None:
    with pytest.raises(RuleCompileError):
        compile_graph(model)


def test_hostile_documents_are_bounded_before_walking() -> None:
    deep: Any = {"x": 1}
    for _ in range(200):
        deep = {"x": deep}
    for fn in (compile_form, compile_graph):
        with pytest.raises(RuleCompileError, match="too large"):
            fn(deep)
    many = {"nodes": [{"id": str(i), "type": "operand"} for i in range(1001)], "edges": []}
    with pytest.raises(RuleCompileError):
        compile_graph(many)


def test_schema_errors_name_a_path() -> None:
    with pytest.raises(RuleCompileError) as ei:
        compile_form({"name": "x"})
    assert all(i.path and i.code == "schema_error" for i in ei.value.issues)


def test_graph_only_construct_is_marked_at_compile_time() -> None:
    """Scenario: Graph-only construct is marked at compile time, not at switch time"""
    ir = _rule("shared_node_fanout.json")
    out = compile_graph(to_graph_model(ir), ir.rule_id)
    marks = (out.graph_layout or {}).get("node_only_constructs")
    assert marks
    assert any("fans out" in m for m in marks)
    form = to_form_model(_rule("form_simple_0.json"))
    form["conditions"] = _jsonable(ir.model_dump())["conditions"]
    with pytest.raises(RuleCompileError, match="form editor cannot express"):
        compile_form(form)
    plain = compile_graph(to_graph_model(_rule("form_simple_0.json")), RULE_ID)
    assert "node_only_constructs" not in (plain.graph_layout or {})
