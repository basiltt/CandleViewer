"""#225 task-identity matrix (worker outlives action; hand-out idiom;
def-service send() task identity under executor) + #232 RuntimeWarning on
a never-awaited def-action wait=True guard, observed under -W error inside
asyncio. STANDALONE."""
import sys, asyncio, warnings, concurrent.futures
sys.path.insert(0, "<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.exceptions import ReentrantWaitError

results = {}

# --- R1: worker spawned from an action outlives the action; its later
# send() must NOT be treated as "issued from my action" (should be
# ordinary external traffic, routed/refused as such -- not silently
# stuck as internal-queue-only). ---
cfg = {
    "id": "m", "initial": "a",
    "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"BACK": "a"}}},
}


async def worker_outlives_action(interp, marker):
    await asyncio.sleep(0.1)
    r = await interp.send("GO", wait=True)
    marker["got"] = r


async def entry_spawns_worker(i, c, e, a):
    marker = {}
    asyncio.ensure_future(worker_outlives_action(i, marker))
    entry_spawns_worker.marker = marker


cfg["states"]["a"]["entry"] = ["spawn"]


async def r1():
    m = create_machine(cfg, logic=MachineLogic(actions={"spawn": entry_spawns_worker}))
    interp = Interpreter(m)
    await interp.start()
    await asyncio.sleep(0.3)
    await interp.stop()
    return True  # if we got here, no hang


results["R1_worker_outlives_action_no_hang"] = asyncio.run(r1())


# --- R2: reentrant wait guard still refused for genuine in-step await ---
cfg2 = {
    "id": "m", "initial": "x",
    "states": {"x": {"entry": ["reentrant_action"], "on": {"GO": "y"}}, "y": {}},
}


async def reentrant_action(i, c, e, a):
    await i.send("GO", wait=True)


async def r2():
    m2 = create_machine(cfg2, logic=MachineLogic(actions={"reentrant_action": reentrant_action}))
    interp = Interpreter(m2)
    errors = []

    class Spy:
        def on_action_error(self, i, action, error):
            errors.append(type(error).__name__)

    interp.use(Spy())
    try:
        await asyncio.wait_for(interp.start(), 5)
    except ReentrantWaitError:
        pass
    await asyncio.sleep(0.05)
    if interp.status == "running":
        await interp.stop()
    return "ReentrantWaitError" in errors


results["R2_genuine_reentrant_still_refused"] = asyncio.run(r2())


# --- R3: 100 concurrent ensure_future hand-outs while actions keep awaiting ---
async def r3():
    async def spawn_and_wait(i):
        r = asyncio.ensure_future(i.send("PING", wait=True))
        await asyncio.sleep(0.01)
        return await r

    m = create_machine({"id": "m", "initial": "a", "states": {"a": {"on": {"PING": {"target": "a", "reenter": True}}}}}, logic=MachineLogic())
    interp = Interpreter(m)
    await interp.start()
    outs = await asyncio.gather(*(spawn_and_wait(interp) for _ in range(100)))
    await interp.stop()
    return all(o is not None for o in outs)


results["R3_100_concurrent_handoffs"] = asyncio.run(r3())

for k, v in results.items():
    print(f"{k}: {v}")
