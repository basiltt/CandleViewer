"""Triage the p1 'hop0 records 0 != 1' miss: was the deadline already fired?"""
import asyncio, json, os, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {"id": "pk", "initial": "a", "context": {"fired": []},
       "states": {"a": {"entry": [{"type": "raise",
                                   "params": {"event": "T0", "delay": 40,
                                              "id": "s0"}}],
                        "on": {"T0": {"actions": ["fire"]}}}}}

def build():
    def fire(i, c, e, a):
        c["fired"].append(e.type)
    return create_machine(json.loads(json.dumps(CFG)),
                          logic=MachineLogic(actions={"fire": fire}))

async def main():
    N = int(os.environ.get("N", "400"))
    miss = 0; miss_fired = 0; lags = []
    for _ in range(N):
        i = Interpreter(build())
        t0 = time.perf_counter()
        await i.start()
        await asyncio.sleep(0.020)
        if os.environ.get("LOAD"):
            x = 0
            for _ in range(400000):
                x += 1
        lag = (time.perf_counter() - t0) * 1000.0
        blob = i.get_persisted_snapshot()
        if isinstance(blob, str):
            blob = json.loads(blob)
        await i.stop()
        recs = blob["scheduled_sends"]
        if len(recs) != 1:
            miss += 1
            lags.append({"ms": round(lag, 1),
                         "pending": [e.get("type") for e in (blob.get("pending_events") or [])],
                         "ctx_fired": (blob.get("context") or {}).get("fired")})
            if i.context["fired"] or (blob.get("context") or {}).get("fired") or (blob.get("pending_events") or []):
                miss_fired += 1
    print(json.dumps({"N": N, "misses": miss, "misses_where_already_fired":
                      miss_fired, "elapsed_ms_at_miss": lags[:20], "deadline_ms": 40.0,
                      "VERDICT": "harness-timing" if miss == miss_fired
                      else "LIBRARY-LOSS"}, indent=1))

asyncio.run(main())
