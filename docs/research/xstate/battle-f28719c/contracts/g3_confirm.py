# -*- coding: utf-8 -*-
"""Confirm the OUR-CONTRACT findings are real, not harness artefacts."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from g3_b11 import IMPL, GV

H._REG.clear()


@scenario("CONF-1", "OUR-B11", "degraded genuinely has no STREAM_UNHEALTHY handler (read the JSON)")
def conf1():
    cfg = H.load("B11")
    deg = cfg["states"]["degraded"]["on"]
    rec = cfg["states"]["recording"]["on"]
    return {"ok": "STREAM_UNHEALTHY" not in deg and "STREAM_UNHEALTHY" in rec,
            "degraded_handles": sorted(deg),
            "recording_handles": sorted(rec),
            "finding": ("a 2nd stream failing while already degraded has no "
                        "handler; under onUnhandled=defer it is parked")}


@scenario("CONF-2", "OUR-B11", "the parked event fires later and flaps recording<->degraded")
async def conf2():
    cfg = H.load("B11")
    st = H.Stub(cfg, guard_vals=GV, act_impl=IMPL)
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock())
    it.use(tp)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True)
    await quiesce(it)
    it.context["streams_healthy"] = {"trade": True, "kline": True}
    await it.send("STREAM_UNHEALTHY", s="trade", wait=True)
    await quiesce(it)
    await it.send("STREAM_UNHEALTHY", s="kline", wait=True)   # parked
    await quiesce(it)
    parked = it.deferred_count
    await it.send("STREAM_HEALTHY", s="trade", wait=True)
    await quiesce(it)
    trans = [t for t in tp.transitions if "STREAM" in t]
    live_entries = st.trace.count("emit_recording_metric")
    r = {"ok": live_entries == 1,
         "deferred_after_2nd_failure": parked,
         "transitions": trans,
         "emit_recording_metric_count": live_entries,
         "finding": ("machine re-entered `recording` (emit_recording_metric "
                     "fired a 2nd time) while a stream was still down, then "
                     "immediately fell back to degraded")}
    await it.stop()
    return r


@scenario("CONF-3", "OUR-B14", "B14 buffer bound is prose-only: no maxBuffer anywhere in the JSON")
def conf3():
    raw = json.dumps(H.load("B14"))
    hits = [k for k in ("max", "bound", "limit", "cap") if k in raw.lower()]
    sp = H.load("B14")["states"]["snapshot_pending"]["on"]["DELTA"]
    return {"ok": not hits,
            "bound_keywords_in_json": hits,
            "DELTA_in_snapshot_pending": sp,
            "finding": ("INV-B14-d requires a bounded buffer (C-2.18); the "
                        "contract expresses no bound -- it is delegated "
                        "entirely to the buffer_delta implementation")}


@scenario("CONF-4", "LIB", "onUnhandled=error: fatal stop is invisible to the caller (all 3 machines)")
async def conf4():
    out = {}
    for b, boot, bad in (("B13", [("CONNECT", {})], ("CONNECT", {})),
                         ("B14", [("SUBSCRIBE", {}), ("SNAPSHOT", {"seq": 1})],
                          ("SUBSCRIBE", {}))):
        cfg = H.load(b)
        gv = {"is_private": False, "connection_budget_exhausted": False}
        st = H.Stub(cfg, guard_vals=gv)
        it = Interpreter(H.build(cfg, st), clock=SimulatedClock())
        await it.start()
        for ev, p in boot:
            await it.send(ev, wait=True, **p)
            await quiesce(it)
        rc = await it.send(bad[0], wait=True, **bad[1])
        await quiesce(it)
        out[b] = {"onUnhandled": cfg["onUnhandled"],
                  "receipt_error": repr(rc.error), "receipt_changed": rc.changed,
                  "receipt_deferred": rc.deferred,
                  "status": it.status, "running": it.is_running,
                  "last_error": repr(it.last_error)}
        await it.stop()
    silent = all(v["receipt_error"] == "None" and v["last_error"] == "None"
                 and v["status"] == "error" for v in out.values())
    return {"ok": not silent, "per_machine": out,
            "finding": ("every onUnhandled='error' machine can be killed by one "
                        "stray event with no error visible to the sender")}


if __name__ == "__main__":
    sys.exit(run_all("confirm"))
