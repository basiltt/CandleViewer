import asyncio, sys, copy
sys.path.insert(0, r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, Interpreter, MachineLogic
from xstate_statemachine.exceptions import RunawayChainError

CFG = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {
            "initial": "a",
            "invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m.a"}},
            "states": {
                "a": {"invoke": {"id": "i2", "src": "svc", "onDone": {"target": "#m.a"}}}
            },
        }
    },
}

async def svc(*a):
    return {"ok": 1}

async def main():
    cfg = copy.deepcopy(CFG)
    cfg["maxIterations"] = 10
    i = Interpreter(create_machine(cfg, logic=MachineLogic(services={"svc": svc})))
    try:
        await asyncio.wait_for(i.start(), timeout=5)
    except asyncio.TimeoutError:
        print("FAIL: async engine livelocked on #144 cycle")
        return
    print("async start() returned; last_error=", type(i.last_error).__name__ if i.last_error else None)
    # start() only enters the initial state + settles `always`; the invoke
    # onDone chain runs on the background run-loop task, not inside start().
    # Give the loop time to catch up before checking for the runaway signal.
    for _ in range(50):
        if i.last_error is not None:
            break
        await asyncio.sleep(0.05)
    print("after wait: last_error=", type(i.last_error).__name__ if i.last_error else None)
    assert isinstance(i.last_error, RunawayChainError), "no RunawayChainError recorded"
    await i.stop()
    print("OK: async engine also bounded")

asyncio.run(main())
