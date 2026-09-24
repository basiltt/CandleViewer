"""S-probe 4: -W error::RuntimeWarning, NO catch_warnings. __del__ raises
inside whichever task/GC point finalises it. Does the machine survive?"""
import asyncio, gc
from xstate_statemachine import create_machine, MachineLogic, Interpreter

CFG = {"id": "m", "initial": "a", "states": {
    "a": {"entry": ["drop"], "on": {"B": "b"}}, "b": {"on": {"C": "c"}}, "c": {}}}

def drop_def(i, c, e, a):
    i.send("B", wait=True)   # dropped

async def main():
    m = create_machine(CFG, logic=MachineLogic(actions={"drop": drop_def}))
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.15)
    gc.collect(); await asyncio.sleep(0.05)
    print("after-gc state=", sorted(i.current_state_ids))
    await i.send("C")
    await asyncio.sleep(0.1)
    print("final state=", sorted(i.current_state_ids), "status=", i.status)
    await i.stop()

asyncio.run(asyncio.wait_for(main(), 25))
print("PROCESS-OK")
