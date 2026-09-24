"""Shared probe harness for xstate-statemachine semantic conformance probes.

Each probe registers with @probe(id, title, expected). It returns an
"observed" value (any JSON-able). The harness compares observed to expected
and records PASS / FAIL / ERROR, then dumps JSON to results/<file>.json.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sys
import traceback
from typing import Any, Callable, Dict, List

logging.disable(logging.CRITICAL)

RESULTS: List[Dict[str, Any]] = []
_REGISTRY: List[Dict[str, Any]] = []


def probe(pid: str, title: str, expected: Any) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REGISTRY.append(
            {"id": pid, "title": title, "expected": expected, "fn": fn}
        )
        return fn

    return deco


def _norm(v: Any) -> Any:
    if isinstance(v, set):
        return sorted(v)
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    return v


async def _run_one(rec: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": rec["id"],
        "title": rec["title"],
        "expected": _norm(rec["expected"]),
    }
    try:
        res = rec["fn"]()
        if inspect.isawaitable(res):
            res = await res
        obs = _norm(res)
        out["observed"] = obs
        out["status"] = "PASS" if obs == out["expected"] else "FAIL"
    except Exception as exc:  # noqa: BLE001
        out["observed"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc()[-1200:]
        out["status"] = "ERROR"
    return out


def run_all(name: str) -> None:
    async def _main() -> None:
        for rec in _REGISTRY:
            RESULTS.append(await _run_one(rec))

    asyncio.run(_main())
    here = os.path.dirname(os.path.abspath(__file__))
    rdir = os.path.join(here, "results")
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    for r in RESULTS:
        print(f"[{r['status']:5}] {r['id']:8} {r['title']}")
        if r["status"] != "PASS":
            print(f"          expected: {json.dumps(r['expected'], default=str)}")
            print(f"          observed: {json.dumps(r['observed'], default=str)}")
    n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
    print(f"\n{name}: {n_pass}/{len(RESULTS)} PASS")
    sys.stdout.flush()
