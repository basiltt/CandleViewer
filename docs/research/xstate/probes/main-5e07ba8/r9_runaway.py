import sys, asyncio
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter, RunawayChainError
CFG={"id":"m","maxIterations":50,"initial":"a","states":{"a":{"on":{
  "SPIN":{"actions":[{"type":"raise","params":{"event":"SPIN"}}]},"WORK":{"actions":["w"]}}}}}
n={"w":0}
def w(i,c,e,a): n["w"]+=1
def mk(): return create_machine(CFG, logic=MachineLogic(actions={"w":w}))
i=SyncInterpreter(mk()); i.start()
r=i.send("SPIN", wait=True)
print("SYNC  receipt.error:", type(r.error).__name__ if r.error else None, "| last_transition_ok:", i.last_transition_ok, "| last_error:", type(i.last_error).__name__ if i.last_error else None)
i.stop()
# #88 per-chain: SPIN must not starve later WORKs
i=SyncInterpreter(mk()); i.start(); n["w"]=0
i.send_events(["SPIN"]+["WORK"]*5)
print("SYNC  #88 WORK handled:", n["w"], "of 5")
i.stop()
async def am():
    i=Interpreter(mk()); await i.start()
    r=await i.send("SPIN", wait=True)
    await asyncio.sleep(0.3)
    print("ASYNC receipt.error:", type(r.error).__name__ if r.error else None, "| last_transition_ok:", i.last_transition_ok, "| last_error:", type(i.last_error).__name__ if i.last_error else None)
    n["w"]=0
    for _ in range(5): await i.send("WORK")
    await asyncio.sleep(0.4)
    print("ASYNC #88 WORK handled:", n["w"], "of 5")
    await i.stop()
asyncio.run(am())
