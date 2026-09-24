# -*- coding: utf-8 -*-
"""Why CANCEL-def fails: is a plain `def` service run INLINE on the event loop
(blocking, therefore uncancellable), or off-thread? Measure both."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from g3_b12 import IMPL

DUR = 0.6

async def run(style):
    cfg = H.load("B12")
    loop_tid = threading.get_ident()
    seen = {}
    if style == "def":
        def seek(i, c, e):
            seen["tid"] = threading.get_ident(); time.sleep(DUR)
            return {"cursor": 7, "gaps": []}
    else:
        async def seek(i, c, e):
            seen["tid"] = threading.get_ident(); await asyncio.sleep(DUR)
            return {"cursor": 7, "gaps": []}
    st = H.Stub(cfg, guard_vals={"loop_enabled": False},
                svc={"seek_and_prime": seek, "emit_one_step": {"cursor": 1}},
                act_impl=IMPL, svc_style=style)
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(H.TraceP())
    await it.start()
    # a heartbeat coroutine: how many ticks does the loop manage while the
    # service runs? A blocked loop ticks ~0.
    ticks = {"n": 0}
    async def hb():
        while True:
            await asyncio.sleep(0.02); ticks["n"] += 1
    t = asyncio.create_task(hb())
    t0 = time.time()
    await it.send("PREPARE", wait=True)
    send_returned_after = round(time.time() - t0, 3)
    state_at_return = ids(it)
    await asyncio.sleep(0.05)
    n_mid = ticks["n"]
    await asyncio.sleep(DUR + 0.3)
    t.cancel()
    r = {"style": style, "service_duration_s": DUR,
         "send_wait_returned_after_s": send_returned_after,
         "state_when_send_returned": state_at_return,
         "loop_ticks_during_service": n_mid,
         "service_thread_is_loop_thread": seen.get("tid") == loop_tid,
         "cursor": it.context["cursor"]}
    await asyncio.wait_for(it.stop(), 8)
    # expectation: the loop keeps ticking and the machine is observably in
    # `buffering` while the service runs -> a cancel window exists.
    r["cancel_window_exists"] = (state_at_return == ["replay.buffering"])
    r["loop_responsive"] = n_mid >= 1
    r["ok"] = r["cancel_window_exists"] and r["loop_responsive"]
    return r

for _s in ("async", "def"):
    def _f(_s=_s):
        async def go(): return await run(_s)
        return go
    scenario("BLOCK-%s" % _s, "svc-lane",
             "a %s service: does the loop stay live and is there a cancel window?" % _s)(_f())

if __name__ == "__main__":
    sys.exit(run_all("h6_block"))
