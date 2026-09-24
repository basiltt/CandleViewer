"""R7-04 refutation A2: isolate the cause of the invoke-cycle wedge.

Claim says cause = settle-budget renewal by external traffic.
Rival cause = a plain (non-coroutine) invoke's result is AWAITED by the
entering macrostep through a fixed-size thread pool (documented #149/#173),
so each lap costs a real service round-trip and the drain rate is capped by
service latency -- independent of the budget.

Variants, same cycle shape, same traffic:
  A plain_sleep1ms  pool=2   (the claimant's config)
  B plain_sleep0    pool=2   (no service latency)
  C plain_sleep1ms  pool=32  (more workers)
  D async_sleep1ms           (coroutine service, macrostep still awaits)
  E async_sleep0             (coroutine, no latency)
If the budget-renewal mechanism is the cause, ALL variants wedge alike.
"""
from __future__ import annotations
import asyncio, random, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine

LAPS = {"n": 0}
def act(i, ctx, e, ad): LAPS["n"] += 1
def svc_sleep(i, ctx, e):
    time.sleep(0.001); return {"v": 1}
def svc_fast(i, ctx, e):
    return {"v": 1}
async def asvc_sleep(i, ctx, e):
    await asyncio.sleep(0.001); return {"v": 1}
async def asvc_fast(i, ctx, e):
    return {"v": 1}

CFG = {
    "id": "a2", "initial": "ver", "context": {"n": 0}, "maxIterations": 50,
    "states": {
        "ver": {"invoke": {"src": "exec",
                           "onDone": {"target": "arm", "actions": ["act"]},
                           "onError": {"target": "arm"}}},
        "arm": {"always": {"target": "ver", "actions": ["act"]},
                "on": {"PING": {"actions": ["act"]}}},
    },
}

def mk(service):
    return create_machine(CFG, logic=MachineLogic(actions={"act": act}, services={"exec": service}))

async def storm(label, service, pool, n=6, seconds=3.0):
    LAPS["n"] = 0
    itps = [Interpreter(mk(service), service_pool_size=pool) for _ in range(n)]
    await asyncio.gather(*(i.start() for i in itps))
    t0 = time.perf_counter(); sent = 0; trace = []
    while time.perf_counter() - t0 < seconds:
        for _ in range(200):
            try: random.choice(itps).send_threadsafe("PING"); sent += 1
            except Exception: pass
        await asyncio.sleep(0.05)
        if len(trace) < 5: trace.append(sum(i.queue_depth for i in itps))
    async def probe(i):
        try:
            await asyncio.wait_for(i.send("PING", wait=True), 5); return 0
        except asyncio.TimeoutError: return 1
        except Exception: return 0
    wedged = sum(await asyncio.gather(*(probe(i) for i in itps)))
    backlog = sum(i.queue_depth for i in itps); laps = LAPS["n"]
    try: await asyncio.wait_for(asyncio.gather(*(i.stop() for i in itps)), 20)
    except asyncio.TimeoutError: pass
    print({"variant": label, "sent": sent, "laps": laps,
           "backlog_trace": trace, "final_backlog": backlog,
           "wedged": f"{wedged}/{n}"}, flush=True)

async def main():
    await storm("A plain_sleep1ms pool=2", svc_sleep, 2)
    await storm("B plain_sleep0   pool=2", svc_fast, 2)
    await storm("C plain_sleep1ms pool=32", svc_sleep, 32)
    await storm("D async_sleep1ms", asvc_sleep, 2)
    await storm("E async_sleep0", asvc_fast, 2)

asyncio.run(main())
