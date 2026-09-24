# -*- coding: utf-8 -*-
"""Root-cause instrumentation for CV-221-01: is `_processing` False when the
coroutine-service completion is enqueued, so `_raise_depth` is never charged?"""
import asyncio, json
from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
R = {}

BASE = {
    "id": "m", "initial": "idle", "actionErrorPolicy": "rollback",
    "guardErrorPolicy": "raise", "onUnhandled": "error",
    "strictTargets": True, "strict": True, "maxIterations": 5, "context": {},
    "states": {
        "idle": {"on": {"GO": "a"}},
        "a": {"invoke": {"id": "s", "src": "svc",
                         "onDone": {"target": "#m.c"},
                         "onError": {"target": "#m.c"}}},
        "c": {"entry": ["boom"]},
    },
}


async def cell(kind, watch=0.8):
    calls, acts, obs = [], [], []

    def boom(i, ctx, e, a):
        acts.append(1)
        raise RuntimeError("boom")

    if kind == "def":
        def svc(i, ctx, e):
            calls.append(1); return {"ok": True}
    else:
        async def svc(i, ctx, e):           # noqa: F811
            calls.append(1); return {"ok": True}

    m = create_machine(json.loads(json.dumps(BASE)), logic=MachineLogic(
        actions={"boom": boom}, services={"svc": svc}, strict=True))
    it = Interpreter(m, clock=SimulatedClock(), **CTL)

    # instrument the priority-lane enqueue that #166-#168 charges
    orig = it._deliver_priority

    def spy(event, *a, **kw):
        if len(obs) < 40 and str(getattr(event, "type", "")).startswith("done."):
            obs.append({"type": event.type, "processing": it._processing,
                        "raise_depth_before": it._raise_depth})
        return orig(event, *a, **kw)

    it._deliver_priority = spy
    await it.start(); await asyncio.sleep(0.03)
    await asyncio.wait_for(it.send("GO", wait=True), 10)
    await asyncio.sleep(watch)
    o = {"kind": kind, "svc": len(calls), "acts": len(acts),
         "completions_seen": len(obs),
         "charged": sum(1 for x in obs if x["processing"]),
         "free": sum(1 for x in obs if not x["processing"]),
         "sample": obs[:8],
         "final_raise_depth": it._raise_depth,
         "last_error": type(getattr(it, "last_error", None)).__name__
         if getattr(it, "last_error", None) else None,
         "ids": sorted(it.current_state_ids)}
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception as ex:
        o["stop_error"] = type(ex).__name__
    return o


async def main():
    R["def"] = await cell("def")
    R["async"] = await cell("async")

asyncio.run(main())
json.dump(R, open("results/q8_rootcause.json", "w", encoding="utf-8"),
          indent=2, default=str)
for k, v in R.items():
    print(k, "| svc", v["svc"], "| completions", v["completions_seen"],
          "| charged", v["charged"], "| free", v["free"],
          "| depth", v["final_raise_depth"], "| lastErr", v["last_error"])
    print("   sample:", json.dumps(v["sample"]))
