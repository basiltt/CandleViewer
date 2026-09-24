"""R7-04 refutation A1: if the wedge is caused by EXTERNAL TRAFFIC RENEWING
the settle budget, then shrinking maxIterations must shrink laps-per-event
and relieve the backlog. If backlog diverges identically at maxIterations=1,
the cause is the cycle's own per-lap cost, not budget renewal."""
from __future__ import annotations
import asyncio, random, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine

LAPS = {"n": 0}
def act(i, ctx, e, ad): LAPS["n"] += 1
def svc(i, ctx, e):
    time.sleep(0.001)
    return {"v": 1}

def cfg(mi: int) -> dict:
    return {
        "id": "a1", "initial": "ver", "context": {"n": 0}, "maxIterations": mi,
        "states": {
            "ver": {"invoke": {"src": "exec",
                               "onDone": {"target": "arm", "actions": ["act"]},
                               "onError": {"target": "arm"}}},
            "arm": {"always": {"target": "ver", "actions": ["act"]},
                    "on": {"PING": {"actions": ["act"]}}},
        },
    }

def mk(mi): return create_machine(cfg(mi), logic=MachineLogic(actions={"act": act}, services={"exec": svc}))

async def storm(mi: int, n: int, seconds: float) -> dict:
    LAPS["n"] = 0
    itps = [Interpreter(mk(mi), service_pool_size=2) for _ in range(n)]
    await asyncio.gather(*(i.start() for i in itps))
    t0 = time.perf_counter(); sent = 0; trace = []
    while time.perf_counter() - t0 < seconds:
        for _ in range(200):
            try: random.choice(itps).send_threadsafe("PING"); sent += 1
            except Exception: pass
        await asyncio.sleep(0.05)
        if len(trace) < 6: trace.append(sum(i.queue_depth for i in itps))
    async def probe(i):
        try:
            await asyncio.wait_for(i.send("PING", wait=True), 5); return 0
        except asyncio.TimeoutError: return 1
        except Exception: return 0
    wedged = sum(await asyncio.gather(*(probe(i) for i in itps)))
    backlog = sum(i.queue_depth for i in itps); laps = LAPS["n"]
    try: await asyncio.wait_for(asyncio.gather(*(i.stop() for i in itps)), 20)
    except asyncio.TimeoutError: pass
    return {"maxIterations": mi, "sent": sent, "laps": laps,
            "laps_per_event": round(laps / max(sent, 1), 2),
            "backlog_trace": trace, "final_backlog": backlog, "wedged": wedged}

async def main():
    for mi in (1, 5, 50, 1000):
        print(await storm(mi, 6, 3.0), flush=True)

asyncio.run(main())
