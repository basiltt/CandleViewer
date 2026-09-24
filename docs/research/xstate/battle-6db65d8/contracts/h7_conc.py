# -*- coding: utf-8 -*-
"""Refinement: the def-lane cancel window is closed to the SEQUENTIAL caller
(send(wait=True) only returns after onDone). Does a CONCURRENT canceller get in?"""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from g3_b12 import IMPL

DUR = 0.6

async def run(style, concurrent):
    cfg = H.load("B12")
    started = threading.Event()
    if style == "def":
        def seek(i, c, e):
            started.set(); time.sleep(DUR); return {"cursor": 4242, "gaps": []}
    else:
        async def seek(i, c, e):
            started.set(); await asyncio.sleep(DUR); return {"cursor": 4242, "gaps": []}
    st = H.Stub(cfg, guard_vals={"loop_enabled": False},
                svc={"seek_and_prime": seek, "emit_one_step": {"cursor": 1}},
                act_impl=IMPL, svc_style=style)
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(H.TraceP())
    await it.start()
    obs = []
    if concurrent:
        prep = asyncio.ensure_future(it.send("PREPARE", wait=True))
        for _ in range(60):
            if started.is_set(): break
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.05)
        obs.append(("mid_service", ids(it)))
        canc = await asyncio.wait_for(it.send("CANCEL", wait=True), 5)
        obs.append(("after_cancel", ids(it)))
        await asyncio.wait_for(prep, 5)
    else:
        await it.send("PREPARE", wait=True)
        obs.append(("after_prepare_returned", ids(it)))
        canc = await it.send("CANCEL", wait=True)
        obs.append(("after_cancel", ids(it)))
    await quiesce(it, 4); await asyncio.sleep(DUR + 0.2)
    r = {"style": style, "concurrent_canceller": concurrent, "obs": obs,
         "final": ids(it), "cursor": it.context["cursor"],
         "cancel_receipt_changed": canc.changed,
         "cancel_receipt_error": type(canc.error).__name__ if canc.error else None}
    await asyncio.wait_for(it.stop(), 8)
    r["seek_result_landed"] = r["cursor"] == 4242
    r["ok"] = not r["seek_result_landed"]
    return r

for _s in ("async", "def"):
    for _c in (True, False):
        def _f(_s=_s, _c=_c):
            async def go(): return await run(_s, _c)
            return go
        scenario("CONC-%s-%s" % (_s, "task" if _c else "seq"), "INV-B12-a",
                 "%s service, %s canceller: cancelled seek must not land"
                 % (_s, "concurrent" if _c else "sequential"))(_f())

if __name__ == "__main__":
    sys.exit(run_all("h7_conc"))
