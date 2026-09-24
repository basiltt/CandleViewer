# -*- coding: utf-8 -*-
"""R9-07 (STANDALONE): rollback + invoke.onDone storm under the DEFAULT
maxIterations (1000) self-terminates below the limit and WEDGES the machine
in the transient invoking state, with no runaway ever reported.

Contract shape: `starting` --onDone--> `recording`, `recording` entry raises,
`actionErrorPolicy=rollback`. What #201 promises: both lanes trip
RunawayChainError. What actually happens at the DEFAULT limit: the storm
stops on its own after a non-deterministic number of laps well under 1000,
`last_error` is the entry action's own RuntimeError (not RunawayChainError),
and the interpreter is left `status=running` parked in `starting` with no
service in flight and no `onDone` that can ever arrive. At an explicit low
maxIterations (10/50) RunawayChainError IS raised -- so the diagnostic exists
but is unreachable at the default.

Runs both `def` and `async def` service spellings. Watchdog: 60 s total.
Exit 1 = at least one lane wedged silently at the default limit (defect).
Exit 0 = no lane wedged (defect fixed).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

TRANSIENT = "r7.starting"

BASE = {
    "id": "r7",
    "actionErrorPolicy": "rollback",
    "onUnhandled": "defer",
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "strict": True,
    "initial": "idle",
    "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#r7.starting"}}},
        "starting": {
            "invoke": {
                "id": "sub",
                "src": "svc",
                "onDone": {"target": "#r7.recording"},
                "onError": {"target": "#r7.err"},
            }
        },
        "recording": {"entry": ["boom"]},
        "err": {},
    },
}


def make(style: str, counter: dict, max_iter=None):
    def boom(i, c, e, a):
        counter["boom"] += 1
        raise RuntimeError("entry failed")

    if style == "def":
        def svc(i, c, e):
            counter["svc"] += 1
            return {"ok": True}
    else:
        async def svc(i, c, e):
            counter["svc"] += 1
            return {"ok": True}

    cfg = json.loads(json.dumps(BASE))
    if max_iter is not None:
        cfg["maxIterations"] = max_iter
    logic = MachineLogic(actions={"boom": boom}, services={"svc": svc}, strict=True)
    return create_machine(cfg, logic=logic, strict_targets=True)


async def run(style: str, max_iter) -> dict:
    counter = {"svc": 0, "boom": 0}
    m = make(style, counter, max_iter)
    it = Interpreter(m, clock=SimulatedClock())
    await it.start()
    t0 = time.time()
    try:
        await asyncio.wait_for(it.send("GO", wait=True), 25)
    except Exception:
        pass
    for _ in range(15):
        await asyncio.sleep(0.03)
    le = getattr(it, "last_error", None)
    rec = {
        "style": style,
        "maxIterations": max_iter if max_iter is not None else "DEFAULT",
        "svc_invocations": counter["svc"],
        "elapsed_s": round(time.time() - t0, 3),
        "final_configuration": sorted(it.current_state_ids),
        "status": str(getattr(it, "status", "?")),
        "last_error_type": type(le).__name__ if le is not None else None,
        "runaway_reported": type(le).__name__ == "RunawayChainError",
    }
    for _ in range(5):
        await asyncio.sleep(0.03)
    rec["configuration_2s_later"] = sorted(it.current_state_ids)
    rec["wedged_in_transient"] = (
        rec["final_configuration"] == [TRANSIENT]
        and rec["configuration_2s_later"] == [TRANSIENT]
        and "running" in rec["status"].lower()
    )
    try:
        await asyncio.wait_for(it.stop(), 10)
    except asyncio.TimeoutError:
        rec["stop_hung"] = True
    return rec


async def main() -> int:
    rows = []
    for style in ("def", "async"):
        for mi in (None, 10, 50):
            rows.append(await run(style, mi))
    print(json.dumps(rows, indent=1, default=str))
    bad = [r for r in rows if r["maxIterations"] == "DEFAULT"
           and r["wedged_in_transient"] and not r["runaway_reported"]]
    print("\nVERDICT:", "SILENT WEDGE at default maxIterations" if bad else "ok",
          [r["style"] for r in bad])
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 55.0))
    except asyncio.TimeoutError:
        print("watchdog fired")
        rc = 1
    sys.exit(rc)
