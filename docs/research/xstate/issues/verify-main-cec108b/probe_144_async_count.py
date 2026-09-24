import asyncio, sys, copy
sys.path.insert(0, r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, Interpreter, MachineLogic

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

count = {"n": 0}
async def svc(*a):
    count["n"] += 1
    return {"ok": 1}

async def main():
    cfg = copy.deepcopy(CFG)
    cfg["maxIterations"] = 10
    i = Interpreter(create_machine(cfg, logic=MachineLogic(services={"svc": svc})))
    await i.start()
    await asyncio.sleep(2)
    print("service invocations in 2s with maxIterations=10:", count["n"])
    print("status:", i.status, "last_error:", i.last_error)
    await i.stop()

asyncio.run(main())
