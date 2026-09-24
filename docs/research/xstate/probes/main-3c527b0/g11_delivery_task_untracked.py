"""G-11: the completion-delivery task (#43) is created with
`_loop_create_task` and is NOT registered with the TaskManager, so it is
neither owned by the invoking state nor awaited by stop()."""
import asyncio, gc
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

CHILD = {"id": "c", "initial": "w", "states": {"w": {"after": {30: "fin"}}, "fin": {"type": "final"}}}
PARENT = {"id": "p", "initial": "work", "states": {
    "work": {"invoke": {"src": "kid", "id": "kid", "onDone": {"target": "ok",
             "actions": ["mark"]}}}, "ok": {}}}

async def main():
    marks = []
    def mark(i, c, e): marks.append(e.type)
    child = create_machine(CHILD, logic=MachineLogic())
    m = create_machine(PARENT, logic=MachineLogic(services={"kid": child}, actions={"mark": mark}))
    it = await Interpreter(m).start()
    # stop the parent at ~the moment the child goes terminal
    await asyncio.sleep(0.030)
    await it.stop()
    await asyncio.sleep(0.1); gc.collect()
    leftover = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    print("after stop(): tasks left =", len(leftover))
    for t in leftover:
        print("   ", t.get_name(), t.get_coro().__qualname__ if hasattr(t.get_coro(), '__qualname__') else t)
    print("marks:", marks, "status:", it.status, "state:", set(it.current_state_ids))

asyncio.run(main())
