"""End-to-end: does a pending ErrorEvent/DoneEvent survive snapshot->restore,
and does the restored machine actually handle it?"""
import sys, asyncio, json
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.events import ErrorEvent, DoneEvent
CFG={"id":"m","initial":"a","onUnhandled":"error","states":{"a":{"on":{
  "error.platform.svc":{"target":"failed"},"done.invoke.svc":{"target":"ok"}}},
  "failed":{},"ok":{}}}
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic())); await i.start()
    await i.stop()   # stop so the inbox is not drained
    i2=Interpreter(create_machine(CFG, logic=MachineLogic())); await i2.start()
    # inject pending engine events directly into the inbox, then snapshot
    i2._event_queue.put_nowait(ErrorEvent(type="error.platform.svc", error=ValueError("x"), src="svc"))
    snap=i2.get_persisted_snapshot()
    print("version:", snap["version"])
    print("pending_events:", json.dumps(snap["pending_events"], default=str))
    await i2.stop()
    m=create_machine(CFG, logic=MachineLogic())
    i3=Interpreter.from_snapshot(json.dumps(snap), m)
    await asyncio.sleep(0.3)
    print("restored state:", i3.current_state_ids, "| status:", i3.status)
    await i3.stop()
asyncio.run(main())
