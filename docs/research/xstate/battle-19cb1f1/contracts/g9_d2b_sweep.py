# -*- coding: utf-8 -*-
"""D2b: lap-parity sweep at limits 1..25 on the REAL B11 contract shape,
plus the DEFAULT-maxIterations case that was round 8's CV-F28-02 wedge.

#209 claims all three lanes agree at limits 1-25, odd and even.
Lanes: async-engine/async-svc, async-engine/def-svc, sync-engine/def-svc.
"""
from __future__ import annotations
import asyncio, json
import cv19 as H
from xstate_statemachine import Interpreter, SyncInterpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock

BID, RAISER, KICK = "B11", "emit_recording_metric", "REASON_ADDED"
GV = {"reasons_remain": True, "all_streams_healthy": True,
      "position_open_for_symbol": False}


async def _plateau_async(st, cap=400, stable_n=6):
    prev, stable = -1, 0
    for _ in range(cap):
        await asyncio.sleep(0.01)
        n = len(st.svc_calls)
        stable = stable + 1 if n == prev else 0
        prev = n
        if stable >= stable_n:
            break
    return len(st.svc_calls)


async def lane_async(limit, style):
    c = H.cfg(BID)
    if limit is not None:
        c["maxIterations"] = limit
    st = H.Stub(c, guard_vals=GV, raising=[RAISER], svc_style=style)
    i = Interpreter(H.build(c, st), clock=SimulatedClock(),
                    max_queue_size=512, overflow_policy=OverflowPolicy.RAISE)
    p = H.CvHooks(); i.use(p)
    await i.start(); await H.quiesce(i, 2)
    try:
        await asyncio.wait_for(i.send(KICK), 20)
    except Exception:
        pass
    laps = await _plateau_async(st)
    res = {"laps": laps, "errtype": type(i.last_error).__name__ if i.last_error else None,
           "stranded": list(p.stranded), "states": H.ids(i),
           "dormant": getattr(i, "has_dormant_invocations", "?")}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    return res


def lane_sync(limit):
    c = H.cfg(BID)
    if limit is not None:
        c["maxIterations"] = limit
    st = H.Stub(c, guard_vals=GV, raising=[RAISER], svc_style="def")
    i = SyncInterpreter(H.build(c, st), clock=SimulatedClock())
    p = H.CvHooks(); i.use(p)
    i.start()
    try:
        i.send(KICK)
    except Exception:
        pass
    res = {"laps": len(st.svc_calls),
           "errtype": type(i.last_error).__name__ if i.last_error else None,
           "stranded": list(p.stranded), "states": H.ids(i)}
    try:
        i.stop()
    except Exception:
        pass
    return res


async def main():
    rows, bad_parity, bad_plateau = [], [], []
    for lim in range(1, 26):
        a1 = await lane_async(lim, "async")
        a2 = await lane_async(lim, "def")
        s1 = lane_sync(lim)
        row = {"limit": lim, "async_engine_async_svc": a1["laps"],
               "async_engine_def_svc": a2["laps"], "sync_engine_def_svc": s1["laps"],
               "expect": lim + 2,
               "errs": [a1["errtype"], a2["errtype"], s1["errtype"]]}
        rows.append(row)
        if not (a1["laps"] == a2["laps"] == s1["laps"]):
            bad_parity.append(row)
        if a1["laps"] != lim + 2:
            bad_plateau.append(row)
        if not all(e == "RunawayChainError" for e in row["errs"]):
            bad_plateau.append(dict(row, why="errtype"))
    H.rec("D2b/sweep/three-lane-parity-1..25", not bad_parity,
          json.dumps(bad_parity)[:400] or "all 25 limits agree")
    H.rec("D2b/sweep/plateau==limit+2", not bad_plateau,
          json.dumps(bad_plateau)[:400] or "all 25 limits == limit+2, all RunawayChainError")
    H.RESULTS["[%s]D2b/sweep/rows" % H.STYLE] = {"pass": True,
                                                 "note": json.dumps(rows)}

    # --- DEFAULT limit: round 8's silent wedge ---
    d = await lane_async(None, "async")
    H.rec("D2b/default-limit/trips", d["errtype"] == "RunawayChainError",
          "laps=%s err=%s states=%s dormant=%s" % (
              d["laps"], d["errtype"], d["states"], d["dormant"]))
    H.rec("D2b/default-limit/stranded-hook", bool(d["stranded"]),
          json.dumps(d["stranded"])[:200])
    H.RESULTS["[%s]D2b/default/raw" % H.STYLE] = {"pass": True,
                                                  "note": json.dumps(d, default=str)}
    H.dump("g9_d2b_sweep.json")


asyncio.run(main())
