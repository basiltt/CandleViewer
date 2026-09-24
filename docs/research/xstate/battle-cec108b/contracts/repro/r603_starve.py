import asyncio, time, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, Interpreter
CFG={"id":"spin","actionErrorPolicy":"rollback","initial":"starting","context":{},
 "states":{"starting":{"invoke":{"id":"s","src":"svc","onDone":{"target":"#spin.recording"}},
                       "on":{"ABORT":{"target":"#spin.idle"}}},
           "recording":{"entry":["boom"]},"idle":{}}}
def boom(i,c,e,a): raise RuntimeError("x")
calls=[]
async def svc(i,c,e):
    calls.append(1); return {"ok":1}
async def main():
    m=create_machine(CFG,logic=MachineLogic(actions={"boom":boom},services={"svc":svc}))
    it=Interpreter(m); await it.start()
    # concurrent heartbeat task to measure loop starvation
    lat=[]
    async def hb():
        while True:
            t=time.monotonic(); await asyncio.sleep(0); lat.append(time.monotonic()-t)
            await asyncio.sleep(0.01)
    h=asyncio.create_task(hb())
    await asyncio.sleep(1.0)
    t=time.monotonic()
    try:
        r=await asyncio.wait_for(it.send("ABORT"),timeout=5)
    except Exception as ex:
        r="EXC:"+type(ex).__name__
    print("ABORT latency=%.3fs result=%r state=%s calls=%d maxhbgap=%.4f"%(
        time.monotonic()-t,r,sorted(it.current_state_ids),len(calls),max(lat) if lat else -1))
    await asyncio.sleep(0.3)
    print("after abort: state=%s calls_total=%d (delta shows spin stopped?)"%(sorted(it.current_state_ids),len(calls)))
    n=len(calls); await asyncio.sleep(0.3)
    print("delta in 0.3s after abort:",len(calls)-n)
    h.cancel()
    await it.stop()
asyncio.run(main())
