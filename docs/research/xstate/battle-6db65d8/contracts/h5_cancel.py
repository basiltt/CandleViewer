# -*- coding: utf-8 -*-
"""INV-B12-a in the `def` lane: a CANCELled invoke's result must never land.
The 221ce7c suite only ever expressed this with an `async def` service."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from g3_b12 import IMPL

async def run(style):
    cfg = H.load("B12")
    started = threading.Event()
    if style == "def":
        def seek(i, c, e):
            started.set(); time.sleep(0.5); return {"cursor": 4242, "gaps": []}
    else:
        async def seek(i, c, e):
            started.set(); await asyncio.sleep(0.5); return {"cursor": 4242, "gaps": []}
    st = H.Stub(cfg, guard_vals={"loop_enabled": False},
                svc={"seek_and_prime": seek, "emit_one_step": {"cursor": 1}},
                act_impl=IMPL, svc_style=style)
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(tp)
    await it.start()
    await it.send("PREPARE", wait=True)
    for _ in range(40):
        if started.is_set(): break
        await asyncio.sleep(0.01)
    buffering = ids(it)
    await it.send("CANCEL", wait=True); await quiesce(it)
    right_after, cur_after = ids(it), it.context["cursor"]
    await asyncio.sleep(1.0)                      # abandoned service finishes here
    late, cur_late = ids(it), it.context["cursor"]
    status = it.status
    await asyncio.wait_for(it.stop(), 8)
    return {"style": style, "svc_started": started.is_set(),
            "buffering": buffering, "after_cancel": right_after,
            "after_service_finished": late, "cursor": (cur_after, cur_late),
            "status": status,
            "ok": buffering == ["replay.buffering"]
                  and right_after == ["replay.paused"]
                  and late == ["replay.paused"] and cur_late == 0,
            "note": "cursor 4242 or a state change late == cancelled seek still landed"}

for _s in ("async", "def"):
    def _f(_s=_s):
        async def go(): return await run(_s)
        return go
    scenario("CANCEL-%s" % _s, "INV-B12-a",
             "CANCEL during buffering: abandoned seek must not land (%s service)" % _s)(_f())

if __name__ == "__main__":
    sys.exit(run_all("h5_cancel"))
