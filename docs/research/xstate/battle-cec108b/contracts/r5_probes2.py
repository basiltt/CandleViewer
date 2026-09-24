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



# ------------------------------------------------- #153 Receipt.denied ----
@scenario("R5-153a", "#153", "B15 MARK_UPDATE with both guards false -> denied, not undeclared")
async def s_153a():
    cfg, st, m, tp = mk("B15", guard_vals={"mark_crossed_liq_price": False,
                                           "below_maintenance_margin": False})
    it = ainterp(m); it.use(tp)
    await it.start()
    r = await it.send("MARK_UPDATE", mark="100", wait=True)
    await quiesce(it)
    out = {"receipt": str(r), "denied": getattr(r, "denied", "ABSENT"),
           "error": str(getattr(r, "error", None)), "deferred": getattr(r, "deferred", None),
           "unhandled_hook": tp.unhandled, "states": ids(it), "status": it.status}
    await it.stop()
    out["ok"] = (out["denied"] is True and out["states"] == ["paper_account.active"]
                 and it.status != "error")
    out["note"] = ("declared-but-guard-denied is distinguishable from undeclared; "
                   "under onUnhandled=defer it must NOT be parked")
    return out


@scenario("R5-153b", "#153", "B15 truly undeclared event -> defer, denied False")
async def s_153b():
    cfg, st, m, tp = mk("B15")
    it = ainterp(m); it.use(tp)
    await it.start()
    r = await it.send("NO_SUCH_EVENT", wait=True)
    await quiesce(it)
    out = {"receipt": str(r), "denied": getattr(r, "denied", "ABSENT"),
           "deferred": getattr(r, "deferred", None), "unhandled_hook": tp.unhandled,
           "deferred_count": it.deferred_count, "states": ids(it)}
    await it.stop()
    out["ok"] = out["denied"] is False and out["deferred"] is True
    return out


@scenario("R5-153c", "#153", "B11 REASON_REMOVED: guard-denied vs fallback candidate")
async def s_153c():
    """recording.REASON_REMOVED has a guarded candidate AND an unguarded fallback,
    so it can never be fully denied. B11 degraded.STREAM_UNHEALTHY is undeclared.
    Contrast the two receipts -- this is what distinguishes OUR-B11-01."""
    cfg, st, m, tp = mk("B11", guard_vals={"reasons_remain": False},
                        act_impl={"mark_stream_unhealthy": lambda i, c, e, a: None})
    it = ainterp(m); it.use(tp)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True)
    await quiesce(it, 12)
    r1 = await it.send("STREAM_UNHEALTHY", s="trade", wait=True)   # declared in recording
    await quiesce(it)
    r2 = await it.send("STREAM_UNHEALTHY", s="kline", wait=True)   # NOT declared in degraded
    await quiesce(it)
    out = {"in_recording_receipt": str(r1), "in_degraded_receipt": str(r2),
           "degraded_denied": getattr(r2, "denied", "ABSENT"),
           "degraded_deferred": getattr(r2, "deferred", None),
           "deferred_count": it.deferred_count, "states": ids(it)}
    await it.stop()
    out["ok"] = (out["degraded_denied"] is False and out["degraded_deferred"] is True
                 and out["deferred_count"] == 1)
    out["note"] = ("denied=False + deferred=True is the caller-visible signature of "
                   "OUR-B11-01: the contract simply has no handler. #153 makes this "
                   "detectable at the call site, which it was not at 3ed3099.")
    return out


# ---------------------------------------------- #152 guardErrorPolicy ----
@scenario("R5-152", "#152", "B13 guard raise on invoke.onDone candidate -> fallback taken")
async def s_152():
    """connecting.onDone = [ {is_private -> authenticating}, {-> subscribing} ].
    is_private RAISES. Pre-#152 the whole selection pass aborted and the
    open_socket completion was lost. Now the unguarded fallback must be taken."""
    cfg, st, m, tp = mk("B13", guard_raise=("is_private",))
    it = ainterp(m); it.use(tp)
    await it.start()
    await it.send("CONNECT", wait=True)
    await quiesce(it, 20)
    out = {"states": ids(it), "status": it.status,
           "svc_calls": st.svc_calls, "guard_calls": st.guard_calls,
           "last_transition_ok": getattr(it, "last_transition_ok", "ABSENT"),
           "last_error": str(getattr(it, "last_error", None)),
           "transitions": tp.transitions}
    await it.stop()
    out["ok"] = out["states"] == ["ws_conn.subscribing"] or out["states"] == ["ws_conn.live"]
    out["note"] = ("engine-driven (done.invoke) guard raise: exception recorded on "
                   "last_error/last_transition_ok, completion NOT lost")
    return out


@scenario("R5-152b", "#152", "B15 caller-driven guard raise -> delivered to the async receipt")
async def s_152b():
    cfg, st, m, tp = mk("B15", guard_raise=("mark_crossed_liq_price",),
                        guard_vals={"below_maintenance_margin": True})
    it = ainterp(m); it.use(tp)
    await it.start()
    raised = None
    try:
        r = await it.send("MARK_UPDATE", mark="1", wait=True)
    except Exception as exc:
        raised = "%s: %s" % (type(exc).__name__, exc)
        r = None
    await quiesce(it)
    out = {"raised_at_call_site": raised, "receipt": str(r),
           "receipt_error": str(getattr(r, "error", None)) if r else None,
           "states": ids(it), "status": it.status,
           "guard_calls": st.guard_calls}
    await it.stop()
    out["ok"] = raised is not None or (r is not None and getattr(r, "error", None) is not None)
    out["note"] = ("first candidate's guard raised; the SECOND candidate "
                   "(below_maintenance_margin=True) is still evaluated per #152")
    return out


if __name__ == "__main__":
    sys.exit(run_all("r5_153_152"))
