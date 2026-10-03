"""E35-T01 rule IR tests; test names reference the Gherkin scenarios."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from candleviewer.rules.ir import (
    Rule,
    RuleLimits,
    RuleScope,
    canonicalize,
    form_compatible,
    form_incompatibility_reasons,
    ir_hash,
    parse_ir_json,
    to_json_schema,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "rule_ir"
FILES = sorted(FIXTURES.glob("*.json"))


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def test_corpus_has_at_least_30_rules() -> None:
    assert len(FILES) >= 30


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_fixture_round_trip_and_schema(path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rule = Rule.model_validate(raw)
    again = Rule.model_validate(rule.model_dump(mode="python"))
    assert again == rule
    assert ir_hash(again) == ir_hash(rule)
    jsonschema.validate(raw, to_json_schema())


def test_canonical_hash_is_stable_under_cosmetic_difference() -> None:
    a = load("form_simple_0")
    a["conditions"]["right"] = {"const": 1.5}
    text = json.dumps(a).replace("1.5}", "1.5000}")
    assert "1.5000" in text
    b = parse_ir_json(text)
    b2 = json.loads(json.dumps(dict(reversed(list(a.items())))))
    b2["graph_layout"] = {"c1": {"x": 999, "y": -4}}
    assert ir_hash(a) == ir_hash(b)
    assert ir_hash(a) == ir_hash(b2)
    assert canonicalize(a) == canonicalize(b)


def test_presentation_fields_are_excluded_from_the_hash() -> None:
    a = load("form_all_of_any_of")
    base = ir_hash(a)
    b = copy.deepcopy(a)
    b["graph_layout"] = {"g1": {"x": 1, "y": 2}}
    b["editor"] = "graph"
    assert ir_hash(b) == base
    r = Rule.model_validate(b)
    assert r.graph_layout == {"g1": {"x": 1, "y": 2}}
    assert Rule.model_validate(json.loads(r.model_dump_json())).graph_layout == r.graph_layout


def test_author_node_ids_do_not_change_hash() -> None:
    a = load("form_simple_1")
    b = copy.deepcopy(a)
    b["conditions"]["node_id"] = "zzz"
    assert ir_hash(a) == ir_hash(b)


def _set(d: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        d = d[int(k)] if isinstance(d, list) else d[k]
    d[keys[-1]] = value


MUTATIONS = [
    ("threshold", "conditions.right.const", 31),
    ("operator", "conditions.op", "gte"),
    ("action_params", "actions.0.params.channel", "email"),
    ("scope_env", "scope.environments", ["demo", "live"]),
    ("scope_symbol", "scope.symbols", ["ETHUSDT"]),
    ("limits", "limits.cooldown_ms", 5),
    ("trigger", "trigger", {"type": "on_book_update"}),
    ("name", "name", "other"),
    ("mode", "mode", "armed"),
    ("metric", "conditions.left.metric", "macd"),
    ("action_type", "actions.0.type", "pause_rule"),
]


@pytest.mark.parametrize(("label", "path", "value"), MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_hash_changes_on_semantic_mutation(label: str, path: str, value: Any) -> None:
    a = load("form_simple_1")
    b = copy.deepcopy(a)
    _set(b, path.replace("actions.0", "actions.0"), value)
    assert ir_hash(a) != ir_hash(b), label


def test_action_order_is_semantic() -> None:
    a = load("ten_actions")
    b = copy.deepcopy(a)
    b["actions"][0], b["actions"][1] = b["actions"][1], b["actions"][0]
    assert ir_hash(a) != ir_hash(b)


def test_canonical_bytes_are_exact_for_large_decimals() -> None:
    a = load("large_decimal")
    c1 = canonicalize(a)
    assert b'"123456789012345678.123456789"' in c1
    assert canonicalize(parse_ir_json(json.dumps(a))) == c1


def test_defaults_are_the_documented_safe_ones() -> None:
    assert RuleScope(level="global").environments == ("demo",)
    lim = RuleLimits()
    assert (lim.cooldown_ms, lim.max_fires_per_hour, lim.max_fires_per_day) == (1000, 60, 500)
    assert (lim.max_actions_per_fire, lim.evaluation_timeout_ms) == (10, 250)
    assert lim.kill_switch_on_error_count == 5


@pytest.mark.parametrize(
    ("name", "reason_part"),
    [
        ("shared_node_fanout", "c1: node fans out to 2 consumers"),
        ("nested_arith", "arithmetic operand in 'left'"),
        ("n_of", "n_of"),
        ("deep_nesting", "g3"),
        ("temporal_occurred_within", "occurred_within"),
    ],
)
def test_form_subset_detection_is_honest(name: str, reason_part: str) -> None:
    rule = Rule.model_validate(load(name))
    assert not form_compatible(rule)
    assert any(reason_part in r for r in form_incompatibility_reasons(rule))


@pytest.mark.parametrize(
    "name", ["form_simple_0", "form_all_of_any_of", "temporal_sustained", "between", "mixed_3"]
)
def test_form_compatible_cases(name: str) -> None:
    assert form_compatible(Rule.model_validate(load(name)))


def test_form_incompatible_extra_cases() -> None:
    a = load("form_all_of_any_of")
    a["conditions"]["op"] = "any_of"
    assert not form_compatible(Rule.model_validate(a))
    t = load("temporal_sustained")
    leaf = load("form_simple_0")["conditions"]
    t["conditions"]["child"] = {"node_id": "g", "op": "all_of", "children": [leaf]}
    assert any("directly wrap" in r for r in form_incompatibility_reasons(Rule.model_validate(t)))
    n = load("form_all_of_any_of")
    n["conditions"]["op"] = "none_of"
    assert not form_compatible(Rule.model_validate(n))
    deep = load("form_simple_0")
    inner = {"node_id": "g2", "op": "all_of", "children": [deep["conditions"]]}
    deep["conditions"] = {"node_id": "g", "op": "all_of", "children": [inner]}
    assert not form_compatible(Rule.model_validate(deep))
    arith = load("nested_arith")
    arith["conditions"]["right"] = {"node_id": "q", "op": "neg", "operands": [{"const": 1}]}
    assert any("'right'" in r for r in form_incompatibility_reasons(Rule.model_validate(arith)))
