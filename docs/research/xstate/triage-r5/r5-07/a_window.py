import asyncio,time,json
from xstate_statemachine import create_machine, MachineLogic, Interpreter
R={}
def mk(svc):
    c={"id":"s","initial":"a","states":{"a":{"invoke":{"src":"slow","onDone":"b"}},"b":{}}}
    return create_machine(c,logic=MachineLogic(services={"slow":svc}))
async def run(svc,label):
    ticks=[0]
    async def tick():
        try:
            while True: await asyncio.sleep(0.01); ticks[0]+=1
        except asyncio.CancelledError: pass
    t=asyncio.ensure_future(tick()); await asyncio.sleep(0.05); ticks[0]=0
    t0=time.perf_counter(); it=await Interpreter(mk(svc)).start(); d=time.perf_counter()-t0
    mid=ticks[0]
    await asyncio.sleep(1.0)   # full window: 1.0s more of loop time
    tot=ticks[0]
    t.cancel(); await it.stop()
    R[label]={"start_blocked_s":round(d,3),"ticks_during_start":mid,
              "ticks_total_over_~1.0s_after":tot,"ids":sorted(it.current_state_ids)}
def blocking(i,c,e): time.sleep(0.6); return 1
async def coro_blocking(i,c,e): time.sleep(0.6); return 1        # sync blocking inside async def
async def coro_proper(i,c,e): await asyncio.sleep(0.6); return 1 # correct async shape
def exec_offload(i,c,e):
    # user-side executor offload, returns awaitable -> library awaits it (late-awaitable path)
    return asyncio.get_running_loop().run_in_executor(None, lambda: (time.sleep(0.6), 1)[1])
async def main():
    for f,l in ((blocking,"plain_def_blocking"),(coro_blocking,"async_def_blocking"),
                (coro_proper,"async_def_await"),(exec_offload,"plain_def_returns_executor_future")):
        await run(f,l)
asyncio.run(main())
print(json.dumps(R,indent=1))
