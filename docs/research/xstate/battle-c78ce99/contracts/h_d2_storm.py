# -*- coding: utf-8 -*-
"""D2: rollback + invoke.onDone storm on the REAL B11/B13 contract shapes.

Round 8 (CV-F28-02): storm self-terminated below the default limit, last_error
was the action's own RuntimeError, machine parked in the transient invoking
state, silent. Round 9 claims: trips at maxIterations+3 on BOTH lanes, with
RunawayChainError.stranded + on_invocation_stranded + ERROR log.

B11: starting --(sub onDone)--> recording, whose entry raises -> rollback
     returns to starting, which re-arms `sub`. Verbatim contract shape.
B13: subscribing --(sub onDone)--> live, entry raises. Same shape.
"""
from __future__ import annotations
import asyncio, json
import cv78 as H
from xstate_statemachine import Interpreter, SyncInterpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import RunawayChainError

CASES = {
    # bid: (entry-raising state, kick event + guard vals, expected invoking state)
    "B11": ("emit_recording_metric", ["REASON_ADDED"], "recording.starting"),
    "B13": ("record_subscribed", ["CONNECT"], "ws_conn.subscribing"),
}
GUARDS = {"B11": {"reasons_remain": True, "all_streams_healthy": True,
                  "position_open_for_symbol": False},
          "B13": {"connection_budget_exhausted": False, "is_private": False}}


async def storm_async(bid, limit):
    c = H.cfg(bid); c["maxIterations"] = limit
    raiser, kick, invoking = CASES[bid]
    st = H.Stub(c, guard_vals=GUARDS[bid], raising=[raiser])
    m = H.build(c, st)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=256,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.CvHooks(); i.use(p)
    await i.start(); await H.quiesce(i, 2)
    try:
        await asyncio.wait_for(i.send(kick[0]), 10)
    except Exception:
        pass
    # wait for CONVERGENCE, not a fixed sample (#210)
    prev, stable = -1, 0
    for _ in range(120):
        await asyncio.sleep(0.03)
        n = len(st.svc_calls)
        stable = stable + 1 if n == prev else 0
        prev = n
        if stable >= 8:
            break
    out = {"laps": len(st.svc_calls), "states": H.ids(i),
           "error": repr(i.last_error) if i.last_error else None,
           "errtype": type(i.last_error).__name__ if i.last_error else None,
           "i_dot_error": repr(i.error) if getattr(i, "error", None) else None,
           "stranded_hook": list(p.stranded),
           "runaway_stranded": getattr(i.last_error, "stranded", "n/a"),
           "hook_errors": [e for e in p.errors][:3]}
    try:
        out["dormant"] = i.has_dormant_invocations
        out["pending"] = list(i.pending_invocations())
    except Exception as e:
        out["dormant"] = "raised:%r" % (e,)
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    return out


def storm_sync(bid, limit):
    c = H.cfg(bid); c["maxIterations"] = limit
    raiser, kick, invoking = CASES[bid]
    st = H.Stub(c, guard_vals=GUARDS[bid], raising=[raiser], svc_style="def")
    m = H.build(c, st)
    i = SyncInterpreter(m, clock=SimulatedClock())
    p = H.CvHooks(); i.use(p)
    i.start()
    try:
        i.send(kick[0])
    except Exception:
        pass
    out = {"laps": len(st.svc_calls), "states": H.ids(i),
           "error": repr(i.last_error) if i.last_error else None,
           "errtype": type(i.last_error).__name__ if i.last_error else None,
           "i_dot_error": repr(i.error) if getattr(i, "error", None) else None,
           "stranded_hook": list(p.stranded),
           "runaway_stranded": getattr(i.last_error, "stranded", "n/a")}
    try:
        i.stop()
    except Exception:
        pass
    return out


async def main():
    LIM = 12
    for bid in ("B11", "B13"):
        a = await storm_async(bid, LIM)
        H.rec("D2/%s/async-engine/trips" % bid,
              a["errtype"] == "RunawayChainError",
              "err=%s laps=%s states=%s" % (a["errtype"], a["laps"], a["states"]))
        H.rec("D2/%s/async-engine/plateau=lim+2" % bid, a["laps"] == LIM + 2,
              "laps=%s expected=%s" % (a["laps"], LIM + 2))
        H.rec("D2/%s/async-engine/stranded-hook" % bid,
              bool(a["stranded_hook"]), json.dumps(a["stranded_hook"])[:200])
        H.rec("D2/%s/async-engine/err.stranded" % bid,
              bool(a["runaway_stranded"]) and a["runaway_stranded"] != "n/a",
              repr(a["runaway_stranded"])[:200])
        s = storm_sync(bid, LIM)
        H.rec("D2/%s/sync-engine/trips" % bid,
              s["errtype"] == "RunawayChainError",
              "err=%s laps=%s states=%s" % (s["errtype"], s["laps"], s["states"]))
        H.rec("D2/%s/sync-engine/plateau=lim+2" % bid, s["laps"] == LIM + 2,
              "laps=%s expected=%s" % (s["laps"], LIM + 2))
        H.rec("D2/%s/lap-parity" % bid, a["laps"] == s["laps"],
              "async=%s sync=%s" % (a["laps"], s["laps"]))
        H.RESULTS["[%s]D2/%s/raw" % (H.STYLE, bid)] = {
            "pass": True, "note": json.dumps({"async": a, "sync": s}, default=str)}
    H.dump("h_d2_storm.json")


asyncio.run(main())
