# -*- coding: utf-8 -*-
"""Is the bounded-chain blast radius deterministic, and does `maxIterations`
bound it? 5 reps per cell. B18 rollback+invoke.onDone shape."""
import asyncio, json, statistics
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


async def one(mi):
    cfg = cfg_of("B18")
    if mi is not None:
        cfg["maxIterations"] = mi
    st = Stub(cfg, **KW)
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    await asyncio.wait_for(interp.send("ENGAGE", wait=True), 10)
    await asyncio.sleep(SETTLE * 5)
    out = (len(st.svc_calls), len(st.trace),
           type(getattr(interp, "last_error", None)).__name__
           if getattr(interp, "last_error", None) else None,
           tuple(ids(interp)),
           getattr(m, "max_iterations", None))
    await asyncio.wait_for(interp.stop(), 5)
    return out


async def main():
    for mi in (None, 2, 5, 25, 100):
        rows = [await one(mi) for _ in range(5)]
        svc = [r[0] for r in rows]
        R[str(mi)] = {"declared_max_iterations": rows[0][4],
                      "svc_calls": svc,
                      "svc_min": min(svc), "svc_max": max(svc),
                      "svc_mean": round(statistics.mean(svc), 1),
                      "acts": [r[1] for r in rows],
                      "last_error": sorted({r[2] for r in rows}),
                      "ids": sorted({r[3] for r in rows})}

asyncio.run(main())
json.dump(R, open("results/q3_budget.json", "w", encoding="utf-8"), indent=2,
          default=str)
for k, v in R.items():
    print("maxIterations=", k, "declared", v["declared_max_iterations"],
          "| svc", v["svc_calls"], "| lastErr", v["last_error"],
          "| ids", v["ids"])
