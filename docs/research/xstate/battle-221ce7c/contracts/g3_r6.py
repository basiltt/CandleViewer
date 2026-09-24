# -*- coding: utf-8 -*-
"""Round-6 fix classes exercised on the real contract machines B11-B15.

R6-01 class: actionErrorPolicy=rollback + a RAISING action on `invoke.onDone`
             -> must terminate, bounded, observable (was: unbounded re-invoke).
R6-03 class: `always` into a state that invokes -> settle budget per macrostep.
"""
import asyncio, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter, SyncInterpreter
from xstate_statemachine.clock import SimulatedClock

WD = 25.0  # per-scenario watchdog


def mk(b, raising=(), guard_vals=None, svc=None, act_impl=None, sync=False):
    cfg = H.load(b)
    st = H.Stub(cfg, guard_vals=guard_vals, svc=svc, act_impl=act_impl,
                raising=raising)
    tp = H.TraceP()
    m = H.build(cfg, st)
    it = SyncInterpreter(m) if sync else Interpreter(m, clock=SimulatedClock())
    it.use(tp)
    return it, st, tp


def report(it, st, tp, t0, extra=None):
    d = {"states": ids(it), "status": getattr(it, "status", "?"),
         "elapsed_s": round(time.time() - t0, 3),
         "svc_calls": len(st.svc_calls),
         "svc_hist": {n: st.svc_calls.count(n) for n in set(st.svc_calls)},
         "act_calls": len(st.trace),
         "last_error": type(getattr(it, "last_error", None)).__name__
                       if getattr(it, "last_error", None) else None,
         "transitions": len(tp.transitions)}
    if extra:
        d.update(extra)
    return d


# ===================================================================
# R6-01 class: rollback + raising entry action reached via invoke.onDone
# ===================================================================

@scenario("R6-B11-01", "R6-01", "B11 starting--onDone-->recording, recording entry RAISES (rollback)")
async def r6_b11_01():
    from g3_b11 import IMPL, GV
    t0 = time.time()
    it, st, tp = mk("B11", raising=("emit_recording_metric",),
                    guard_vals=GV, act_impl=IMPL)
    await it.start()
    try:
        await asyncio.wait_for(it.send("REASON_ADDED", reason="chart", wait=True), WD)
        timed_out = False
    except asyncio.TimeoutError:
        timed_out = True
    await quiesce(it, 6)
    r = report(it, st, tp, t0, {"send_timed_out": timed_out})
    try:
        await asyncio.wait_for(it.stop(), 10)
    except asyncio.TimeoutError:
        r["stop_hung"] = True
    n = r["svc_hist"].get("subscribe_streams", 0)
    r["ok"] = (not timed_out) and n < 60 and r["elapsed_s"] < 20
    r["verdict"] = ("bounded, terminates" if r["ok"]
                    else "UNBOUNDED/HUNG re-invoke loop")
    return r


@scenario("R6-B11-01s", "R6-01", "B11 same shape on SyncInterpreter (parity)")
def r6_b11_01_sync():
    from g3_b11 import IMPL, GV
    t0 = time.time()
    it, st, tp = mk("B11", raising=("emit_recording_metric",),
                    guard_vals=GV, act_impl=IMPL, sync=True)
    err = None
    try:
        it.start()
        it.send("REASON_ADDED", reason="chart")
    except Exception as exc:
        err = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    r = report(it, st, tp, t0, {"raised_at_call_site": err})
    try:
        it.stop()
    except Exception:
        pass
    r["ok"] = r["elapsed_s"] < 20
    return r


@scenario("R6-B13-01", "R6-01", "B13 subscribing--onDone-->live, live entry RAISES (rollback)")
async def r6_b13_01():
    from g3_b13 import IMPL
    t0 = time.time()
    cfg = H.load("B13")
    cfg["context"]["kind"] = "public"
    cfg["context"]["pending_topics"] = ["trade"]
    st = H.Stub(cfg, guard_vals={"is_private": False,
                                 "connection_budget_exhausted": False},
                act_impl=IMPL, raising=("emit_feed_healthy",))
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(tp)
    await it.start()
    try:
        await asyncio.wait_for(it.send("CONNECT", wait=True), WD)
        timed_out = False
    except asyncio.TimeoutError:
        timed_out = True
    await quiesce(it, 6)
    r = report(it, st, tp, t0, {"send_timed_out": timed_out})
    try:
        await asyncio.wait_for(it.stop(), 10)
    except asyncio.TimeoutError:
        r["stop_hung"] = True
    n = r["svc_hist"].get("subscribe_in_batches", 0)
    r["ok"] = (not timed_out) and n < 60 and r["elapsed_s"] < 20
    r["verdict"] = ("bounded" if r["ok"] else "UNBOUNDED/HUNG")
    return r


