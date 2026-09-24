# -*- coding: utf-8 -*-
"""B11 INV-B11-d hazard: `degraded` has no STREAM_UNHEALTHY handler."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from g3_b11 import IMPL, GV

def mk():
    cfg = H.load("B11")
    st = H.Stub(cfg, guard_vals=GV, act_impl=IMPL)
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(tp)
    return it, st, tp

async def to_degraded(it, st):
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True); await quiesce(it)
    it.context["streams_healthy"] = {"trade": True, "kline": True}
    await it.send("STREAM_UNHEALTHY", s="trade", wait=True); await quiesce(it)


@scenario("B11-d-hz1", "INV-B11-d", "2nd unhealthy deferred; next STREAM_HEALTHY flaps via recording")
async def hz1():
    it, st, tp = mk()
    await to_degraded(it, st)
    await it.send("STREAM_UNHEALTHY", s="kline", wait=True); await quiesce(it)
    n_rec_before = st.trace.count("emit_recording_metric")
    await it.send("STREAM_HEALTHY", s="trade", wait=True); await quiesce(it)
    n_rec_after = st.trace.count("emit_recording_metric")
    end = ids(it)
    await it.stop()
    flapped = n_rec_after > n_rec_before
    return {"ok": not flapped,                       # FAIL is the finding
            "final_state": end,
            "emit_recording_metric": (n_rec_before, n_rec_after),
            "flapped_through_recording": flapped,
            "transitions": tp.transitions[-4:],
            "healthy": dict(it.context["streams_healthy"])}


@scenario("B11-d-hz2", "INV-B11-d", "2nd unhealthy never recorded if no further event arrives")
async def hz2():
    it, st, tp = mk()
    await to_degraded(it, st)
    await it.send("STREAM_UNHEALTHY", s="kline", wait=True)
    await quiesce(it, 12)                            # let it sit
    recorded = it.context["streams_healthy"].get("kline")
    deferred = it.deferred_count
    await it.stop()
    return {"ok": recorded is False,                 # expect kline marked unhealthy
            "kline_marked_unhealthy": recorded,
            "healthy_map": dict(it.context["streams_healthy"]),
            "deferred_still_held": deferred,
            "note": "deferred event is held indefinitely; context lags reality"}


@scenario("B11-d-hz3", "INV-B11-d", "stale map lets a single STREAM_HEALTHY declare all-healthy")
async def hz3():
    it, st, tp = mk()
    await to_degraded(it, st)
    await it.send("STREAM_UNHEALTHY", s="kline", wait=True); await quiesce(it)
    # now send only the RECOVERY for trade. kline is genuinely down.
    await it.send("STREAM_HEALTHY", s="trade", wait=True); await quiesce(it, 10)
    end = ids(it)
    await it.stop()
    return {"ok": end == ["recording.degraded"],
            "final": end, "healthy": dict(it.context["streams_healthy"]),
            "transitions": tp.transitions[-5:]}

if __name__ == "__main__":
    sys.exit(run_all("b11_hazard"))
