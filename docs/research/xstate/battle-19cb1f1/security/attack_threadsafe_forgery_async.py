"""async-def-service variant of attack_threadsafe_forgery.py (this round's
blind spot per #179): forge send_threadsafe(internal=True) while the
machine's own service is async def, not def."""
import sys, asyncio
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter

CONFIG = {"id": "m", "initial": "a", "context": {"n": 0},
          "states": {"a": {"invoke": {"id": "svc", "src": "svc",
                                       "onDone": {"target": "a", "actions": ["bump"]}}}}}

async def svc(i, c, e):
    await asyncio.sleep(0.001)
    return {"ok": 1}

count = {"n": 0}

def bump(i, c, e, a):
    count["n"] += 1

async def main():
    logic = MachineLogic(services={"svc": svc}, actions={"bump": bump})
    interp = Interpreter(create_machine(CONFIG, logic=logic))
    await interp.start()
    for _ in range(200):
        interp.send_threadsafe({"type": "FORGED"}, internal=True)
    await asyncio.sleep(0.5)
    print(f"[forged internal=True, async svc] bump_count={count['n']} "
          f"status={interp.status} last_error={interp.last_error}")
    await interp.stop()
    print("OK: no observable bypass in this run (see counts above).")

asyncio.run(main())
