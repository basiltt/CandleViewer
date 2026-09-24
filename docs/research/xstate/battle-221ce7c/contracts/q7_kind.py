# -*- coding: utf-8 -*-
"""Discriminator: same rollback+onDone re-arm shape, only the service's
DEFINITION KIND changes (plain def vs async def). Is the chain budget charged?
"""
import asyncio, json
from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
R = {}

BASE = {
    "id": "m", "initial": "idle", "actionErrorPolicy": "rollback",
    "guardErrorPolicy": "raise", "onUnhandled": "error",
    "strictTargets": True, "strict": True, "context": {},
    "states": {
        "idle": {"on": {"GO": "a"}},
        "a": {"invoke": {"id": "s", "src": "svc",
                         "onDone": {"target": "#m.c"},
                         "onError": {"target": "#m.c"}}},
        "c": {"entry": ["boom"]},
    },
}


async def cell(kind, mi, watch=1.0):
    calls, acts = [], []
    c = json.loads(json.dumps(BASE))
    c["maxIterations"] = mi

    def boom(i, ctx, e, a):
        acts.append(1)
        raise RuntimeError("boom")

    if kind == "def":
        def svc(i, ctx, e):
            calls.append(1); return {"ok": True}
    else:
        async def svc(i, ctx, e):           # noqa: F811
            calls.append(1); return {"ok": True}

    m = create_machine(c, logic=MachineLogic(
        actions={"boom": boom}, services={"svc": svc}, strict=True))
    it = Interpreter(m, clock=SimulatedClock(), **CTL)
    await it.start(); await asyncio.sleep(0.03)
    await asyncio.wait_for(it.send("GO", wait=True), 10)
    await asyncio.sleep(watch)
    n1 = len(calls)
    await asyncio.sleep(watch)
    o = {"kind": kind, "maxIterations": mi, "svc_at_1s": n1,
         "svc_at_2s": len(calls), "grew_after_1s": len(calls) > n1,
         "acts": len(acts), "status": it.status,
         "ids": sorted(it.current_state_ids),
         "last_error": type(getattr(it, "last_error", None)).__name__
         if getattr(it, "last_error", None) else None}
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception as ex:
        o["stop_error"] = type(ex).__name__
    return o


async def main():
    for kind in ("def", "async"):
        for mi in (5, 50):
            R[f"{kind}_mi{mi}"] = await cell(kind, mi)

asyncio.run(main())
json.dump(R, open("results/q7_kind.json", "w", encoding="utf-8"), indent=2,
          default=str)
for k, v in R.items():
    print(k, "| svc@1s", v["svc_at_1s"], "| svc@2s", v["svc_at_2s"],
          "| still growing:", v["grew_after_1s"], "| lastErr", v["last_error"])
