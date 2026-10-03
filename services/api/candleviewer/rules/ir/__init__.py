"""Rule IR: typed models, canonical hash, JSON Schema, form-subset detection (E35-T01)."""

from __future__ import annotations

from candleviewer.rules.ir.canonical import (
    IR_HASH_VERSION,
    canonicalize,
    ir_hash,
    parse_ir_json,
)
from candleviewer.rules.ir.form import form_compatible, form_incompatibility_reasons
from candleviewer.rules.ir.models import (
    Action,
    ArithmeticNode,
    BooleanNode,
    Comparison,
    ConditionNode,
    Literal_,
    MetricRef,
    Operand,
    Rule,
    RuleLimits,
    RuleScope,
    TemporalNode,
    Trigger,
)
from candleviewer.rules.ir.schema import to_json_schema

__all__ = [
    "IR_HASH_VERSION", "Action", "ArithmeticNode", "BooleanNode", "Comparison", "ConditionNode",
    "Literal_", "MetricRef", "Operand", "Rule", "RuleLimits", "RuleScope", "TemporalNode",
    "Trigger", "canonicalize", "form_compatible", "form_incompatibility_reasons", "ir_hash",
    "parse_ir_json", "to_json_schema",
]  # fmt: skip
