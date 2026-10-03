"""Form-editor front-end: ``compile_form`` / ``to_form_model`` (E35-T04).

The form model is the rule document with a *linear restricted* ``conditions`` tree (no node ids,
no arithmetic operands, at most ``all_of`` of ``any_of`` of comparisons). Node ids are minted
deterministically here; the hash renumbers them anyway.
"""

from __future__ import annotations

from typing import Any

from candleviewer.rules.compiler.common import build_rule, check_bounds
from candleviewer.rules.ir import Rule, form_incompatibility_reasons
from candleviewer.rules.issues import Issue, RuleCompileError

_OPAQUE = frozenset({"params", "const", "set_values"})
_COND_KEYS = ("children", "child")


def _mint_conditions(node: Any, counter: list[int]) -> Any:
    """Pre-order id assignment over the condition tree (iterative-safe: depth is bounded)."""
    if not isinstance(node, dict):
        return node
    out = dict(node)
    counter[0] += 1
    out.setdefault("node_id", f"c{counter[0]}")
    if isinstance(out.get("children"), list):
        out["children"] = [_mint_conditions(c, counter) for c in out["children"]]
    if "child" in out:
        out["child"] = _mint_conditions(out["child"], counter)
    for name in ("left", "right", "right2"):
        v = out.get(name)
        if isinstance(v, dict) and "operands" in v:
            out[name] = _mint_conditions(v, counter)
    if isinstance(out.get("operands"), list):
        out["operands"] = [_mint_conditions(o, counter) for o in out["operands"]]
    return out


def compile_form(model: dict[str, Any], rule_id: Any = None) -> Rule:
    """Compile a form-editor model to the canonical IR (never auto-reconciles)."""
    check_bounds(model, "form model")
    doc = dict(model)
    if rule_id is not None:
        doc["rule_id"] = rule_id
    doc["editor"] = "form"
    counter = [0]
    if "conditions" in doc:
        doc["conditions"] = _mint_conditions(doc["conditions"], counter)
    if isinstance(doc.get("actions"), list):
        doc["actions"] = [
            {**a, "node_id": a.get("node_id", f"a{i + 1}")} if isinstance(a, dict) else a
            for i, a in enumerate(doc["actions"])
        ]
    rule = build_rule(doc)
    reasons = form_incompatibility_reasons(rule)
    if reasons:
        raise RuleCompileError(
            [
                Issue(
                    "conditions",
                    "schema_error",
                    f"The form editor cannot express this rule: {r}. Use the graph editor.",
                    klass="syntax",
                )
                for r in reasons
            ]
        )
    return rule


def _strip_ids(node: Any, in_opaque: bool = False) -> Any:
    if isinstance(node, dict):
        return {
            k: (v if k in _OPAQUE else _strip_ids(v)) for k, v in node.items() if k != "node_id"
        }
    if isinstance(node, (list, tuple)):
        return [_strip_ids(v) for v in node]
    return node


def to_form_model(ir: Rule) -> dict[str, Any]:
    """Decompile a form-compatible IR into the form model; ``ValueError`` otherwise."""
    reasons = form_incompatibility_reasons(ir)
    if reasons:
        raise ValueError("rule is not form-compatible: " + "; ".join(reasons))
    doc = ir.model_dump(mode="python")
    doc.pop("graph_layout", None)
    doc["editor"] = "form"
    doc["conditions"] = _strip_ids(doc["conditions"])
    doc["actions"] = [_strip_ids(a) for a in doc["actions"]]
    return doc
