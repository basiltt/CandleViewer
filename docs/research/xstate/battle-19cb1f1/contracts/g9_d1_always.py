# -*- coding: utf-8 -*-
"""D1: `always` out of an invoking state -- the invoke must NOT arm (#204).

SCXML 6.1 statesToInvoke: a state entered and exited within one macrostep
never submits its service. Round 8 held for `async def` and FAILED for `def`
(CV-F28-01). Re-driven on 19cb1f1, BOTH kinds, BOTH engines.
"""
from __future__ import annotations
import asyncio, json
import cv19 as H
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine, OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

FWD = {
    "id": "fwd", "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "strictTargets": True, "strict": True,
    "initial": "idle", "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#fwd.transient"}}},
        # transient: invokes AND has an always out of it -> same macrostep exit
        "transient": {
            "invoke": {"id": "svc", "src": "fire",
                       "onDone": {"target": "#fwd.done_st"},
                       "onError": {"target": "#fwd.err"}},
            "always": {"target": "#fwd.moved"},
        },
        "moved": {}, "done_st": {}, "err": {},
    },
}

BACK = {
    "id": "bak", "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "strictTargets": True, "strict": True,
    "initial": "idle", "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#bak.armed"}}},
        # entry raises -> rollback unwinds the entry that armed the invoke
        "armed": {
            "entry": ["boom"],
            "invoke": {"id": "svc", "src": "fire",
                       "onDone": {"target": "#bak.done_st"},
                       "onError": {"target": "#bak.err"}},
        },
        "done_st": {}, "err": {},
    },
}


def logic(style, calls, raising=()):
    def boom(i, c, e, a):
        raise RuntimeError("boom")
    if style == "def":
        def fire(i, c, e):
            calls.append("fire")
            return {"ok": True}
    else:
        async def fire(i, c, e):
            calls.append("fire")
            await asyncio.sleep(0)
            return {"ok": True}
    fire.__name__ = "fire"
    return MachineLogic(actions={"boom": boom}, services={"fire": fire},
                        strict=True)


async def run_async(cfgd, style):
    calls = []
    m = create_machine(json.loads(json.dumps(cfgd)), logic=logic(style, calls),
                       strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.CvHooks(); i.use(p)
    await i.start(); await H.quiesce(i, 3)
    try:
        await asyncio.wait_for(i.send("GO"), 5)
    except Exception as e:
        calls.append("send:%r" % (e,))
    await H.quiesce(i, 6)
    st = H.ids(i)
    await i.stop()
    return calls, st


def run_sync(cfgd, style):
    calls = []
    m = create_machine(json.loads(json.dumps(cfgd)), logic=logic(style, calls),
                       strict_targets=True)
    i = SyncInterpreter(m, clock=SimulatedClock())
    p = H.CvHooks(); i.use(p)
    i.start()
    try:
        i.send("GO")
    except Exception as e:
        calls.append("send:%r" % (e,))
    st = H.ids(i)
    try:
        i.stop()
    except Exception:
        pass
    return calls, st


async def main():
    for kind in ("async", "def"):
        # --- roll FORWARD (always) ---
        c, s = await run_async(FWD, kind)
        H.rec("D1/rollforward/async-engine/%s" % kind, c.count("fire") == 0,
              "submissions=%d states=%s" % (c.count("fire"), s))
        c, s = run_sync(FWD, kind)
        H.rec("D1/rollforward/sync-engine/%s" % kind, c.count("fire") == 0,
              "submissions=%d states=%s" % (c.count("fire"), s))
        # --- roll BACK (rollback) ---
        c, s = await run_async(BACK, kind)
        H.rec("D1/rollback/async-engine/%s" % kind, c.count("fire") == 0,
              "submissions=%d states=%s" % (c.count("fire"), s))
        c, s = run_sync(BACK, kind)
        H.rec("D1/rollback/sync-engine/%s" % kind, c.count("fire") == 0,
              "submissions=%d states=%s" % (c.count("fire"), s))
    H.dump("g9_d1_always_invoke.json")


asyncio.run(main())
