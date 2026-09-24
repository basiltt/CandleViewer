# -*- coding: utf-8 -*-
"""Round-5 fix probes mapped onto the B11-B15 contract machines (cec108b)."""
import asyncio, copy, json, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
import xstate_statemachine as X
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock


def mk(b, guard_vals=None, svc=None, act_impl=None, cfg_mut=None, **kw):
    cfg = H.load(b)
    if cfg_mut:
        cfg_mut(cfg)
    st = H.Stub(cfg, guard_vals=guard_vals or {}, svc=svc or {},
                act_impl=act_impl or {}, **kw)
    m = H.build(cfg, st)
    tp = H.TraceP()
    return cfg, st, m, tp


def ainterp(m, **kw):
    return Interpreter(m, clock=SimulatedClock(), **kw)


# --------------------------------------------------------------- #149 ----
@scenario("R5-149a", "#149", "B11 plain-def service does not block the loop (service_executor)")
async def s_149a():
    """subscribe_streams as a BLOCKING plain def. CV-C32 mandated async def.
    If #149 works, the loop keeps turning while it runs."""
    cfg = H.load("B11")
    st = H.Stub(cfg)
    def blocking_subscribe(interp, ctx, evt):
        time.sleep(0.6)
        return {"ok": True}
    logic = st.logic()
    logic.services["subscribe_streams"] = blocking_subscribe   # plain def
    m = X.create_machine(copy.deepcopy(cfg), logic=logic)
    it = ainterp(m)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True)
    # loop liveness: can an independent coroutine make progress while the
    # blocking service runs?
    ticks = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.5:
        await asyncio.sleep(0.01)
        ticks += 1
    mid = ids(it)
    await quiesce(it, 30)
    fin = ids(it)
    await it.stop()
    return {"ok": ticks > 20 and fin == ["recording.recording"],
            "loop_ticks_during_blocking_service": ticks,
            "state_while_blocking": mid, "final": fin,
            "verdict": "loop kept turning -> CV-C32 (all services async def) is no "
                       "longer required for loop liveness" if ticks > 20 else
                       "loop was blocked -> CV-C32 still required"}


@scenario("R5-149b", "#149", "B11 plain-def service: event sent DURING it is still served")
async def s_149b():
    cfg = H.load("B11")
    st = H.Stub(cfg, act_impl={"add_reason": lambda i, c, e, a:
                               c.__setitem__("reasons", sorted(set(c["reasons"]) | {e.payload["reason"]}))})
    def blocking_subscribe(interp, ctx, evt):
        time.sleep(0.5)
        return {"ok": True}
    logic = st.logic()
    logic.services["subscribe_streams"] = blocking_subscribe
    m = X.create_machine(copy.deepcopy(cfg), logic=logic)
    it = ainterp(m)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True)
    await asyncio.sleep(0.1)          # mid-service
    t0 = time.monotonic()
    r = await it.send("REASON_ADDED", reason="alerts", wait=True)
    dt = time.monotonic() - t0
    await quiesce(it, 30)
    fin = ids(it)
    reasons = list(it.context["reasons"])
    await it.stop()
    return {"ok": dt < 0.4 and reasons == ["alerts", "chart"],
            "send_latency_s": round(dt, 3), "receipt": str(r),
            "reasons": reasons, "final": fin,
            "note": "latency < service duration => the entering macrostep awaits the "
                    "executor without blocking the inbox"}


if __name__ == "__main__":
    sys.exit(run_all("r5"))
