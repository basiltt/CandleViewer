"""G-8: an invoked CHILD MACHINE that fails with no onError handler.
A failing callable service calls `_fail()` (interpreter -> status 'error').
Does the child-machine path do the same?"""
import asyncio
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

async def blow(i, c, e): raise ValueError("svc boom")
async def child_blow(i, c, e): raise ValueError("child boom")

CHILD = {"id": "c", "initial": "w", "states": {
    "w": {"invoke": {"src": "inner", "id": "inner"}}}}   # no onError -> child _fail()s

async def case(name, cfg, logic):
    it = await Interpreter(create_machine(cfg, logic=logic)).start()
    await asyncio.sleep(0.3)
    print(f"{name}: status={it.status!r} error={it.error!r} state={set(it.current_state_ids)}")
    await it.stop()

async def main():
    # A) callable service fails, no onError
    await case("A callable svc, no onError",
        {"id": "p", "initial": "w", "states": {"w": {"invoke": {"src": "svc", "id": "svc"}}}},
        MachineLogic(services={"svc": blow}))
    # B) invoked child MACHINE fails, no onError on the parent
    child = create_machine(CHILD, logic=MachineLogic(services={"inner": child_blow}))
    await case("B invoked child machine, no onError",
        {"id": "p", "initial": "w", "states": {"w": {"invoke": {"src": "kid", "id": "kid"}}}},
        MachineLogic(services={"kid": child}))
    # C) invoked child machine fails, parent HAS onError
    child2 = create_machine(CHILD, logic=MachineLogic(services={"inner": child_blow}))
    await case("C invoked child machine, with onError",
        {"id": "p", "initial": "w", "states": {
            "w": {"invoke": {"src": "kid", "id": "kid", "onError": {"target": "bad"}}},
            "bad": {}}},
        MachineLogic(services={"kid": child2}))

asyncio.run(main())
