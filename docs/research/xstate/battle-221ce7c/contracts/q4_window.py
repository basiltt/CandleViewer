# -*- coding: utf-8 -*-
"""Does the B18 rollback+onDone re-arm chain TERMINATE, or does it run for as
long as we watch? Vary the observation window; a terminating chain plateaus."""
import asyncio, json, time
from charness import SETTLE, Stub, build, TraceP, ids
from cdrv import cfg_of
from xstate_statemachine import Interpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock

KW = {"guard_vals": {"cancel_working_requested": True,
                     "flatten_requested": True,
                     "all_accounts_flat": False},
      "raising": ["page_owner"]}
CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
R = {}


async def watch(window_s, samples=6):
    cfg = cfg_of("B18")
    st = Stub(cfg, **KW)
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    t0 = time.perf_counter()
    await asyncio.wait_for(interp.send("ENGAGE", wait=True), 20)
    trail = []
    for i in range(samples):
        await asyncio.sleep(window_s / samples)
        trail.append((round(time.perf_counter() - t0, 3), len(st.svc_calls)))
    out = {"trail": trail, "svc_total": len(st.svc_calls),
           "acts": len(st.trace), "ids": ids(interp),
           "status": interp.status,
           "last_error": type(getattr(interp, "last_error", None)).__name__
           if getattr(interp, "last_error", None) else None}
    try:
        await asyncio.wait_for(interp.stop(), 5)
    except Exception as ex:
        out["stop_error"] = type(ex).__name__
    return out


async def main():
    for w in (0.2, 1.0, 3.0):
        R[f"window_{w}s"] = await watch(w)

asyncio.run(main())
json.dump(R, open("results/q4_window.json", "w", encoding="utf-8"), indent=2,
          default=str)
for k, v in R.items():
    print(k, "| svc", v["svc_total"], "| trail", v["trail"],
          "|", v["status"], v["ids"], v["last_error"])
