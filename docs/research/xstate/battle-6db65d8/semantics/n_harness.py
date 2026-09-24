"""Minimal attack harness for the round-5 SEMANTICS re-run (3ed3099).

Each attack is an async function registered with @attack(id, title, intent).
It returns a dict; a key "ok" of False (or a raised exception) is a FAIL.
Results are written to results/<group>.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import traceback
from typing import Any, Callable, Dict, List

logging.disable(logging.CRITICAL)

_REG: List[Dict[str, Any]] = []


def attack(aid: str, title: str, intent: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "intent": intent, "fn": fn})
        return fn

    return deco


def run_all(group: str) -> int:
    out: List[Dict[str, Any]] = []
    npass = 0
    for a in _REG:
        rec = {"id": a["id"], "title": a["title"], "intent": a["intent"]}
        try:
            fn = a["fn"]
            res = asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
            rec["detail"] = res
            rec["status"] = "PASS" if res.get("ok") else "FAIL"
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "ERROR"
            rec["detail"] = {
                "exc": f"{type(exc).__name__}: {exc}",
                "tb": traceback.format_exc()[-1200:],
            }
        if rec["status"] == "PASS":
            npass += 1
        out.append(rec)
        print(f"[{rec['status']:5}] {rec['id']:10} {rec['title']}")
        if rec["status"] != "PASS":
            print(f"          -> {json.dumps(rec['detail'], default=str)[:900]}")
    os.makedirs(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"),
        exist_ok=True,
    )
    p = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "results", f"{group}.json"
    )
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    return 0 if npass == len(out) else 1


def main(group: str) -> None:
    sys.exit(run_all(group))
