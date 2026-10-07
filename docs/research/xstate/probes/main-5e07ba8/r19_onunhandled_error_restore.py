"""Same as r18 ERROR case but with onUnhandled:"error" on the machine."""
import sys, asyncio, json
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.events import ErrorEvent
def cfg(ou):
    c={"id":"m","initial":"a","states":{"a":{"on":{"error.platform.svc":{"target":"failed"}}},"failed":{}}}
    if ou: c["onUnhandled"]=ou
    return c
async def case(ou):
    i=Interpreter(create_machine(cfg(ou), logic=MachineLogic())); await i.start()
    i._event_queue.put_nowait(ErrorEvent(type="error.platform.svc", error=ValueError("x"), src="svc"))
    snap=i.get_persisted_snapshot(); await i.stop()
    i2=Interpreter.from_snapshot(json.dumps(snap), create_machine(cfg(ou), logic=MachineLogic()))
    await i2.start(); await asyncio.sleep(0.3)
    print(f"onUnhandled={ou!r:8s} -> state {set(i2.current_state_ids)} status={i2.status}")
    await i2.stop()
async def main():
    for ou in [None,"error","defer","warn"]:
        await case(ou)
asyncio.run(main())
