# -*- coding: utf-8 -*-
"""Verify #208 on main @ 19cb1f1: a receipt from `send(wait=True)` is never
success-shaped (`ok`/`error=None`) over an empty configuration
(`current_state_ids == []`), and the receipt path refuses `ok` when the
step ended with an illegal configuration.

Acceptance criteria (from gh issue #208 body):
  1. On the nested-final + `always` + `after` chart that originally
     reproduced #197/#208, no `send(wait=True)` receipt across many laps
     ever reports ok=True/error=None while current_state_ids == [].
  2. If the post-step configuration is illegal, the receipt reports an
     error, not `ok`.
  3. SyncInterpreter is synchronous by construction -- send() cannot return
     while genuinely mid-step -- so its lane should never see an empty
     configuration at all (a stronger, not weaker, property).

Matrix: {def, async def} service x {Interpreter, SyncInterpreter}.

Exit 0 = no violation observed in any cell. Exit 1 = a violation found.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, List

logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine

CFG = {
    "id": "m197",
    "initial": "a",
    "maxIterations": 38,
    "after": {"17": {"target": "#m197.a.c"}},
    "states": {
        "a": {
            "initial": "a",
            "always": {"target": "#m197.a.a.a"},
            "states": {
                "a": {
                    "initial": "a",
                    "invoke": {"id": "inv", "src": "svc"},
                    "states": {"a": {"type": "final"}},
                },
                "c": {},
            },
        }
    },
}


def mk(kind: str):
    def svc_def(i, c, e):
        return {"ok": 1}

    async def svc_async(i, c, e):
        return {"ok": 1}

    svc = svc_def if kind == "def" else svc_async
    cfg = json.loads(json.dumps(CFG))
    return create_machine(cfg, logic=MachineLogic(services={"svc": svc}))


async def check_async(kind: str, laps: int = 60) -> dict:
    violations: List[dict] = []
    i = await Interpreter(mk(kind)).start()
    for lap in range(laps):
        r = await i.send("PING", wait=True)
        ok = getattr(r, "error", "MISSING") is None
        empty = len(i.current_state_ids) == 0
        if ok and empty:
            violations.append({"lap": lap, "ok": ok, "empty": empty})
        await asyncio.sleep(0.005)
    await i.stop()
    return {"engine": "Interpreter", "kind": kind, "laps": laps, "violations": violations}


def check_sync(kind: str, laps: int = 60) -> dict:
    # SyncInterpreter requires sync services.
    if kind != "def":
        return {"engine": "SyncInterpreter", "kind": kind, "skipped": "sync-only"}
    violations: List[dict] = []

    def svc(i, c, e):
        return {"ok": 1}

    s = SyncInterpreter(create_machine(json.loads(json.dumps(CFG)),
                                        logic=MachineLogic(services={"svc": svc})))
    s.start()
    for lap in range(laps):
        r = s.send("PING", wait=True)
        ok = getattr(r, "error", "MISSING") is None
        empty = len(s.current_state_ids) == 0
        if empty:
            # Sync should NEVER see empty, ok or not -- stronger property.
            violations.append({"lap": lap, "ok": ok, "empty": empty})
    s.stop()
    return {"engine": "SyncInterpreter", "kind": kind, "laps": laps, "violations": violations}


async def check_illegal_configuration() -> dict:
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"EV": {"actions": ["wreck"]}}}, "b": {}},
    }

    def wreck(i: Any, c: Any, e: Any, a: Any) -> None:
        i._active_state_nodes.clear()

    i = await Interpreter(
        create_machine(cfg, logic=MachineLogic(actions={"wreck": wreck}))
    ).start()
    r = await i.send("EV", wait=True)
    ok_receipt = getattr(r, "error", "MISSING") is None
    ok_flag = i.last_transition_ok
    await i.stop()
    err, ok_flag = r.error, ok_flag
    return {
        "error_is_not_none": err is not None,
        "last_transition_ok_false": ok_flag is False,
        "receipt_not_ok": not ok_receipt,
    }


async def main() -> int:
    rows = []
    failures = []
    for kind in ("def", "async def"):
        r = await check_async(kind)
        rows.append(r)
        if r["violations"]:
            failures.append(r)

    for kind in ("def", "async def"):
        r = check_sync(kind)
        rows.append(r)
        if r.get("violations"):
            failures.append(r)

    illegal = await check_illegal_configuration()
    rows.append({"illegal_configuration_check": illegal})
    if not (illegal["error_is_not_none"] and illegal["last_transition_ok_false"]
            and illegal["receipt_not_ok"]):
        failures.append({"illegal_configuration_check": illegal})

    print(json.dumps(rows, indent=1, default=str))
    if failures:
        print("\nFAILURES:", json.dumps(failures, indent=1, default=str))
        return 1
    print("\nALL CELLS PASS")
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 100.0))
    except asyncio.TimeoutError:
        print("watchdog fired")
        rc = 1
    sys.exit(rc)
