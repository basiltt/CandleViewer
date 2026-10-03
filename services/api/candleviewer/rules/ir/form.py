"""Form-subset detection (`24-internal-schemas.md` section 11.4, E35-T01).

Form subset: trigger + two-level boolean tree (``all_of`` of ``any_of`` of comparisons) + flat
actions + limits; operands are metric refs / constants only (no arithmetic); temporal nodes only as
``sustained_for`` directly wrapping a comparison.
"""

from __future__ import annotations

from candleviewer.rules.ir.models import (
    ArithmeticNode,
    BooleanNode,
    Comparison,
    ConditionNode,
    Rule,
    TemporalNode,
)


def _operand_reasons(c: Comparison, out: list[str]) -> None:
    for name in ("left", "right", "right2"):
        if isinstance(getattr(c, name), ArithmeticNode):
            out.append(f"{c.node_id}: arithmetic operand in '{name}' (graph-only construct)")


def _leaf_reasons(node: ConditionNode, out: list[str]) -> None:
    if isinstance(node, Comparison):
        _operand_reasons(node, out)
    elif isinstance(node, TemporalNode):
        if node.op != "sustained_for":
            out.append(f"{node.node_id}: temporal op '{node.op}' is graph-only")
        if isinstance(node.child, Comparison):
            _operand_reasons(node.child, out)
        else:
            out.append(f"{node.node_id}: temporal node must directly wrap a comparison")
    else:
        out.append(f"{node.node_id}: boolean '{node.op}' nested deeper than two levels")


def _group_reasons(node: BooleanNode, depth: int, out: list[str]) -> None:
    if node.op not in ("all_of", "any_of"):
        out.append(f"{node.node_id}: boolean op '{node.op}' is graph-only")
        return
    for child in node.children:
        if isinstance(child, BooleanNode):
            if depth == 0 and node.op == "all_of" and child.op == "any_of":
                _group_reasons(child, 1, out)
            elif depth == 0 and node.op == "any_of":
                out.append(f"{child.node_id}: boolean nested inside root any_of (exceeds subset)")
            else:
                _leaf_reasons(child, out)
        else:
            _leaf_reasons(child, out)


def _walk_ids(node: object, seen: dict[str, int]) -> None:
    nid = getattr(node, "node_id", None)
    if isinstance(nid, str):
        seen[nid] = seen.get(nid, 0) + 1
    if isinstance(node, BooleanNode):
        for c in node.children:
            _walk_ids(c, seen)
    elif isinstance(node, TemporalNode):
        _walk_ids(node.child, seen)
    elif isinstance(node, Comparison):
        for name in ("left", "right", "right2"):
            op = getattr(node, name)
            if isinstance(op, ArithmeticNode):
                _walk_ids(op, seen)
    elif isinstance(node, ArithmeticNode):
        for o in node.operands:
            _walk_ids(o, seen)


def form_incompatibility_reasons(ir: Rule) -> list[str]:
    """Reasons naming the offending ``node_id`` and construct; empty means form-compatible."""
    out: list[str] = []
    root = ir.conditions
    if isinstance(root, BooleanNode):
        _group_reasons(root, 0, out)
    else:
        _leaf_reasons(root, out)
    seen: dict[str, int] = {}
    _walk_ids(root, seen)
    for nid, n in sorted(seen.items()):
        if n > 1:
            out.append(f"{nid}: node fans out to {n} consumers (shared node, graph-only)")
    return out


def form_compatible(ir: Rule) -> bool:
    return not form_incompatibility_reasons(ir)
