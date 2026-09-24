# -*- coding: utf-8 -*-
"""B11 RecordingSession: happy path + INV-B11-a..d."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock

CFG = lambda: H.load("B11")

def mk(guard_vals=None, svc=None, act_impl=None, **kw):
    cfg = CFG()
    st = H.Stub(cfg, guard_vals=guard_vals or {}, svc=svc or {}, act_impl=act_impl or {}, **kw)
    m = H.build(cfg, st)
    tp = H.TraceP()
    it = Interpreter(m, clock=SimulatedClock())
    it.use(tp)
    return it, st, tp

# real-ish action impls so context is meaningful
def _add(i, c, e, a): c["reasons"] = sorted(set(c["reasons"]) | {e.payload.get("reason")})
def _rm(i, c, e, a): c["reasons"] = [r for r in c["reasons"] if r != e.payload.get("reason")]
def _gap(i, c, e, a): c["gap_count_24h"] = c["gap_count_24h"] + 1
def _unh(i, c, e, a): c["streams_healthy"] = dict(c["streams_healthy"], **{e.payload["s"]: False})
def _h(i, c, e, a): c["streams_healthy"] = dict(c["streams_healthy"], **{e.payload["s"]: True})
IMPL = {"add_reason": _add, "remove_reason": _rm, "bump_gap_count": _gap,
        "mark_stream_unhealthy": _unh, "mark_stream_healthy": _h}
GV = {"reasons_remain": lambda c, e: bool([r for r in c["reasons"] if r != e.payload.get("reason")]),
      "all_streams_healthy": lambda c, e: all(dict(c["streams_healthy"], **{e.payload["s"]: True}).values()),
      "position_open_for_symbol": False}


@scenario("B11-happy", "happy", "idle -> starting -> recording via subscribe_streams")
async def s_happy():
    it, st, tp = mk(guard_vals=GV, act_impl=IMPL)
    await it.start()
    t = [ids(it)]
    await it.send("REASON_ADDED", reason="chart", wait=True)
    await quiesce(it); t.append(ids(it))
    return {"ok": t[-1] == ["recording.recording"] and "subscribe_streams" in st.svc_calls,
            "states": t, "svc": st.svc_calls, "ctx_reasons": it.context["reasons"],
            "entry_actions": [a for a in st.trace if a in ("cancel_linger", "emit_recording_metric")]}


@scenario("B11-a-1", "INV-B11-a", "last reason removed + position OPEN -> LINGER_DUE returns to recording")
async def s_pos_open():
    gv = dict(GV, position_open_for_symbol=True)
    it, st, tp = mk(guard_vals=gv, act_impl=IMPL)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True); await quiesce(it)
    await it.send("REASON_REMOVED", reason="chart", wait=True); await quiesce(it)
    lingering = ids(it)
    await it.send("LINGER_DUE", wait=True); await quiesce(it)
    after = ids(it)
    return {"ok": lingering == ["recording.lingering"] and after == ["recording.recording"]
                  and "unsubscribe_and_flush" not in st.svc_calls,
            "lingering": lingering, "after_linger_due": after, "svc": st.svc_calls}


@scenario("B11-a-2", "INV-B11-a", "no reasons + position CLOSED -> stopping -> stopped")
async def s_pos_closed():
    it, st, tp = mk(guard_vals=GV, act_impl=IMPL)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True); await quiesce(it)
    await it.send("REASON_REMOVED", reason="chart", wait=True); await quiesce(it)
    await it.send("LINGER_DUE", wait=True); await quiesce(it)
    return {"ok": ids(it) == ["recording.stopped"] and "unsubscribe_and_flush" in st.svc_calls,
            "final": ids(it), "svc": st.svc_calls}


@scenario("B11-a-3", "INV-B11-a", "two reasons: removing one keeps recording (reasons_remain)")
async def s_two_reasons():
    it, st, tp = mk(guard_vals=GV, act_impl=IMPL)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True); await quiesce(it)
    await it.send("REASON_ADDED", reason="position", wait=True); await quiesce(it)
    await it.send("REASON_REMOVED", reason="chart", wait=True); await quiesce(it)
    return {"ok": ids(it) == ["recording.recording"] and it.context["reasons"] == ["position"],
            "states": ids(it), "reasons": it.context["reasons"]}


@scenario("B11-b", "INV-B11-b", "reason re-added during lingering -> recording, NO stream restart")
async def s_relinger():
    it, st, tp = mk(guard_vals=GV, act_impl=IMPL)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True); await quiesce(it)
    n_sub_before = st.svc_calls.count("subscribe_streams")
    await it.send("REASON_REMOVED", reason="chart", wait=True); await quiesce(it)
    lin = ids(it)
    await it.send("REASON_ADDED", reason="chart", wait=True); await quiesce(it)
    n_sub_after = st.svc_calls.count("subscribe_streams")
    return {"ok": lin == ["recording.lingering"] and ids(it) == ["recording.recording"]
                  and n_sub_after == n_sub_before == 1
                  and "cancel_linger" in st.trace,
            "lingering": lin, "after": ids(it),
            "subscribe_calls": (n_sub_before, n_sub_after),
            "cancel_linger_count": st.trace.count("cancel_linger")}


@scenario("B11-c", "INV-B11-c", "every GAP_DETECTED counted + metricised, state unchanged")
async def s_gaps():
    it, st, tp = mk(guard_vals=GV, act_impl=IMPL)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True); await quiesce(it)
    for i in range(5):
        await it.send("GAP_DETECTED", seq=i, wait=True)
    await quiesce(it)
    return {"ok": it.context["gap_count_24h"] == 5
                  and st.trace.count("emit_gap_metric") == 5
                  and ids(it) == ["recording.recording"],
            "gap_count": it.context["gap_count_24h"],
            "metric_calls": st.trace.count("emit_gap_metric"), "states": ids(it)}


@scenario("B11-d", "INV-B11-d", "degraded on any unhealthy; exit only when ALL healthy")
async def s_degraded():
    it, st, tp = mk(guard_vals=GV, act_impl=IMPL)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True); await quiesce(it)
    it.context["streams_healthy"] = {"trade": True, "kline": True}
    await it.send("STREAM_UNHEALTHY", s="trade", wait=True); await quiesce(it)
    deg1 = ids(it)
    await it.send("STREAM_UNHEALTHY", s="kline", wait=True); await quiesce(it)
    deg2 = ids(it)                      # already degraded: unhandled under defer!
    await it.send("STREAM_HEALTHY", s="trade", wait=True); await quiesce(it)
    mid = ids(it)
    await it.send("STREAM_HEALTHY", s="kline", wait=True); await quiesce(it)
    end = ids(it)
    return {"ok": deg1 == ["recording.degraded"] and mid == ["recording.degraded"]
                  and end == ["recording.recording"],
            "after_first_unhealthy": deg1, "after_second_unhealthy": deg2,
            "after_first_healthy": mid, "after_all_healthy": end,
            "healthy_map": it.context["streams_healthy"],
            "deferred": it.deferred_count, "unhandled": tp.unhandled,
            "alert_count": st.trace.count("raise_degraded_alert")}


if __name__ == "__main__":
    sys.exit(run_all("b11"))
