# -*- coding: utf-8 -*-
"""B11: step-by-step trace of the deferred STREAM_UNHEALTHY (INV-B11-d hazard)."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from g3_b11 import IMPL, GV

async def main():
    cfg = H.load("B11")
    st = H.Stub(cfg, guard_vals=GV, act_impl=IMPL)
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(tp)
    await it.start()
    log = []
    async def step(ev, **p):
        await it.send(ev, wait=True, **p); await quiesce(it)
        log.append({"sent": ev, "payload": p, "states": ids(it),
                    "deferred": it.deferred_count,
                    "healthy": dict(it.context["streams_healthy"]),
                    "unhandled": list(tp.unhandled), "alerts": st.trace.count("raise_degraded_alert")})
    await step("REASON_ADDED", reason="chart")
    it.context["streams_healthy"] = {"trade": True, "kline": True}
    await step("STREAM_UNHEALTHY", s="trade")
    await step("STREAM_UNHEALTHY", s="kline")   # unhandled in degraded -> deferred
    await step("STREAM_HEALTHY", s="trade")
    await step("STREAM_HEALTHY", s="kline")     # -> recording; deferred replays?
    await quiesce(it, 12)
    log.append({"sent": "(settle)", "states": ids(it), "deferred": it.deferred_count,
                "alerts": st.trace.count("raise_degraded_alert"),
                "healthy": dict(it.context["streams_healthy"])})
    await it.stop()
    print(json.dumps(log, indent=1, default=str))
    json.dump(log, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "g3_b11_defer.json"), "w"), indent=1, default=str)

asyncio.run(main())
