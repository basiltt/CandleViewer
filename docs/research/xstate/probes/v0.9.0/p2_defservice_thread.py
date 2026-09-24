"""S-probe 2: a `def` service runs in an executor thread. What does
_issued_from_own_action() say there, and is send_threadsafe from it
classified internal or external?"""
import asyncio, threading
from xstate_statemachine import create_machine, MachineLogic, Interpreter

CFG = {"id": "m", "initial": "a", "states": {
    "a": {"invoke": {"id": "s", "src": "svc", "onDone": "b"}, "on": {"PING": "c"}},
    "b": {}, "c": {}}}

out = {}
def svc(i, c, e):
    out["thread"] = threading.current_thread().name
    try:
        out["own_action"] = i._issued_from_own_action()
    except Exception as ex:
        out["own_action"] = f"EXC {type(ex).__name__}: {ex}"
    try:
        i.send_threadsafe("PING")
        out["threadsafe"] = "accepted"
    except Exception as ex:
        out["threadsafe"] = f"EXC {type(ex).__name__}: {ex}"
    return 1

async def main():
    m = create_machine(CFG, logic=MachineLogic(services={"svc": svc}))
    i = Interpreter(m)
    await i.start()
    for _ in range(60):
        await asyncio.sleep(0.01)
        if i.current_state_ids & {"m.b", "m.c"}: break
    out["landed"] = sorted(i.current_state_ids)
    await i.stop()
    print(out)

asyncio.run(asyncio.wait_for(main(), 25))
