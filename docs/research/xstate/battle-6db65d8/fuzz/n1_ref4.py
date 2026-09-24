import logging, copy, asyncio, time
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, MachineLogic
NESTED = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}
async def svc(i,c,e): return {"ok":1}
async def main():
    it=Interpreter(create_machine(copy.deepcopy(NESTED), logic=MachineLogic(services={"svc_ok":svc})))
    await it.start()
    # co-tenant coroutine: measure scheduling latency
    lags=[]
    async def heartbeat():
        for _ in range(20):
            t=time.perf_counter(); await asyncio.sleep(0.05); lags.append(time.perf_counter()-t-0.05)
    await heartbeat()
    print(f"  co-tenant max sleep lag: {max(lags)*1000:.1f}ms  mean {sum(lags)/len(lags)*1000:.1f}ms")
    # can a user event still get through?
    t=time.perf_counter()
    try:
        r=await asyncio.wait_for(it.send("X"), 3); print(f"  send('X') returned in {time.perf_counter()-t:.2f}s")
    except asyncio.TimeoutError: print("  send('X') TIMED OUT (3s)")
    await it.stop()
asyncio.run(main())
