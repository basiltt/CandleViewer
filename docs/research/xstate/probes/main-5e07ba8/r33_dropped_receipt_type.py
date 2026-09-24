"""The receipt of a DROPPED event: docs promise RunawayChainError; the async
engine's _fail_receipt hard-codes InterpreterStoppedError."""
import sys, asyncio
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter, RunawayChainError
from xstate_statemachine.exceptions import InterpreterStoppedError
CFG={"id":"m","maxIterations":3,"initial":"a","states":{"a":{"on":{
  "SPIN":{"actions":[{"type":"raise","params":{"event":"SPIN"}}]},"W":{}}}}}
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic())); await i.start()
    await i.send("SPIN")
    recs=[i.send("W", n=k, wait=True) for k in range(8)]
    await asyncio.sleep(1.0)
    for k,r in enumerate(recs):
        try: rr=await asyncio.wait_for(r, 0.4)
        except asyncio.TimeoutError: print(f"  n={k}: NEVER RESOLVED"); continue
        if rr.error: print(f"  n={k}: error={type(rr.error).__name__}  is RunawayChainError? {isinstance(rr.error,RunawayChainError)}")
    await i.stop()
asyncio.run(main())
