"""G-5: 1000 invoke/complete cycles -- task and registry leak check (#43)."""
import asyncio, gc
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

CHILD = {"id": "c", "initial": "go", "states": {"go": {"always": "fin"}, "fin": {"type": "final"}}}
PARENT = {"id": "p", "initial": "idle", "states": {
    "idle": {"on": {"RUN": "work"}},
    "work": {"invoke": {"src": "kid", "id": "kid", "onDone": {"target": "idle"}}},
}}

async def main():
    child = create_machine(CHILD, logic=MachineLogic())
    m = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    it = await Interpreter(m).start()
    await asyncio.sleep(0.05)
    base = len(asyncio.all_tasks())
    print("baseline tasks:", base)
    for n in (1, 100, 500, 1000):
        while True:
            await it.send("RUN")
            await asyncio.sleep(0)
            if "p.idle" in it.current_state_ids:
                pass
            break
        if n in (1,):
            pass
    # run N cycles properly
    async def cycle():
        await it.send("RUN")
        for _ in range(200):
            await asyncio.sleep(0)
            if "p.idle" in it.current_state_ids:
                return True
        return False
    ok = 0
    for i in range(1000):
        if await cycle(): ok += 1
        if (i + 1) % 250 == 0:
            gc.collect()
            print(f"  after {i+1:4d} cycles: tasks={len(asyncio.all_tasks()):4d} "
                  f"_actors={len(it._actors)} _invoked_children={len(it._invoked_children)} "
                  f"tm_owners={len(getattr(it.task_manager, '_tasks_by_owner', {}))}")
    print("completed cycles:", ok, "/1000  final state:", it.current_state_ids)
    await asyncio.sleep(0.2); gc.collect()
    print("final tasks:", len(asyncio.all_tasks()), "(baseline", base, ")")
    await it.stop()

asyncio.run(main())
