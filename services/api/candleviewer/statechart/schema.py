"""JSON-Schema (2020-12) for the CV machine-JSON contract (E50-T01).

Deliberately loose on the *behavioural* shape (states/transitions nest
arbitrarily) and strict on the *known-key* surface: the schema below only
pins the handful of top-level keys every catalogue chart's `1.3c` mandatory
config block requires (28-statechart-catalogue.md), plus basic JSON types.
The exhaustive "no unknown key anywhere, including inside `invoke.src`" rule
is `CV-C57` and lives in `keys.py` as a dedicated recursive walk — a single
`additionalProperties: false` schema cannot express "unless the key is
`x-`-prefixed" at every nesting depth without duplicating the whole grammar,
so JSON-Schema here is deliberately a coarse net (types, required keys) and
`keys.py` is the fine one (exact key vocabulary, incl. inline invoke).
"""

from __future__ import annotations

from typing import Any

#: Root-level keys the 1.3c mandatory config block requires on every
#: catalogue chart. `registry.validate()` checks these are *present* and
#: correctly typed; `keys.py` checks nothing *else* sneaks in.
MACHINE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://candleviewer.internal/schemas/statechart/machine.json",
    "title": "CV statechart machine-JSON contract",
    "type": "object",
    "required": [
        "id",
        "strictConfig",
        "strict",
        "strictTargets",
        "onUnhandled",
        "maxIterations",
        "states",
    ],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "version": {"type": "integer"},
        "type": {"enum": ["parallel", "compound", "atomic", "final", "history"]},
        "initial": {"type": "string"},
        "context": {"type": "object"},
        "states": {"type": "object", "minProperties": 1},
        "on": {"type": "object"},
        "always": {},
        "after": {"type": "object"},
        "entry": {"type": "array"},
        "exit": {"type": "array"},
        "invoke": {},
        "onDone": {},
        "history": {"type": "string"},
        "output": {},
        "target": {"type": "string"},
        "meta": {"type": "object"},
        "description": {"type": "string"},
        "tags": {"type": "array"},
        # 1.3c mandatory policy block (28-statechart-catalogue.md §1.3c).
        "strictConfig": {"const": True},
        "strict": {"const": True},
        "strictTargets": {"const": True},
        "onUnhandled": {"const": "defer"},
        "maxIterations": {"type": "integer", "minimum": 1},
        "actionErrorPolicy": {"enum": ["rollback", "continue"]},
        "guardErrorPolicy": {"enum": ["raise", "continue"]},
        "spawnBlockingTimeout": {"type": "integer", "minimum": 0},
    },
    # Unknown top-level keys are CV-C57's job (recursive, path-named), not
    # this schema's — see the module docstring.
    "additionalProperties": True,
}


def canonical_json(chart: dict[str, Any]) -> bytes:
    """Deterministic UTF-8 JSON bytes: sorted keys, no incidental whitespace.

    Used by `registry.hash()` so `machine_hash` (`sha256(canonical_json(chart))`)
    is stable across key reordering (ticket acceptance criterion 3) and
    across platforms (fixed separators, no locale-dependent formatting).
    """
    import json

    return json.dumps(chart, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
