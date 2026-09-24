"""Minimal harness for main@5327ba6 adversarial probes."""

from __future__ import annotations

import json
import logging
import sys
import traceback
from typing import Any, Callable, Dict, List

logging.disable(logging.CRITICAL)

_REG: List[Dict[str, Any]] = []
RESULTS: List[Dict[str, Any]] = []


def probe(pid: str, title: str, expected: Any) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": pid, "title": title, "expected": expected, "fn": fn})
        return fn

    return deco


def _norm(v: Any) -> Any:
    if isinstance(v, (set, frozenset)):
        return sorted(str(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    return v


def run(name: str) -> int:
    import asyncio
    import inspect

    for rec in _REG:
        out = {"id": rec["id"], "title": rec["title"], "expected": _norm(rec["expected"])}
        try:
            res = rec["fn"]()
            if inspect.isawaitable(res):
                res = asyncio.run(asyncio.wait_for(_aw(res), timeout=30))
            out["observed"] = _norm(res)
            out["status"] = "PASS" if out["observed"] == out["expected"] else "FAIL"
        except Exception as exc:  # noqa: BLE001
            out["observed"] = f"{type(exc).__name__}: {exc}"
            out["traceback"] = traceback.format_exc()[-1500:]
            out["status"] = "ERROR"
        RESULTS.append(out)
        print(f"[{out['status']:5}] {out['id']} {out['title']}")
        if out["status"] != "PASS":
            print(f"        expected: {out['expected']!r}")
            print(f"        observed: {out['observed']!r}")
    with open(f"{name}.json", "w", encoding="utf-8") as fh:
        json.dump(RESULTS, fh, indent=2, default=str)
    bad = sum(1 for r in RESULTS if r["status"] != "PASS")
    print(f"\n{name}: {len(RESULTS) - bad}/{len(RESULTS)} pass")
    return 1 if bad else 0


async def _aw(coro):
    return await coro


def main(name: str) -> None:
    sys.exit(run(name))
