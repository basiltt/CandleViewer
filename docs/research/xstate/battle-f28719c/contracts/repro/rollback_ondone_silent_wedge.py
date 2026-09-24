# -*- coding: utf-8 -*-
"""STANDALONE: rollback + invoke.onDone under the DEFAULT maxIterations (1000)
self-terminates below the limit and WEDGES the machine in the transient
invoking state, with no runaway ever reported.

Contract shape: B11 `starting` --onDone--> `recording`, `recording` entry
raises, actionErrorPolicy=rollback.

What the operator is promised (#201): both async lanes trip RunawayChainError.
What actually happens on the DEFAULT limit: the storm stops on its own after a
NON-DETERMINISTIC number of laps (well under 1000), `last_error` is the action's
own RuntimeError -- NOT RunawayChainError -- and the machine is parked in
`starting` with no service running and no `onDone` that will ever arrive.
`starting` is a transient state: the session is wedged, and nothing says so.

With an explicit low maxIterations (10/50) the RunawayChainError IS raised.
So the diagnostic exists but is unreachable at the default.

Exit 0 = storm reported as a runaway, or machine not left in the transient state.
Exit 1 = silent self-termination wedged in the transient invoking state.
"""
from __future__ import annotations
import asyncio, json, os, sys, time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

STYLE = os.environ.get("CV_SVC_STYLE", "async")
TRANSIENT = "r6.starting"

BASE = {
    "id": "r6", "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "initial": "idle", "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#r6.starting"}}},
        "starting": {"invoke": {"id": "sub", "src": "svc",
                                "onDone": {"target": "#r6.recording"},
                                "onError": {"target": "#r6.err"}}},
        "recording": {"entry": ["boom"]},
        "err": {},
    },
}


def make(counter, max_iter=None):
    def boom(i, c, e, a):
        counter["boom"] += 1
        raise RuntimeError("entry failed")

    if STYLE == "def":
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
    logic = MachineLogic(actions={"boom": boom}, services={"svc": svc},
                         strict=True)
    return create_machine(cfg, logic=logic, strict_targets=True)


async def run(max_iter):
    counter = {"svc": 0, "boom": 0}
    m = make(counter, max_iter)
    it = Interpreter(m, clock=SimulatedClock())
    await it.start()
    t0 = time.time()
    try:
        await asyncio.wait_for(it.send("GO", wait=True), 25)
    except Exception:
        pass
    # let everything settle well past the storm
    for _ in range(15):
        await asyncio.sleep(0.03)
    le = getattr(it, "last_error", None)
    rec = {
        "style": STYLE,
        "maxIterations": max_iter if max_iter is not None else "DEFAULT",
        "limit_on_machine": getattr(m, "max_iterations", None),
        "svc_invocations": counter["svc"],
        "elapsed_s": round(time.time() - t0, 3),
        "final_configuration": sorted(it.current_state_ids),
        "status": str(getattr(it, "status", "?")),
        "last_error_type": type(le).__name__ if le is not None else None,
        "runaway_reported": type(le).__name__ == "RunawayChainError",
    }
    # is it really wedged? nothing further should move it
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


async def main():
    rows = []
    for mi in (None, 10, 50, 200):
        rows.append(await run(mi))
    print(json.dumps(rows, indent=1, default=str))
    default_row = rows[0]
    bad = default_row["wedged_in_transient"] and not default_row["runaway_reported"]
    print("\nVERDICT:", "SILENT WEDGE at default maxIterations" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
