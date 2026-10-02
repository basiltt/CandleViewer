"""THROWAWAY prototype for E35-K01: three IR canonicalisation strategies. Not production code."""
from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal
from typing import Any

import cbor2

PRESENTATION_KEYS = ("presentation", "graph_layout", "editor", "comment", "collapsed")


def parse_ir(text: str) -> Any:
    """Parse JSON keeping every non-integer number as Decimal (no float round-trip)."""
    return json.loads(text, parse_float=Decimal, parse_int=int)


def dec_str(d: Decimal) -> str:
    """Canonical decimal text: plain notation, no exponent, no trailing zeros, no '-0'."""
    if d == 0:
        return "0"
    return format(d.normalize(), "f")


def strip_presentation(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: strip_presentation(v) for k, v in node.items() if k not in PRESENTATION_KEYS}
    if isinstance(node, list):
        return [strip_presentation(v) for v in node]
    return node


def renumber(doc: Any) -> Any:
    """Hash view only: rewrite node_id and ref in DFS first-visit order (n1, n2, ...).

    The stored IR keeps author ids; only the hashed copy is renumbered.
    """
    mapping: dict[str, str] = {}

    def visit(n: Any) -> None:
        if isinstance(n, dict):
            if "node_id" in n and n["node_id"] not in mapping:
                mapping[n["node_id"]] = f"n{len(mapping) + 1}"
            for k in sorted(n):  # sorted: dict key order must not influence ids
                visit(n[k])
        elif isinstance(n, list):
            for v in n:
                visit(v)

    visit(doc)

    def rewrite(n: Any) -> Any:
        if isinstance(n, dict):
            return {
                k: (mapping.get(v, v) if k in ("node_id", "ref") and isinstance(v, str)
                    else rewrite(v))
                for k, v in n.items()
            }
        if isinstance(n, list):
            return [rewrite(v) for v in n]
        return n

    return rewrite(doc)


def _prep(doc: Any) -> Any:
    return renumber(strip_presentation(copy.deepcopy(doc)))


def _map_dec(o: Any, fn: Any) -> Any:
    if isinstance(o, Decimal) or (isinstance(o, int) and not isinstance(o, bool)):
        return fn(Decimal(o))
    if isinstance(o, dict):
        return {k: _map_dec(v, fn) for k, v in o.items()}
    if isinstance(o, list):
        return [_map_dec(v, fn) for v in o]
    return o


def _dumps(o: Any, sort_keys: bool = True) -> bytes:
    return json.dumps(o, sort_keys=sort_keys, separators=(",", ":"), ensure_ascii=False).encode()


def canon_jcs_float(doc: Any, sort_keys: bool = True) -> bytes:
    """Strategy 1: Decimal -> IEEE double (JCS number rules)."""
    return _dumps(_map_dec(_prep(doc), float), sort_keys)


def canon_jcs_decstr(doc: Any, sort_keys: bool = True) -> bytes:
    """Strategy 2: Decimal -> canonical string."""
    return _dumps(_map_dec(_prep(doc), dec_str), sort_keys)


def canon_cbor(doc: Any) -> bytes:
    """Strategy 3: canonical CBOR of the decimal-string form."""
    return cbor2.dumps(_map_dec(_prep(doc), dec_str), canonical=True)


STRATEGIES = {"jcs_float": canon_jcs_float, "jcs_decstr": canon_jcs_decstr, "cbor": canon_cbor}


def ir_hash(doc: Any, strategy: str = "jcs_decstr") -> str:
    return hashlib.sha256(STRATEGIES[strategy](doc)).hexdigest()
