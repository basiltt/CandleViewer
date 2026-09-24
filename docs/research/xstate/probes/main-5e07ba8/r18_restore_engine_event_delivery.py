"""#87 claim: an accepted engine event survives the snapshot AND is delivered.
Compare a pending USER event (known to work, #47) with a pending ErrorEvent."""
import sys, asyncio, json
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.events import ErrorEvent
CFG={"id":"m","initial":"a","states":{"a":{"on":{
  "error.platform.svc":{"target":"failed"},"USER":{"target":"user"}}},
  "failed":{},"user":{}}}
async def case(ev, label):
    i=Interpreter(create_machine(CFG, logic=MachineLogic())); await i.start()
    i._event_queue.put_nowait(ev)
    snap=i.get_persisted_snapshot(); await i.stop()
    print(f"{label}: persisted -> {json.dumps(snap['pending_events'], default=str)}")
    i2=Interpreter.from_snapshot(json.dumps(snap), create_machine(CFG, logic=MachineLogic()))
    print(f"{label}: restored inbox depth = {i2._event_queue.qsize()}")
    await i2.start(); await asyncio.sleep(0.3)
    print(f"{label}: state after restore+start = {set(i2.current_state_ids)}")
    await i2.stop()
async def main():
    from xstate_statemachine.events import Event
    await case(Event("USER"), "USER  ")
    await case(ErrorEvent(type="error.platform.svc", error=ValueError("x"), src="svc"), "ERROR ")
asyncio.run(main())
