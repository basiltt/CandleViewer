"""P8 (STANDALONE): #194 claims `children_timeout` is per child ("N children
each awaiting D settle in ~D"). The implementation loops over WAVES of
bring-ups, giving each wave a fresh full `timeout`, so the real worst case
for start() is W x timeout where W is the number of waves -- and a child
whose own bring-up arms another child adds a wave.

This probe measures start() wall time for N=3 concurrent children with
D=0.6 s and children_timeout=0.4 s, then for a nested chain of 3 children.
Concurrent case should be ~0.4 s; nested case shows the multiplication.

Exit 1 if start() exceeds 2 x children_timeout.
"""
import asyncio, json, sys, time
from xstate_statemachine import create_machine, Interpreter, MachineLogic

D = 0.6
T = 0.4


def kid(kid_id):
    return {"id": kid_id, "initial": "s",
            "states": {"s": {"entry": ["slow"], "type": "final"}}}


PARENT = {
    "id": "p",
    "initial": "run",
    "states": {
        "run": {
            "invoke": [
                {"id": "k1", "src": "k1"},
                {"id": "k2", "src": "k2"},
                {"id": "k3", "src": "k3"},
            ]
        }
    },
}


async def slow(i, c, e, adef=None):
    await asyncio.sleep(D)


def build():
    logic = MachineLogic(actions={"slow": slow})
    kids = {
        f"k{n}": create_machine(json.loads(json.dumps(kid(f"k{n}"))), logic=logic)
        for n in (1, 2, 3)
    }
    logic2 = MachineLogic(actions={"slow": slow}, services=kids)
    return create_machine(json.loads(json.dumps(PARENT)), logic=logic2)


async def main():
    i = Interpreter(build())
    t0 = time.monotonic()
    await i.start(children_timeout=T)
    elapsed = time.monotonic() - t0
    await asyncio.sleep(D + 0.2)
    await i.stop()
    return elapsed


el = asyncio.run(asyncio.wait_for(main(), 25.0))
print(f"N=3 children, D={D}s each, children_timeout={T}s -> start() took {el:.3f}s")
bad = el > 2 * T
print("VERDICT:", "start() exceeded 2x the allowance" if bad else "within ~1 allowance (ok)")
sys.exit(1 if bad else 0)
