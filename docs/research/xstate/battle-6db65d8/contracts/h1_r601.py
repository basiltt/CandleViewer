# -*- coding: utf-8 -*-
"""R6-01 class on 6db65d8: is the invoke.onDone->raising-entry->rollback->re-invoke
loop bounded, charged, and OBSERVABLE? Both service lanes, both engines."""
import asyncio, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter, SyncInterpreter
from xstate_statemachine.clock import SimulatedClock

def mk(b, style, raising, guard_vals=None, act_impl=None, cfgfix=None, maxit=None):
    cfg = H.load(b)
    if cfgfix: cfgfix(cfg)
    if maxit is not None: cfg["maxIterations"] = maxit
    st = H.Stub(cfg, guard_vals=guard_vals, act_impl=act_impl,
                raising=raising, svc_style=style)
    tp = H.TraceP(); m = H.build(cfg, st)
    return m, st, tp

def rep(it, st, tp, t0, svc, extra=None):
    d = {"svc_n": st.svc_calls.count(svc), "acts": len(st.trace),
         "states": ids(it), "status": getattr(it, "status", "?"),
         "elapsed_s": round(time.time()-t0, 3),
         "last_error": type(getattr(it, "last_error", None)).__name__
                       if getattr(it, "last_error", None) else None,
         "transitions": len(tp.transitions)}
    if extra: d.update(extra)
    return d

B11 = dict(b="B11", raising=("emit_recording_metric",), svc="subscribe_streams",
           ev=("REASON_ADDED", {"reason": "chart"}))
def _b13fix(cfg):
    cfg["context"]["kind"] = "public"; cfg["context"]["pending_topics"] = ["trade"]
B13 = dict(b="B13", raising=("emit_feed_healthy",), svc="subscribe_in_batches",
           ev=("CONNECT", {}), cfgfix=_b13fix,
           guard_vals={"is_private": False, "connection_budget_exhausted": False})

async def _async_case(spec, style, maxit=None):
    from g3_b11 import IMPL as I11, GV
    from g3_b13 import IMPL as I13
    imp = I11 if spec["b"] == "B11" else I13
    gv = spec.get("guard_vals") or GV
    t0 = time.time()
    m, st, tp = mk(spec["b"], style, spec["raising"], gv, imp,
                   spec.get("cfgfix"), maxit)
    it = Interpreter(m, clock=SimulatedClock()); it.use(tp)
    await it.start()
    ev, kw = spec["ev"]
    rcpt = None; to = False
    try:
        rcpt = await asyncio.wait_for(it.send(ev, wait=True, **kw), 20)
    except asyncio.TimeoutError: to = True
    await quiesce(it, 6)
    r = rep(it, st, tp, t0, spec["svc"], {
        "style": style, "maxIterations": maxit, "timed_out": to,
        "receipt_error": type(getattr(rcpt, "error", None)).__name__ if rcpt is not None and rcpt.error else None,
        "receipt_changed": getattr(rcpt, "changed", None),
        "receipt_denied": getattr(rcpt, "denied", None)})
    try: await asyncio.wait_for(it.stop(), 8)
    except asyncio.TimeoutError: r["stop_hung"] = True
    return r

def _sync_case(spec, maxit=None):
    from g3_b11 import IMPL as I11, GV
    from g3_b13 import IMPL as I13
    imp = I11 if spec["b"] == "B11" else I13
    gv = spec.get("guard_vals") or GV
    t0 = time.time()
    m, st, tp = mk(spec["b"], "def", spec["raising"], gv, imp,
                   spec.get("cfgfix"), maxit)
    it = SyncInterpreter(m); it.use(tp)
    err = None
    try:
        it.start(); ev, kw = spec["ev"]; it.send(ev, **kw)
    except Exception as exc:
        err = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    r = rep(it, st, tp, t0, spec["svc"],
            {"style": "def/sync", "maxIterations": maxit, "call_site": err})
    try: it.stop()
    except Exception: pass
    return r

BOUND = 60   # "bounded and observable" acceptance

def _judge(r):
    r["ok"] = (not r.get("timed_out")) and r["svc_n"] < BOUND and r["elapsed_s"] < 15
    r["observable"] = r["last_error"] in ("RunawayChainError",)
    return r

for _style in ("async", "def"):
    for _spec, _nm in ((B11, "B11"), (B13, "B13")):
        def _f(_spec=_spec, _style=_style):
            async def go(): return _judge(await _async_case(_spec, _style))
            return go
        scenario("R601-%s-%s" % (_nm, _style), "R6-01",
                 "%s onDone->raising entry->rollback (%s service, async engine)" % (_nm, _style))(_f())

for _spec, _nm in ((B11, "B11"), (B13, "B13")):
    def _g(_spec=_spec):
        def go(): return _judge(_sync_case(_spec))
        return go
    scenario("R601-%s-sync" % _nm, "R6-01",
             "%s same shape, SyncInterpreter with def service" % _nm)(_g())

# does maxIterations govern the bound, and is it the same on both lanes?
for _mi in (5, 25):
    for _style in ("async", "def"):
        def _h(_mi=_mi, _style=_style):
            async def go():
                r = await _async_case(B11, _style, maxit=_mi)
                r["ok"] = r["svc_n"] <= _mi + 2 and not r.get("timed_out")
                return r
            return go
        scenario("R601-mi%d-%s" % (_mi, _style), "R6-01",
                 "B11 loop bound tracks maxIterations=%d (%s)" % (_mi, _style))(_h())

if __name__ == "__main__":
    sys.exit(run_all("h1_r601"))
