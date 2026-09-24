# -*- coding: utf-8 -*-
"""Is the R6-01 trip OBSERVABLE on 6db65d8? (bounded is established; this asks
whether anything in the public surface says the machine shed work.)"""
import asyncio, json, logging, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from g3_b11 import IMPL, GV

class Cap(logging.Handler):
    def __init__(self): super().__init__(); self.recs=[]
    def emit(self, r):
        if r.levelno >= logging.WARNING: self.recs.append((r.levelname, r.getMessage()[:110]))

async def run(style, limit=None):
    cfg = H.load("B11")
    if limit is not None: cfg["maxIterations"] = limit
    st = H.Stub(cfg, guard_vals=GV, act_impl=IMPL,
                raising=("emit_recording_metric",), svc_style=style)
    tp = H.TraceP(); cap = Cap()
    lg = logging.getLogger("xstate_statemachine"); lg.addHandler(cap); lg.setLevel(logging.WARNING)
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(tp)
    t0 = time.time()
    await it.start()
    rc = await asyncio.wait_for(it.send("REASON_ADDED", reason="chart", wait=True), 20)
    await quiesce(it, 6)
    r = {"style": style, "maxIterations": limit,
         "svc_n": st.svc_calls.count("subscribe_streams"),
         "elapsed_s": round(time.time()-t0, 3), "states": ids(it),
         "status": it.status,
         "last_error": type(it.last_error).__name__ if it.last_error else None,
         "receipt_error": type(rc.error).__name__ if rc.error else None,
         "receipt_changed": rc.changed, "receipt_denied": rc.denied,
         "plugin_dropped": tp.dropped[:6], "n_dropped": len(tp.dropped),
         "warn_log": cap.recs[:4], "n_warn": len(cap.recs)}
    await asyncio.wait_for(it.stop(), 8)
    lg.removeHandler(cap)
    r["channels"] = [k for k, v in (
        ("last_error=RunawayChainError", r["last_error"] == "RunawayChainError"),
        ("receipt.error", r["receipt_error"] is not None),
        ("on_event_dropped", r["n_dropped"] > 0),
        ("WARNING/ERROR log", r["n_warn"] > 0)) if v]
    r["ok"] = bool(r["channels"])
    return r

for _s in ("async", "def"):
    def _f(_s=_s):
        async def go(): return await run(_s)
        return go
    scenario("OBS-%s" % _s, "R6-01-obs",
             "B11 rollback re-invoke trip: any observable channel? (%s)" % _s)(_f())

if __name__ == "__main__":
    sys.exit(run_all("h2_obs"))