# ===================================================================
# R6-03 class: `always` out of a state whose entry raises (rollback)
# ===================================================================

def _b14_impl():
    def buf(i, c, e, a): c["buffered_deltas"] = c["buffered_deltas"] + [e.payload.get("seq")]
    def clr(i, c, e, a): c["buffered_deltas"] = []
    def bump(i, c, e, a): c["resync_count"] = c["resync_count"] + 1
    return {"buffer_delta": buf, "clear_buffer": clr, "bump_resync_count": bump}


@scenario("R6-B14-03", "R6-03", "B14 desynced entry RAISES then always->snapshot_pending (rollback)")
async def r6_b14_03():
    t0 = time.time()
    it, st, tp = mk("B14", raising=("emit_resync_metric",), act_impl=_b14_impl())
    await it.start()
    await it.send("SUBSCRIBE", symbol="BTC", wait=True)
    await it.send("SNAPSHOT", seq=10, wait=True)
    try:
        await asyncio.wait_for(it.send("SEQUENCE_GAP", wait=True), WD)
        timed_out = False
    except asyncio.TimeoutError:
        timed_out = True
    await quiesce(it, 8)
    r = report(it, st, tp, t0, {"send_timed_out": timed_out,
                                "resync_count": it.context.get("resync_count")})
    try:
        await asyncio.wait_for(it.stop(), 10)
    except asyncio.TimeoutError:
        r["stop_hung"] = True
    r["ok"] = (not timed_out) and r["act_calls"] < 500 and r["elapsed_s"] < 20
    r["verdict"] = "bounded" if r["ok"] else "UNBOUNDED/HUNG always-loop"
    return r


@scenario("R6-B15-03", "R6-03", "B15 liquidating entry RAISES then always->liquidated (rollback)")
async def r6_b15_03():
    t0 = time.time()
    it, st, tp = mk("B15", raising=("write_liquidation_journal",),
                    guard_vals={"mark_crossed_liq_price": True,
                                "below_maintenance_margin": False,
                                "above_maintenance_margin": True})
    await it.start()
    try:
        await asyncio.wait_for(it.send("MARK_UPDATE", px="1", wait=True), WD)
        timed_out = False
    except asyncio.TimeoutError:
        timed_out = True
    await quiesce(it, 8)
    r = report(it, st, tp, t0, {"send_timed_out": timed_out})
    try:
        await asyncio.wait_for(it.stop(), 10)
    except asyncio.TimeoutError:
        r["stop_hung"] = True
    r["ok"] = (not timed_out) and r["act_calls"] < 500 and r["elapsed_s"] < 20
    r["verdict"] = "bounded" if r["ok"] else "UNBOUNDED/HUNG always-loop"
    return r


@scenario("R6-B14-03s", "R6-03", "B14 always-shape on SyncInterpreter (parity)")
def r6_b14_03_sync():
    t0 = time.time()
    it, st, tp = mk("B14", raising=("emit_resync_metric",),
                    act_impl=_b14_impl(), sync=True)
    err = None
    try:
        it.start()
        it.send("SUBSCRIBE", symbol="BTC")
        it.send("SNAPSHOT", seq=10)
        it.send("SEQUENCE_GAP")
    except Exception as exc:
        err = "%s: %s" % (type(exc).__name__, str(exc)[:140])
    r = report(it, st, tp, t0, {"raised_at_call_site": err})
    try:
        it.stop()
    except Exception:
        pass
    r["ok"] = r["elapsed_s"] < 20 and r["act_calls"] < 500
    return r


@scenario("R6-B15-03s", "R6-03", "B15 always-shape on SyncInterpreter (parity)")
def r6_b15_03_sync():
    t0 = time.time()
    it, st, tp = mk("B15", raising=("write_liquidation_journal",),
                    guard_vals={"mark_crossed_liq_price": True,
                                "below_maintenance_margin": False,
                                "above_maintenance_margin": True}, sync=True)
    err = None
    try:
        it.start()
        it.send("MARK_UPDATE", px="1")
    except Exception as exc:
        err = "%s: %s" % (type(exc).__name__, str(exc)[:140])
    r = report(it, st, tp, t0, {"raised_at_call_site": err})
    try:
        it.stop()
    except Exception:
        pass
    r["ok"] = r["elapsed_s"] < 20 and r["act_calls"] < 500
    return r


if __name__ == "__main__":
    sys.exit(run_all("r6"))
