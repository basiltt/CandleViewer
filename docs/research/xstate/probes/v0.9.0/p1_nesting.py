"""S-probe 1: #225 task-identity nesting depth.
Action -> helper coroutine (same task) -> send()  == internal (self-send)?
Action -> ensure_future(worker) -> worker spawns task -> send() == external?
Stdlib + xstate_statemachine only."""
import asyncio, sys
from xstate_statemachine import create_machine, MachineLogic, Interpreter

CFG = {"id": "m", "initial": "a", "states": {
    "a": {"entry": ["kick"], "on": {"PING": "b"}},
    "b": {}}}

async def run(mode):
    seen = {}
    async def helper(i):
        seen["helper_internal"] = i._issued_from_own_action()
        await i.send("PING")
    async def worker(i):
        seen["worker_internal"] = i._issued_from_own_action()
        async def inner():
            seen["inner_internal"] = i._issued_from_own_action()
            await i.send("PING")
        await asyncio.create_task(inner())
    async def kick(i, c, e, a):
        seen["action_internal"] = i._issued_from_own_action()
        if mode == "same_task":
            await helper(i)
        else:
            asyncio.ensure_future(worker(i))
    m = create_machine(CFG, logic=MachineLogic(actions={"kick": kick}))
    i = Interpreter(m)
    await i.start()
    for _ in range(50):
        await asyncio.sleep(0.01)
        if i.current_state_ids == {"m.b"}: break
    seen["landed"] = sorted(i.current_state_ids)
    await i.stop()
    return seen

async def main():
    for mode in ("same_task", "spawned_nested"):
        print(mode, await run(mode))

asyncio.run(asyncio.wait_for(main(), 25))
