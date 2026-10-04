"""The hop chain under test (E35-Q02): shared by the property suite, corpus and mutation gates."""

from __future__ import annotations

import copy
from typing import Any

from candleviewer.rules.compiler import compile_form, compile_graph, to_form_model, to_graph_model
from candleviewer.rules.errors import FormUnrepresentableError
from candleviewer.rules.ir import Rule, form_compatible, ir_hash

#: The only key a compiler may *add* to the presentation block (E35-T04 read-only marking).
COMPILER_LAYOUT_KEYS = frozenset({"node_only_constructs"})


class HopMismatch(AssertionError):
    """A hop changed the canonical hash or the presentation block."""


def _check(label: str, before: Rule, after: Rule, expected: str) -> None:
    got = ir_hash(after)
    if got != expected:
        raise HopMismatch(f"{label}: hash {got} != {expected}")
    want = before.graph_layout or {}
    have = {k: v for k, v in (after.graph_layout or {}).items() if k not in COMPILER_LAYOUT_KEYS}
    if want and have != {k: v for k, v in want.items() if k not in COMPILER_LAYOUT_KEYS}:
        raise HopMismatch(f"{label}: presentation block changed: {want!r} -> {have!r}")


def to_node(ir: Rule) -> Rule:
    return compile_graph(copy.deepcopy(to_graph_model(ir)), ir.rule_id)


def to_form(ir: Rule) -> Rule:
    return compile_form(copy.deepcopy(to_form_model(ir)), ir.rule_id)


def reorder_keys(o: Any) -> Any:
    """Reverse the key order of every mapping (incl. free-form ``params``): the wire hop.

    Editor documents arrive as JSON with arbitrary key order (ADR-0026 property (a)); a
    canonicaliser that does not sort keys only shows up when key order actually changes.
    """
    if isinstance(o, dict):
        return {k: reorder_keys(o[k]) for k in reversed(list(o))}
    if isinstance(o, (list, tuple)):
        return [reorder_keys(v) for v in o]
    return o


def wire(ir: Rule) -> Rule:
    return Rule.model_validate(reorder_keys(ir.model_dump(mode="python")))


def full_chain(doc: dict[str, Any] | Rule) -> str:
    """wire -> IR -> node -> IR -> form -> IR; returns the hash, raises ``HopMismatch`` on drift.

    A form-incompatible document must make the form hop raise ``FormUnrepresentableError``
    (fail loudly) - a returned document there is itself a failure.
    """
    ir = doc if isinstance(doc, Rule) else Rule.model_validate(doc)
    h = ir_hash(ir)
    _check("wire (key order)", ir, wire(ir), h)
    via_node = to_node(ir)
    _check("IR->node->IR", ir, via_node, h)
    if form_compatible(ir):
        via_form = to_form(via_node)
        _check("node->IR->form->IR", via_node, via_form, h)
        _check("form->node->IR", via_form, to_node(via_form), h)
    else:
        try:
            lossy = to_form_model(via_node)
        except FormUnrepresentableError:
            pass
        else:
            raise HopMismatch(f"form hop emitted a document for a graph-only rule: {lossy!r}")
    return h
