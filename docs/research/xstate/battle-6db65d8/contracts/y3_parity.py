# -*- coding: utf-8 -*-
"""Same rollback+onDone machine, async vs sync engine: lap count + receipt."""
from __future__ import annotations
import asyncio, json, logging
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine)
from xstate_statemachine.clock import SimulatedClock

logging.disable(logging.CRITICAL)

BASE = {
    "id": "m", "initial": "idle", "maxIterations": 20,
    "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "strictTargets": True, "strict": True, "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#m.arm"}}},
        "arm": {"invoke": {"id": "s", "src": "svc",
                           "onDone": {"target": "#m.done", "actions": ["boom"]},
                           "onError": {"target": "#m.err"}}},
        "done": {"type": "final"}, "err": {"type": "final"},
    },
}


def mk(style, calls):
    def boom(i, c, e, a):
        raise RuntimeError("boom")

    async def asvc(i, c, e):
        calls.append(1); return {"ok": True}

    def dsvc(i, c, e):
        calls.append(1); return {"ok": True}

    return create_machine(json.loads(json.dumps(BASE)), logic=MachineLogic(
        actions={"boom": boom},
        services={"svc": asvc if style == "async" else dsvc}, strict=True))


def desc(r):
    return {"type": type(r).__name__,
            "ok": getattr(r, "ok", "<no attr>"),
            "error": repr(getattr(r, "error", "<no attr>")),
            "deferred": getattr(r, "deferred", "<no attr>")}


async def main():
    out = {}
    for style in ("async", "def"):
        calls = []
        i = Interpreter(mk(style, calls), clock=SimulatedClock())
        await i.start()
        r = await asyncio.wait_for(i.send("GO"), 30)
        await asyncio.sleep(3)
        out["async-engine/" + style] = {
            "svc_calls": len(calls), "receipt": desc(r),
            "states": sorted(i.current_state_ids), "status": i.status,
            "interp_error": repr(i.error),
           "last_error": repr(i.last_error)}
        await asyncio.wait_for(i.stop(), 5)

    calls = []
    i = SyncInterpreter(mk("def", calls), clock=SimulatedClock())
    i.start()
    exc = None
    try:
        r = i.send("GO"); rd = desc(r)
    except Exception as e:
        rd = None; exc = repr(e)
    out["sync-engine/def"] = {"svc_calls": len(calls), "receipt": rd,
                              "raised": exc,
                              "states": sorted(i.current_state_ids),
                              "status": i.status, "interp_error": repr(i.error),
           "last_error": repr(i.last_error)}
    i.stop()
    for k, v in out.items():
        print(k, json.dumps(v), flush=True)
    json.dump(out, open("y3_parity.json", "w"), indent=1)


asyncio.run(main())
