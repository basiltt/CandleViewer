# -*- coding: utf-8 -*-
"""Minimal R6-03 / #167 shape, independent of the contract catalogue.

    idle --GO--> work            (work invokes `s`)
    work.invoke.onDone --> done  with action `bad` which raises
    actionErrorPolicy: rollback  -> back to `work` -> invoke re-arms -> ...

CHANGELOG (Unreleased, #167) claims: "A completion the machine produced while
processing (a rollback that re-armed an invoke, #167) ... is charged to the
chain budget", with a trip observable as RunawayChainError on last_error.
"""
from __future__ import annotations
import asyncio, json, time

from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 OverflowPolicy, create_machine)
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "m",
    "actionErrorPolicy": "rollback",
    "initial": "idle",
    "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#m.work"}}},
        "work": {
            "invoke": {
                "id": "s", "src": "svc",
                "onDone": {"target": "#m.done", "actions": ["bad"]},
            }
        },
        "done": {"type": "final"},
    },
}

calls = {"svc": 0, "bad": 0}


def logic(sync=False):
    def bad(interp, ctx, evt, ad):
        calls["bad"] += 1
        raise RuntimeError("boom")

    async def svc_a(interp, ctx, evt):
        calls["svc"] += 1
        return {"ok": True}

    def svc_s(interp, ctx, evt):
        calls["svc"] += 1
        return {"ok": True}

    return MachineLogic(actions={"bad": bad},
                        services={"svc": svc_s if sync else svc_a},
                        strict=True)


async def async_probe(hold=2.0):
    calls.update(svc=0, bad=0)
    m = create_machine(json.loads(json.dumps(CFG)), logic=logic())
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(i.send("GO"), 10)
        sent = "returned in %.3fs" % (time.perf_counter() - t0)
    except asyncio.TimeoutError:
        sent = "HANG (no receipt in 10s)"
    a = calls["svc"]
    await asyncio.sleep(hold)
    b = calls["svc"]
    out = {"engine": "async", "send": sent, "states": sorted(i.current_state_ids),
           "status": i.status,
           "error": None if i.error is None else repr(i.error),
           "last_error": repr(getattr(i, "last_error", "<absent>")),
           "svc_at_send": a, "svc_after_%.0fs" % hold: b,
           "rate_per_s": round((b - a) / hold, 1)}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


def sync_probe():
    calls.update(svc=0, bad=0)
    m = create_machine(json.loads(json.dumps(CFG)), logic=logic(sync=True))
    i = SyncInterpreter(m, clock=SimulatedClock())
    i.start()
    t0 = time.perf_counter()
    try:
        i.send("GO")
        sent = "returned in %.3fs" % (time.perf_counter() - t0)
        exc = None
    except Exception as e:
        sent = "raised in %.3fs" % (time.perf_counter() - t0)
        exc = repr(e)
    return {"engine": "sync", "send": sent, "exc": exc,
            "states": sorted(i.current_state_ids), "status": i.status,
            "error": None if i.error is None else repr(i.error),
            "last_error": repr(getattr(i, "last_error", "<absent>")),
            "svc": calls["svc"]}


async def main():
    res = [await async_probe(1.0), await async_probe(3.0), sync_probe()]
    for r in res:
        print(json.dumps(r), flush=True)
    json.dump(res, open("out_r603_min.json", "w"), indent=1, default=str)
    a, b = res[0], res[1]
    print("\nUNBOUNDED_IN_TIME:", b["svc_after_3s"] > a["svc_after_1s"] * 1.5)


asyncio.run(main())
