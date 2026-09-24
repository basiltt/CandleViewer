"""#31: runtime parity for unresolvable targets under strict_targets=False."""
import sys, asyncio
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
CFG={"id":"m","strictTargets":False,"initial":"a","states":{"a":{"on":{
  "GO":{"target":{"type":"dyn"},"actions":[]}}}}}
def mk():
    import xstate_statemachine.models as M
    return create_machine(CFG, logic=MachineLogic())
try: m=mk()
except Exception as e: print("build-time rejection:", type(e).__name__, str(e)[:110]); sys.exit()
async def am():
    i=Interpreter(mk()); await i.start()
    r=await i.send("GO", wait=True); await asyncio.sleep(0.2)
    print("ASYNC receipt.error:", type(r.error).__name__ if r.error else None,
          "| ok:", i.last_transition_ok, "| last_error:", type(i.last_error).__name__ if i.last_error else None, "| status:", i.status)
    await i.stop()
asyncio.run(am())
i=SyncInterpreter(mk()); i.start()
r=i.send("GO", wait=True)
print("SYNC  receipt.error:", type(r.error).__name__ if r.error else None,
      "| ok:", i.last_transition_ok, "| last_error:", type(i.last_error).__name__ if i.last_error else None, "| status:", i.status)
try:
    i.send("GO")
except Exception as e: print("SYNC  fire-and-forget raises:", type(e).__name__)
i.stop()
