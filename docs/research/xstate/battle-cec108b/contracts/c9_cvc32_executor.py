# -*- coding: utf-8 -*-
"""CV-C32 asks that EVERY contract service be `async def`, because #116 made
plain-`def` services run inline and block the loop. #149 moved them to a
`service_executor`. Test whether CV-C32 can be retired:
  (1) does a slow plain-def service still stall timers / inbound sends?
  (2) is the plain-def result ordering still #116-correct?
  (3) does a custom service_executor get used, and is it honoured?
"""
import asyncio, json, time, concurrent.futures
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {"id":"x","initial":"idle","onUnhandled":"defer","strict":True,
 "context":{},
 "states":{
  "idle":{"on":{"GO":{"target":"#x.busy"}}},
  "busy":{"invoke":{"id":"w","src":"work",
                    "onDone":{"target":"#x.ok"},
                    "onError":{"target":"#x.bad"}},
          "on":{"PING":{"actions":["pong"]}}},
  "ok":{}, "bad":{}}}

def build(svc, **ikw):
    trace=[]
    def pong(i,c,e,a): trace.append(("pong", time.monotonic()))
    m = create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic(
        actions={"pong":pong}, services={"work":svc}, strict=True))
    return m, trace, ikw

async def loop_stall(plain: bool, executor=None):
    """Slow service (0.5 s). While it runs, can the loop still service PINGs
    and can wall-clock timer callbacks still fire?"""
    if plain:
        def work(i,c,e):
            time.sleep(0.5); return {"ok":True}
    else:
        async def work(i,c,e):
            await asyncio.sleep(0.5); return {"ok":True}
    m, trace, _ = build(work)
    it = Interpreter(m, clock=SimulatedClock(),
                     **({"service_executor": executor} if executor else {}))
    await it.start(); await asyncio.sleep(0.03)
    ticks=[]
    async def heartbeat():
        t0=time.monotonic()
        while time.monotonic()-t0 < 0.45:
            ticks.append(time.monotonic()-t0); await asyncio.sleep(0.02)
    await it.send("GO")
    hb = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.05)
    t0=time.monotonic()
    r = await it.send("PING", wait=True)
    ping_latency = time.monotonic()-t0
    await hb
    gaps = [round(b-a,3) for a,b in zip(ticks, ticks[1:])]
    await asyncio.sleep(0.6)
    out = {"service": "plain def" if plain else "async def",
           "executor": "custom" if executor else "default",
           "heartbeat_ticks_during_service": len(ticks),
           "max_heartbeat_gap_s": max(gaps) if gaps else None,
           "ping_receipt_latency_s": round(ping_latency,3),
           "ping_ran": len(trace),
           "final": sorted(it.current_state_ids)}
    await it.stop(); return out

async def ordering(plain: bool):
    """#116: send_events([GO, CANCEL]) -- does the in-step completion land
    ahead of the next inbox event, identically for plain and async?"""
    CFG2 = json.loads(json.dumps(CFG))
    CFG2["states"]["busy"]["on"]["CANCEL"] = {"target":"#x.bad"}
    if plain:
        def work(i,c,e): return {"ok":True}
    else:
        async def work(i,c,e): return {"ok":True}
    m = create_machine(CFG2, logic=MachineLogic(
        actions={"pong":lambda i,c,e,a:None}, services={"work":work}, strict=True))
    it = Interpreter(m, clock=SimulatedClock())
    await it.start(); await asyncio.sleep(0.03)
    res=[]
    for _ in range(10):
        await it.send("GO"); await it.send("CANCEL")
        await asyncio.sleep(0.06)
        res.append(sorted(it.current_state_ids)[0])
        if res[-1] != "x.idle":
            break
    await it.stop()
    return {"service": "plain def" if plain else "async def", "outcomes": res}

async def main():
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2,
                                               thread_name_prefix="cv-svc")
    out = {"loop_stall": [await loop_stall(False), await loop_stall(True),
                          await loop_stall(True, ex)],
           "ordering": [await ordering(False), await ordering(True)]}
    ex.shutdown(wait=False)
    print(json.dumps(out, indent=1))
    json.dump(out, open("c9_cvc32_executor.json","w"), indent=1)

asyncio.run(main())
