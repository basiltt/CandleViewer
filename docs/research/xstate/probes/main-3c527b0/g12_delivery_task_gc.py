"""G-12: `_loop_create_task` keeps no strong reference to the completion
delivery task. asyncio holds only a WEAK reference (see the stdlib
`asyncio.create_task` docs: 'save a reference ... to avoid a task
disappearing mid-execution'). Stress it with aggressive GC."""
import asyncio, gc
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

CHILD = {"id": "c", "initial": "w", "states": {"w": {"always": "fin"}, "fin": {"type": "final"}}}
PARENT = {"id": "p", "initial": "idle", "states": {
    "idle": {"on": {"RUN": "work"}},
    "work": {"invoke": {"src": "kid", "id": "kid", "onDone": "idle"}}}}

async def main():
    gc.set_debug(0)
    child = create_machine(CHILD, logic=MachineLogic())
    m = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    it = await Interpreter(m).start()
    misses = 0
    for i in range(300):
        await it.send("RUN")
        gc.collect()          # <-- collect while the delivery task is in flight
        done = False
        for _ in range(300):
            await asyncio.sleep(0)
            gc.collect()
            if "p.idle" in it.current_state_ids:
                done = True; break
        if not done:
            misses += 1
            print(f"  cycle {i}: onDone LOST, stuck in {set(it.current_state_ids)}")
            break
    print("lost completions:", misses, "/300")
    await it.stop()

asyncio.run(main())
