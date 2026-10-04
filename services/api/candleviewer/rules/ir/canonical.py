"""Canonical serialisation and content hash for the rule IR (ADR-0026, E35-T01).

Strategy 2 of the E35-K01 spike: JCS-style JSON where every number is a canonical decimal string,
sha256 over UTF-8 bytes. Computed server-side only, before persistence (never from a jsonb
round-trip). Any change to this algorithm changes every hash: bump ``IR_HASH_VERSION`` and ship an
upcaster.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from candleviewer.rules.ir.models import Rule

IR_HASH_VERSION = 1

# Presentation fields (ADR-0026 §4) plus persistence metadata that changes on every save and so
# must not mint a new content hash. Stripped ONLY from the top-level Rule document: free-form
# ``params`` dicts (Action/MetricRef) are semantic and must never lose keys.
PRESENTATION_KEYS = frozenset({"graph_layout", "editor"})
METADATA_KEYS = frozenset({"created_by", "created_at", "updated_at"})
_EXCLUDED = PRESENTATION_KEYS | METADATA_KEYS


def parse_ir_json(text: str) -> Rule:
    """Parse IR JSON text into a ``Rule`` without a float round-trip (numbers become Decimal)."""
    raw = json.loads(text, parse_float=Decimal)
    return Rule.model_validate(raw)


def dec_str(d: Decimal) -> str:
    """Plain notation, no exponent, no trailing fractional zeros, no ``+``, ``-0`` -> ``0``."""
    if d == 0:
        return "0"
    return format(d.normalize(), "f")


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: v for k, v in node.items() if k not in _EXCLUDED}
    return node


# Free-form payloads: never renumbered (their values are data, not node references).
_OPAQUE_KEYS = frozenset({"params", "const"})


def _renumber(doc: Any) -> Any:
    """Rewrite ``node_id``/``ref`` in DFS first-visit order (hash view only, ADR-0026 §3)."""
    mapping: dict[str, str] = {}

    def visit(n: Any) -> None:
        if isinstance(n, dict):
            nid = n.get("node_id")
            if isinstance(nid, str) and nid not in mapping:
                mapping[nid] = f"n{len(mapping) + 1}"
            for k in sorted(n):
                if k not in _OPAQUE_KEYS:
                    visit(n[k])
        elif isinstance(n, (list, tuple)):
            for v in n:
                visit(v)

    def rewrite(n: Any) -> Any:
        if isinstance(n, dict):
            return {
                k: (
                    v
                    if k in _OPAQUE_KEYS
                    else (
                        mapping.get(v, v)
                        if k in ("node_id", "ref") and isinstance(v, str)
                        else rewrite(v)
                    )
                )
                for k, v in n.items()
            }
        if isinstance(n, (list, tuple)):
            return [rewrite(v) for v in n]
        return n

    visit(doc)
    return rewrite(doc)


def _normalise(o: Any) -> Any:
    if isinstance(o, bool) or o is None or isinstance(o, str):
        return o
    if isinstance(o, (int, Decimal)):
        return dec_str(Decimal(o))
    if isinstance(o, UUID):
        return str(o)
    if isinstance(o, dict):
        return {k: _normalise(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_normalise(v) for v in o]
    raise TypeError(f"unsupported type in IR: {type(o).__name__}")


def _as_rule(ir: Rule | dict[str, Any]) -> Rule:
    return ir if isinstance(ir, Rule) else Rule.model_validate(ir)


def canonicalize(ir: Rule | dict[str, Any]) -> bytes:
    """Canonical UTF-8 bytes of the hashed view of ``ir`` (idempotent, order-insensitive)."""
    dumped = _as_rule(ir).model_dump(mode="python")
    view = _normalise(_renumber(_strip(dumped)))
    return json.dumps(view, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def ir_hash(ir: Rule | dict[str, Any]) -> str:
    """sha256 hex of ``canonicalize(ir)``."""
    return hashlib.sha256(canonicalize(ir)).hexdigest()
