"""CHANGELOG/docs: 'the triggering receipt carries RunawayChainError'.
What does the async engine actually put on the receipt?"""
import sys, asyncio
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
CFG={"id":"m","maxIterations":5,"initial":"a","states":{"a":{"on":{
  "SPIN":{"actions":[{"type":"raise","params":{"event":"SPIN"}}]}}}}}
def mk(): return create_machine(CFG, logic=MachineLogic())
async def main():
    i=Interpreter(mk()); await i.start()
    r=await i.send("SPIN", wait=True); await asyncio.sleep(0.4)
    print("ASYNC triggering receipt.error  :", type(r.error).__name__ if r.error else None)
    # the receipt of the event that is actually DROPPED
    i2=Interpreter(mk()); await i2.start()
    rs=[await asyncio.sleep(0) or i2.send("SPIN", wait=True) for _ in range(1)]
    await asyncio.sleep(0.5)
    print("ASYNC last_error                :", type(i2.last_error).__name__ if i2.last_error else None)
    await i.stop(); await i2.stop()
asyncio.run(main())
i=SyncInterpreter(mk()); i.start()
r=i.send("SPIN", wait=True)
print("SYNC  triggering receipt.error  :", type(r.error).__name__ if r.error else None)
i.stop()
