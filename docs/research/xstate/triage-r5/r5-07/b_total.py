import asyncio,time,json,sys
from xstate_statemachine import create_machine, MachineLogic, Interpreter
import xstate_statemachine as X
def blocking(i,c,e): time.sleep(0.6); return 1
def offload(i,c,e): return asyncio.get_running_loop().run_in_executor(None,lambda:(time.sleep(0.6),1)[1])
async def run(svc):
    # ONE fixed 1.5s window covering start() AND the service completion
    ticks=[0]; gaps=[]
    async def tick():
        last=time.perf_counter()
        try:
            while True:
                await asyncio.sleep(0.01); now=time.perf_counter()
                gaps.append(now-last); last=now; ticks[0]+=1
        except asyncio.CancelledError: pass
    t=asyncio.ensure_future(tick()); await asyncio.sleep(0.1); ticks[0]=0; gaps.clear()
    t0=time.perf_counter()
    it=await Interpreter(create_machine(
        {"id":"s","initial":"a","states":{"a":{"invoke":{"src":"x","onDone":"b"}},"b":{}}},
        logic=MachineLogic(services={"x":svc}))).start()
    await asyncio.sleep(1.5-(time.perf_counter()-t0))
    t.cancel(); await it.stop()
    return {"ticks_in_fixed_1.5s_window":ticks[0],"max_loop_gap_s":round(max(gaps),3),
            "total_loop_dead_s~":round(sum(g for g in gaps if g>0.05),3),"ids":sorted(it.current_state_ids)}
async def main():
    out={"version":X.__version__,"path":X.__file__}
    out["plain_def_blocking"]=await run(blocking)
    out["plain_def_executor_offload"]=await run(offload)
    print(json.dumps(out,indent=1))
asyncio.run(main())
