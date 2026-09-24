# -*- coding: utf-8 -*-
"""always -> invoked child -> onError -> always ... (B5 repricing shape).

Must terminate, be bounded, be observable, and reach the SAME lap count on
async def and def services, and on the async vs sync engine.
"""
from __future__ import annotations
import asyncio, json, logging
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine)
from xstate_statemachine.clock import SimulatedClock

logging.disable(logging.CRITICAL)

CFG = {
    "id": "ice", "initial": "pending", "maxIterations": 30,
    "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "strictTargets": True, "strict": True,
    "context": {"n": 0},
    "states": {
        "pending": {"always": [{"target": "#ice.slice"}]},
        "slice": {"entry": ["bump"],
                  "invoke": {"id": "s", "src": "submit",
                             "onDone": {"target": "#ice.working"},
                             "onError": {"target": "#ice.reprice"}}},
        # always straight back into the invoking state: the cycle under test
        "reprice": {"always": [{"target": "#ice.cool", "guard": "cooled"},
                               {"target": "#ice.slice"}]},
        "working": {"type": "final"},
        "cool": {"type": "final"},
    },
}


def mk(style, calls, cool_at):
    def bump(i, c, e, a):
        c["n"] = c["n"] + 1

    def cooled(c, e):
        return c["n"] >= cool_at

    async def asvc(i, c, e):
        calls.append(1); raise RuntimeError("post-only")

    def dsvc(i, c, e):
        calls.append(1); raise RuntimeError("post-only")

    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic(
        actions={"bump": bump}, guards={"cooled": cooled},
        services={"submit": asvc if style == "async" else dsvc}, strict=True))


async def run_async(style, cool_at):
    calls = []
    i = Interpreter(mk(style, calls, cool_at), clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(3.0)
    n1 = len(calls)
    await asyncio.sleep(2.0)
    out = {"engine": "async", "style": style, "cool_at": cool_at,
           "svc_calls": len(calls), "bounded": len(calls) == n1,
           "entries": i.context["n"], "states": sorted(i.current_state_ids),
           "status": i.status, "interp_error": repr(i.error),
           "last_error": repr(i.last_error)}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


def run_sync(cool_at):
    calls = []
    i = SyncInterpreter(mk("def", calls, cool_at), clock=SimulatedClock())
    exc = None
    try:
        i.start()
    except Exception as e:
        exc = repr(e)
    out = {"engine": "sync", "style": "def", "cool_at": cool_at,
           "svc_calls": len(calls), "entries": i.context["n"],
           "states": sorted(i.current_state_ids), "status": i.status,
           "raised": exc, "interp_error": repr(i.error),
           "last_error": repr(i.last_error)}
    try:
        i.stop()
    except Exception:
        pass
    return out


async def main():
    res = []
    for cool_at in (5, 10**9):   # terminating case, then unbounded cycle
        for style in ("async", "def"):
            r = await run_async(style, cool_at)
            res.append(r); print(json.dumps(r), flush=True)
        r = run_sync(cool_at)
        res.append(r); print(json.dumps(r), flush=True)
    json.dump(res, open("y6_always.json", "w"), indent=1)


asyncio.run(main())
