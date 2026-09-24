"""#94 claims completions are NEVER discarded by a chain trip -- "on both
engines". The async trip handler has no completion sparing at all: it drops
whatever event is at the head of the queue."""
import sys, asyncio
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.events import DoneEvent
import xstate_statemachine.interpreter as I
CFG={"id":"m","maxIterations":5,"initial":"a","states":{"a":{
  "invoke":{"id":"svc","src":"svc","onDone":{"target":"ok"}},
  "on":{"SPIN":{"actions":[{"type":"raise","params":{"event":"SPIN"}}]}}},
  "ok":{}}}
async def svc(i,c,e): await asyncio.sleep(0.25); return {"v":1}
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic(services={"svc":svc})))
    await i.start()
    await i.send("SPIN")           # runaway; trip fires while svc is in flight
    await asyncio.sleep(1.5)
    print("final state:", set(i.current_state_ids))
    print("VERDICT:", "done.invoke DELIVERED" if "m.ok" in i.current_state_ids
          else "*** done.invoke DISCARDED - machine STRANDED in the invoking state ***")
    await i.stop()
asyncio.run(main())
