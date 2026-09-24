"""G-6: child completes at (approximately) the same moment the parent leaves
the invoking state. Does a stale onDone land in the state we already left?"""
import asyncio
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

CHILD = {"id": "c", "initial": "w", "states": {
    "w": {"after": {"DELAY": "fin"}}, "fin": {"type": "final"}}}
PARENT = {"id": "p", "initial": "work", "states": {
    "work": {"invoke": {"src": "kid", "id": "kid",
                        "onDone": {"target": "done_state"}},
             "on": {"ABORT": "aborted"}},
    "done_state": {}, "aborted": {}}}

async def run(delay_ms, abort_after_ms):
    child = create_machine({**CHILD, "states": {**CHILD["states"],
        "w": {"after": {delay_ms: "fin"}}}}, logic=MachineLogic())
    m = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    it = await Interpreter(m).start()
    await asyncio.sleep(abort_after_ms / 1000)
    await it.send("ABORT")
    await asyncio.sleep(0.25)
    res = (set(it.current_state_ids), len(it._actors), len(it._invoked_children),
           len(asyncio.all_tasks()))
    await it.stop()
    return res

async def main():
    for d, a in ((30, 10), (20, 20), (20, 19), (20, 21), (10, 10), (5, 5)):
        r = await run(d, a)
        flag = " <-- STALE onDone won" if "p.done_state" in r[0] else ""
        print(f"child_delay={d:3d}ms abort_at={a:3d}ms -> state={r[0]} actors={r[1]} invoked={r[2]} tasks={r[3]}{flag}")

asyncio.run(main())
