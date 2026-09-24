"""R2b - isolate the r2 `def`-lane wedge: executor starvation vs chain_owed."""
import asyncio, time
from common2 import Interpreter, MachineLogic, create_machine, emit
from xstate_statemachine.exceptions import RunawayChainError
LAPS={"n":0}; STOP={"go":False}
def act(i,c,e,a): LAPS["n"]+=1
def never_def(i,c,e):
    while not STOP["go"]: time.sleep(0.01)
    return {"v":1}
async def never_async(i,c,e): await asyncio.sleep(3600)
CFG={"id":"r2b","initial":"hold","context":{"n":0},"maxIterations":50,"states":{
 "hold":{"invoke":{"src":"never","onDone":{"target":"cyc"},"onError":{"target":"cyc"}},
         "on":{"LEAVE":{"target":"idle"}}},
 "idle":{"on":{"CYCLE":{"target":"cyc"},"NOOP":{"actions":["act"]}}},
 "cyc":{"always":{"target":"cyc2","actions":["act"]}},
 "cyc2":{"always":{"target":"cyc","actions":["act"]}}}}
def mk(k,pool):
    return create_machine(CFG,logic=MachineLogic(actions={"act":act},
        services={"never": never_async if k=="async def" else never_def}))
async def one(kind,pool):
    STOP["go"]=False; LAPS["n"]=0
    i=Interpreter(mk(kind,pool),service_pool_size=pool)
    await asyncio.wait_for(i.start(),10); await asyncio.sleep(0.2)
    i.send_threadsafe("LEAVE"); await asyncio.sleep(0.4)
    st=sorted(getattr(i,'current_state_ids',[]))
    # does a TRIVIAL event still round-trip?
    try:
        await asyncio.wait_for(i.send("NOOP",wait=True),5); noop=True
    except asyncio.TimeoutError: noop=False
    LAPS["n"]=0
    try:
        await asyncio.wait_for(i.send("CYCLE",wait=True),5); cyc=False
    except asyncio.TimeoutError: cyc=True
    await asyncio.sleep(0.3)
    r={"kind":kind,"pool":pool,"state_after_LEAVE":st,"owed":getattr(i,"_chain_owed",-1),
       "trivial_event_ok":noop,"cycle_wedged":cyc,"laps":LAPS["n"],
       "tripped":isinstance(i.last_error,RunawayChainError),"last_error":repr(i.last_error)[:80]}
    STOP["go"]=True
    try: await asyncio.wait_for(i.stop(),20); r["stop"]="ok"
    except asyncio.TimeoutError: r["stop"]="HUNG"
    return r
async def main():
    rows=[await one(k,p) for k in ("async def","def") for p in (1,8)]
    emit("r2b_def_lane_wedge_isolation",{"rows":rows})
    return 0
raise SystemExit(asyncio.run(main()))
