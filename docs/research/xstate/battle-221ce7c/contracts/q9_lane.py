# -*- coding: utf-8 -*-
"""Confirm the mechanism: a coroutine service publishes its completion with
the PUBLIC `send()` (inbox lane), so `from_inbox` is True and the macrostep
resets the settle budget on every lap -- the reset the plain-def path
(`_deliver_priority`) never gets."""
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


async def cell(kind, watch=0.6):
    calls, acts, lanes, iters = [], [], [], []

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

    o_send, o_prio = it.send, it._deliver_priority

    def prio(event, *a, **kw):
        if len(lanes) < 60 and str(getattr(event, "type", "")).startswith("done."):
            lanes.append("priority")
        return o_prio(event, *a, **kw)

    def snd(event, *a, **kw):
        t = getattr(event, "type", event)
        if len(lanes) < 60 and str(t).startswith("done."):
            lanes.append("inbox_send")
        return o_send(event, *a, **kw)

    it._deliver_priority = prio
    it.send = snd
    await it.start(); await asyncio.sleep(0.03)

    async def sampler():
        for _ in range(40):
            iters.append(it._settle_iterations)
            await asyncio.sleep(watch / 40)

    task = asyncio.create_task(sampler())
    await asyncio.wait_for(it.send("GO", wait=True), 10)
    await task
    o = {"kind": kind, "svc": len(calls), "acts": len(acts),
         "lanes": {x: lanes.count(x) for x in set(lanes)},
         "lane_first8": lanes[:8],
         "settle_iterations_samples": iters[:12],
         "settle_iterations_max": max(iters) if iters else None,
         "raise_depth": it._raise_depth,
         "last_error": type(getattr(it, "last_error", None)).__name__
         if getattr(it, "last_error", None) else None}
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception as ex:
        o["stop_error"] = type(ex).__name__
    return o


async def main():
    R["def"] = await cell("def")
    R["async"] = await cell("async")

asyncio.run(main())
json.dump(R, open("results/q9_lane.json", "w", encoding="utf-8"), indent=2,
          default=str)
for k, v in R.items():
    print(k, "| svc", v["svc"], "| lanes", v["lanes"], v["lane_first8"],
          "| settle_max", v["settle_iterations_max"],
          "| depth", v["raise_depth"], "| lastErr", v["last_error"])
