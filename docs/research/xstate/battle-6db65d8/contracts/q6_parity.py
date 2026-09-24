# -*- coding: utf-8 -*-
"""Sync parity for the CV-221-01 shape (plain-def service so SyncInterpreter
supports it), and: is RunawayChainError EVER raised on this chain?"""
import asyncio, json, time
from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 SyncInterpreter, OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
R = {}

CFG = {
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


def mk(calls, acts, max_iter=None):
    c = json.loads(json.dumps(CFG))
    if max_iter is not None:
        c["maxIterations"] = max_iter

    def svc(i, ctx, e):          # plain def -> supported by SyncInterpreter
        calls.append(1)
        return {"ok": True}

    def boom(i, ctx, e, a):
        acts.append("boom")
        raise RuntimeError("boom")

    return create_machine(c, logic=MachineLogic(
        actions={"boom": boom}, services={"svc": svc}, strict=True))


def run_sync(max_iter=None):
    calls, acts = [], []
    m = mk(calls, acts, max_iter)
    it = SyncInterpreter(m, clock=SimulatedClock())
    o = {"engine": "sync", "declared_mi": getattr(m, "max_iterations", None)}
    t0 = time.perf_counter()
    try:
        it.start(); it.send("GO")
        o["ids"] = sorted(it.current_state_ids); o["status"] = it.status
    except Exception as ex:
        o["raised"] = f"{type(ex).__name__}: {str(ex)[:140]}"
    o["wall"] = round(time.perf_counter() - t0, 3)
    o["svc"] = len(calls); o["acts"] = len(acts)
    try: it.stop()
    except Exception: pass
    return o


async def run_async(max_iter=None, watch=1.0):
    calls, acts = [], []
    m = mk(calls, acts, max_iter)
    it = Interpreter(m, clock=SimulatedClock(), **CTL)
    await it.start(); await asyncio.sleep(0.03)
    try:
        r = await asyncio.wait_for(it.send("GO", wait=True), 10)
        rec = {"changed": r.changed,
               "error": type(r.error).__name__ if r.error else None}
    except asyncio.TimeoutError:
        rec = {"TIMEOUT": True}
    await asyncio.sleep(watch)
    o = {"engine": "async", "declared_mi": getattr(m, "max_iterations", None),
         "receipt": rec, "svc_per_s": len(calls), "acts": len(acts),
         "ids": sorted(it.current_state_ids), "status": it.status,
         "last_error": type(getattr(it, "last_error", None)).__name__
         if getattr(it, "last_error", None) else None}
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception as ex:
        o["stop_error"] = type(ex).__name__
    return o


async def main():
    for mi in (None, 5):
        R[f"sync_mi_{mi}"] = run_sync(mi)
        R[f"async_mi_{mi}"] = await run_async(mi)

asyncio.run(main())
json.dump(R, open("results/q6_parity.json", "w", encoding="utf-8"), indent=2,
          default=str)
for k, v in R.items():
    print(k, json.dumps(v, default=str))
