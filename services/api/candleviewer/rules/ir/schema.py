"""JSON Schema for the rule IR, generated from the pydantic models (E35-T01).

Published at ``GET /api/v1/schemas/rule-ir.json``; the committed copy
(``rule-ir.json`` next to this file) is guarded against drift by
``scripts/generate_rule_ir_schema.py --check``.
"""

from __future__ import annotations

import json
from typing import Any

from candleviewer.rules.ir.models import Rule

SCHEMA_ID = "https://candleviewer.local/schemas/rule-ir-v1.json"


def to_json_schema() -> dict[str, Any]:
    schema = Rule.model_json_schema(mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
        "title": "CandleViewer Rule IR",
    }


def render_schema() -> str:
    return json.dumps(to_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
