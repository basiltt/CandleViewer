# -*- coding: utf-8 -*-
"""STANDALONE: rollback + invoke.onDone re-invoke storm on f28719c.

Shape (B11 `starting` --onDone--> `recording`, `recording` entry raises):
  actionErrorPolicy=rollback, so the entry failure rolls the machine back to
  `starting`, which re-arms the invoke, whose onDone re-enters `recording`...

Question: is the storm BOUNDED, and is it REPORTED to the operator?
#201 says both async lanes trip RunawayChainError. Check what the caller sees.

Exit 0 = storm bounded AND surfaced as a RunawayChainError the caller can see.
Exit 1 = bounded but silent (operator sees a clean return / unrelated error).
"""
from __future__ import annotations
import asyncio, json, os, sys, time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

STYLE = os.environ.get("CV_SVC_STYLE", "async")

CFG = {
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

calls = {"svc": 0, "boom": 0}


def make_logic():
    def boom(i, c, e, a):
        calls["boom"] += 1
        raise RuntimeError("entry failed")

    if STYLE == "def":
        def svc(i, c, e):
            calls["svc"] += 1
            return {"ok": True}
    else:
        async def svc(i, c, e):
            calls["svc"] += 1
            return {"ok": True}
    return MachineLogic(actions={"boom": boom}, services={"svc": svc}, strict=True)


async def main():
    m = create_machine(json.loads(json.dumps(CFG)), logic=make_logic(),
                       strict_targets=True)
    it = Interpreter(m, clock=SimulatedClock())
    await it.start()
    t0 = time.time()
    caller_saw, receipt = None, None
    try:
        receipt = await asyncio.wait_for(it.send("GO", wait=True), 25)
    except asyncio.TimeoutError:
        caller_saw = "TIMEOUT (hung)"
    except Exception as exc:
        caller_saw = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    for _ in range(6):
        await asyncio.sleep(0.03)
    el = round(time.time() - t0, 3)
    last = it.context.get("_last_error", None) or getattr(it, "last_error", None)
    out = {
        "style": STYLE, "elapsed_s": el, "svc_invocations": calls["svc"],
        "entry_failures": calls["boom"], "states": sorted(it.current_state_ids),
        "status": getattr(it, "status", "?"),
        "caller_saw_exception": caller_saw,
        "receipt": repr(receipt)[:300] if receipt is not None else None,
        "last_error": repr(last)[:200],
    }
    try:
        await asyncio.wait_for(it.stop(), 10)
    except asyncio.TimeoutError:
        out["stop_hung"] = True

    bounded = el < 20 and caller_saw != "TIMEOUT (hung)"
    blob = json.dumps(out, default=str)
    surfaced = "Runaway" in blob or "runaway" in blob
    out["bounded"] = bounded
    out["runaway_surfaced_anywhere"] = surfaced
    print(json.dumps(out, indent=1, default=str))
    return 0 if (bounded and surfaced) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
