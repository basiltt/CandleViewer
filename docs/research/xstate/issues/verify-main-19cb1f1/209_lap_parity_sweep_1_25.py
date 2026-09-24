# -*- coding: utf-8 -*-
"""Verify #209 on main @ 19cb1f1: lap parity across all three lanes (sync,
async/def-service, async/async-service) at maxIterations limits 1..25,
on both `rollback_ondone` and `nested_invoke` shapes.

Acceptance criterion: sync_calls == async_def_calls == async_async_calls
at EVERY limit 1..25 (not just a curated subset), on both shapes.

Exit 0 = parity holds at every limit on both shapes.
Exit 1 = any mismatch found (regression of #209 / re-opening the #201
lap-count issue).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Dict

logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine


def rollback_ondone(mi: int) -> Dict[str, Any]:
    return {
        "id": "m0", "initial": "a", "actionErrorPolicy": "rollback",
        "maxIterations": mi,
        "states": {
            "a": {"invoke": {"id": "i1", "src": "svc", "onDone": {"target": "b"}}},
            "b": {"always": {"target": "a"}},
        },
    }


def nested_invoke(mi: int) -> Dict[str, Any]:
    return {
        "id": "m0", "initial": "a", "maxIterations": mi,
        "states": {
            "a": {
                "initial": "a",
                "invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m0.a.b"}},
                "states": {
                    "a": {},
                    "b": {"invoke": {"id": "i2", "src": "svc",
                                      "onDone": {"target": "#m0.a.a"}}},
                },
            }
        },
    }


async def plateau(read, stable: int = 4, timeout: float = 10.0) -> int:
    import time
    t0 = time.time()
    last = None
    count = 0
    while time.time() - t0 < timeout:
        await asyncio.sleep(0.02)
        cur = read()
        if cur == last:
            count += 1
            if count >= stable:
                return cur
        else:
            count = 0
        last = cur
    return last if last is not None else read()


def sync_calls(cfg_fn, mi: int) -> int:
    n = [0]

    def svc(i, c, e):
        n[0] += 1
        return 1

    SyncInterpreter(
        create_machine(json.loads(json.dumps(cfg_fn(mi))),
                        logic=MachineLogic(services={"svc": svc}))
    ).start()
    return n[0]


async def async_calls(cfg_fn, mi: int, kind: str) -> int:
    n = [0]

    def svc_def(i, c, e):
        n[0] += 1
        return 1

    async def svc_async(i, c, e):
        n[0] += 1
        return 1

    svc = svc_def if kind == "def" else svc_async
    i = await Interpreter(
        create_machine(json.loads(json.dumps(cfg_fn(mi))),
                        logic=MachineLogic(services={"svc": svc}))
    ).start()
    p = await plateau(lambda: n[0])
    await i.stop()
    return p


async def main() -> int:
    mismatches = []
    rows = []
    for name, fn in (("rollback_ondone", rollback_ondone), ("nested_invoke", nested_invoke)):
        for mi in range(1, 26):
            s = sync_calls(fn, mi)
            ad = await async_calls(fn, mi, "def")
            aa = await async_calls(fn, mi, "async def")
            row = {"shape": name, "limit": mi, "sync": s, "async_def": ad, "async_async": aa}
            rows.append(row)
            if not (s == ad == aa):
                mismatches.append(row)

    print(json.dumps(rows, indent=1))
    if mismatches:
        print("\nMISMATCHES:", json.dumps(mismatches, indent=1))
        return 1
    print("\nALL 50 (shape x limit) CELLS AGREE ACROSS ALL THREE LANES")
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 110.0))
    except asyncio.TimeoutError:
        print("watchdog fired")
        rc = 1
    sys.exit(rc)
