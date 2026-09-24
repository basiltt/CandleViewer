# -*- coding: utf-8 -*-
"""CV-6DB-01 -- a plain `def` service's result lands after the invoking state
was exited: it is never cancelled, and its onDone writes context in a state
that no longer invokes it. The identical machine with an `async def` service
is correct. Exits 1 on the bug.

Run: python cv_6db_01_def_invoke_not_cancelled.py
"""
import asyncio, sys, threading, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "m", "initial": "idle", "context": {"cursor": 0},
    "states": {
        "idle": {"on": {"GO": "busy"}},
        "busy": {
            "invoke": {"id": "w", "src": "work",
                       "onDone": {"target": "done", "actions": ["land"]}},
            "on": {"CANCEL": "cancelled"},
        },
        "done": {}, "cancelled": {},
    },
}

def build(style):
    started = threading.Event()
    if style == "def":
        def work(i, c, e):
            started.set(); time.sleep(0.6); return {"cursor": 4242}
    else:
        async def work(i, c, e):
            started.set(); await asyncio.sleep(0.6); return {"cursor": 4242}
    def land(i, c, e, a): c["cursor"] = e.data["cursor"]
    m = create_machine(CFG, logic=MachineLogic(actions={"land": land},
                                               services={"work": work}))
    return m, started

async def case(style):
    m, started = build(style)
    it = Interpreter(m)
    await it.start()
    go = asyncio.ensure_future(it.send("GO", wait=True))
    for _ in range(200):
        if started.is_set(): break
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.05)
    mid = sorted(it.current_state_ids)
    await asyncio.wait_for(it.send("CANCEL", wait=True), 5)
    after = sorted(it.current_state_ids)
    try: await asyncio.wait_for(go, 5)
    except Exception: pass
    await asyncio.sleep(1.0)              # abandoned service finishes here
    r = {"style": style, "mid_service": mid, "after_cancel": after,
         "final": sorted(it.current_state_ids), "cursor": it.context["cursor"]}
    await asyncio.wait_for(it.stop(), 5)
    return r

async def main():
    bad = 0
    for style in ("async", "def"):
        r = await case(style)
        ok = r["cursor"] == 0 and r["final"] == ["m.cancelled"]
        print(("PASS " if ok else "FAIL "), r)
        bad += not ok
    if bad:
        print("\nBUG: the `def` service was not cancelled; its onDone landed "
              "cursor=4242 in a state that had already been exited.")
    return 1 if bad else 0

sys.exit(asyncio.run(main()))
