"""G-7: baseline -- does onDone fire at all for a timed child? (control for G-6)"""
import asyncio, time
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

PARENT = {"id": "p", "initial": "work", "states": {
    "work": {"invoke": {"src": "kid", "id": "kid", "onDone": {"target": "done_state"}},
             "on": {"ABORT": "aborted"}},
    "done_state": {}, "aborted": {}}}

async def main():
    for d in (5, 20, 30):
        child = create_machine({"id": "c", "initial": "w", "states": {
            "w": {"after": {d: "fin"}}, "fin": {"type": "final"}}}, logic=MachineLogic())
        m = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
        it = await Interpreter(m).start()
        t0 = time.perf_counter()
        for _ in range(2000):
            await asyncio.sleep(0.001)
            if "p.done_state" in it.current_state_ids: break
        print(f"child after={d}ms -> {set(it.current_state_ids)} in {1000*(time.perf_counter()-t0):.1f}ms")
        await it.stop()

asyncio.run(main())
