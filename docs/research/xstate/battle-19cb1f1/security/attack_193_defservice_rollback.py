"""NEW (f28719c): #193 - a def-service armed by a transition that is then
rolled back (actionErrorPolicy: rollback) must be cancelled BEFORE the
callable is submitted; no side effect must leak. Runs 200 concurrent
arm-then-rollback cycles on the async engine's def-service lane.
STANDALONE: stdlib + xstate_statemachine only."""
import sys, asyncio, warnings
warnings.simplefilter("ignore")
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter

calls = []

def submit_child(i, c, e):
    calls.append(1)
    return {"ok": True}

def failing_entry(i, c, e, a):
    raise RuntimeError("entry action failed")

CFG = {
    "id": "m", "initial": "idle", "context": {},
    "actionErrorPolicy": "rollback",
    "states": {
        "idle": {"on": {"GO": "armed"}},
        "armed": {
            "invoke": {"src": "submit_child", "onDone": "done"},
            "entry": ["failing_entry"],
        },
        "done": {},
    },
}

async def one_cycle():
    logic = MachineLogic(services={"submit_child": submit_child},
                          actions={"failing_entry": failing_entry})
    m = create_machine(CFG, logic=logic)
    interp = Interpreter(m)
    await interp.start()
    await interp.send("GO", wait=True)
    await interp.stop()
    return interp.current_state_ids

async def main(n=200):
    for _ in range(n):
        state_ids = await one_cycle()
    print(f"cycles={n} service_calls_leaked={len(calls)} final_state_ids={state_ids}")
    if calls:
        print("FINDING: def-service side effect leaked despite rollback "
              f"({len(calls)}/{n} cycles submitted the callable).")
    else:
        print("OK: def-service never submitted for a rolled-back arm "
              f"across {n} concurrent-style cycles.")

asyncio.run(main())
