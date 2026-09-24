"""G-20: independently verify the `children + 1` task-budget claim
(docs/_guide/production-characteristics.md) and the no-wakeup claim."""
import asyncio
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

CHILD = {"id": "c", "initial": "w", "states": {"w": {"after": {1000000: "f"}}, "f": {"type": "final"}}}

def parent_cfg(n):
    return {"id": "p", "type": "parallel", "states": {
        f"s{i}": {"initial": "w", "states": {
            "w": {"invoke": {"src": "kid", "id": f"k{i}"}}}} for i in range(n)}}

async def main():
    base_it = await Interpreter(create_machine(
        {"id": "b", "initial": "a", "states": {"a": {}}}, logic=MachineLogic())).start()
    await asyncio.sleep(0.05)
    base = len(asyncio.all_tasks())
    await base_it.stop()
    print("baseline tasks (1 idle interpreter):", base)
    for n in (1, 10, 50):
        ch = create_machine(CHILD, logic=MachineLogic())
        it = await Interpreter(create_machine(parent_cfg(n),
              logic=MachineLogic(services={"kid": ch}))).start()
        await asyncio.sleep(0.2)
        t = len(asyncio.all_tasks())
        print(f"  {n:2d} idle invoked children -> {t} tasks "
              f"(children+1 = {n+1}; delta over baseline = {t-base})")
        await it.stop()

asyncio.run(main())
