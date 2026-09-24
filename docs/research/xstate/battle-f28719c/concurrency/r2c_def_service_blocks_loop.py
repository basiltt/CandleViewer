"""R2c - MINIMAL: does a long-running plain `def` service block the run
loop, so the machine cannot process ANY event (not even the one that
would exit the invoking state) until it returns?

Both spellings, identical shape, 2.0 s service. The probe event is sent
0.2 s after start and awaited with a 1.0 s deadline -- i.e. well before
the service returns. A machine whose loop is free answers immediately.
"""
import asyncio, time
from common2 import Interpreter, MachineLogic, create_machine, emit
CFG={"id":"r2c","initial":"hold","context":{},"states":{
 "hold":{"invoke":{"src":"slow","onDone":{"target":"done_"},"onError":{"target":"done_"}},
         "on":{"PING":{"target":"other"}}},
 "other":{},"done_":{}}}
def slow_def(i,c,e):
    time.sleep(2.0); return {"v":1}
async def slow_async(i,c,e):
    await asyncio.sleep(2.0); return {"v":1}
async def one(kind,pool):
    svc = slow_async if kind=="async def" else slow_def
    i=Interpreter(create_machine(CFG,logic=MachineLogic(services={"slow":svc})),
                  service_pool_size=pool)
    t0=time.perf_counter()
    await asyncio.wait_for(i.start(),10)
    start_s=round(time.perf_counter()-t0,3)
    await asyncio.sleep(0.2)
    t1=time.perf_counter()
    try:
        await asyncio.wait_for(i.send("PING",wait=True),1.0); ans=True
    except asyncio.TimeoutError: ans=False
    lat=round(time.perf_counter()-t1,3)
    st=sorted(getattr(i,'current_state_ids',[]))
    try: await asyncio.wait_for(i.stop(),20); stop="ok"
    except asyncio.TimeoutError: stop="HUNG"
    return {"kind":kind,"pool":pool,"start_seconds":start_s,
            "probe_answered_within_1s":ans,"probe_latency_s":lat,
            "state_after_probe":st,"stop":stop}
async def main():
    rows=[await one(k,p) for k in ("async def","def") for p in (1,4)]
    bad=[r for r in rows if not r["probe_answered_within_1s"]]
    emit("r2c_def_service_blocks_loop",{"rows":rows,"blocked":bad,
         "result":"FAIL" if bad else "PASS"})
    return 1 if bad else 0
raise SystemExit(asyncio.run(main()))
