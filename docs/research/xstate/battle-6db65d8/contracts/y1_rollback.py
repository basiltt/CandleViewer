# -*- coding: utf-8 -*-
"""Minimal: actionErrorPolicy rollback + invoke.onDone re-arms the invoke.

Is the self-generated cycle bounded (RunawayChainError / maxIterations),
and is the lap count the same for `def` and `async def` services?
"""
from __future__ import annotations
import asyncio, json, sys, time
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "m", "initial": "idle",
    "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "strictTargets": True, "strict": True,
    "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#m.arm"}}},
        "arm": {"invoke": {"id": "s", "src": "svc",
                           "onDone": {"target": "#m.done", "actions": ["boom"]},
                           "onError": {"target": "#m.err"}}},
        "done": {"type": "final"}, "err": {"type": "final"},
    },
}


def logic(style, calls, maxi=None):
    def boom(i, c, e, a):
        raise RuntimeError("boom")

    async def asvc(i, c, e):
        calls.append(1)
        return {"ok": True}

    def dsvc(i, c, e):
        calls.append(1)
        return {"ok": True}

    return MachineLogic(actions={"boom": boom},
                        services={"svc": asvc if style == "async" else dsvc},
                        strict=True)


async def run(style, maxi, window=6.0):
    calls = []
    cfg = dict(CFG)
    if maxi is not None:
        cfg = json.loads(json.dumps(CFG)); cfg["maxIterations"] = maxi
    m = create_machine(cfg, logic=logic(style, calls))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    t0 = time.perf_counter()
    try:
        r = await asyncio.wait_for(i.send("GO"), window)
        rec = "ok=%s err=%r" % (getattr(r, "ok", "?"), getattr(r, "error", None))
    except asyncio.TimeoutError:
        rec = "SEND-TIMEOUT"
    await asyncio.sleep(1.0)
    n1 = len(calls)
    await asyncio.sleep(1.0)
    n2 = len(calls)
    out = {"style": style, "maxIterations": maxi, "send": rec,
           "svc_calls_at_send": n1, "svc_calls_1s_later": n2,
           "still_spinning": n2 > n1, "states": sorted(i.current_state_ids),
           "status": i.status, "last_error": repr(i.error),
           "sec": round(time.perf_counter() - t0, 2)}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


def run_sync(style, maxi):
    calls = []
    cfg = json.loads(json.dumps(CFG))
    if maxi is not None:
        cfg["maxIterations"] = maxi
    m = create_machine(cfg, logic=logic(style, calls))
    i = SyncInterpreter(m, clock=SimulatedClock())
    i.start()
    try:
        i.send("GO")
        e = None
    except Exception as ex:
        e = repr(ex)
    out = {"engine": "sync", "style": style, "maxIterations": maxi,
           "svc_calls": len(calls), "states": sorted(i.current_state_ids),
           "status": i.status, "raised": e, "last_error": repr(i.error)}
    i.stop()
    return out


async def main():
    res = []
    for maxi in (None, 20):
        for style in ("async", "def"):
            res.append(await run(style, maxi))
            print(json.dumps(res[-1]), flush=True)
    for maxi in (None, 20):
        r = run_sync("def", maxi)
        res.append(r); print(json.dumps(r), flush=True)
    json.dump(res, open("y1_rollback.json", "w"), indent=1)


asyncio.run(main())
