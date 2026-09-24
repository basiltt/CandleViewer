"""P10 (STANDALONE): `_seed_pending` (#201) is armed at start() and spent by
whatever engine completion happens to arrive FIRST -- not necessarily the
seed it was armed for, and not necessarily soon.

A machine whose initial configuration invokes a long `async def` service
keeps the flag armed for the service's whole duration. Any self-generated
runaway started in the meantime is running with `_raise_depth` accumulating
-- and when the unrelated-but-first completion finally lands, the flag is
spent and `_raise_depth` is reset to 0, handing the runaway a fresh full
budget. The trip is delayed by roughly one extra `maxIterations`.

Compares laps executed with a slow initial service (flag armed) against the
same machine with no initial service (flag not armed).

Exit 1 = the armed flag measurably extends the runaway.
"""
import asyncio, json, sys
from xstate_statemachine import create_machine, Interpreter, MachineLogic

LAPS = {"n": 0}

BASE = {
    "id": "m",
    "initial": "idle",
    "maxIterations": 10,
    "states": {
        "idle": {"on": {"GO": "a"}},
        "a": {"entry": ["lap", {"type": "raise", "params": {"event": "GO2"}}],
              "on": {"GO2": "b"}},
        "b": {"entry": ["lap", {"type": "raise", "params": {"event": "GO"}}],
              "on": {"GO": "a"}},
    },
}


def lap(i, c, e, adef=None):
    LAPS["n"] += 1


async def slow(i, c, e):
    await asyncio.sleep(0.5)
    return "R"


def build(with_service):
    cfg = json.loads(json.dumps(BASE))
    if with_service:
        cfg["states"]["idle"]["invoke"] = {"id": "s", "src": "s"}
    return create_machine(
        cfg, logic=MachineLogic(services={"s": slow}, actions={"lap": lap})
    )


async def run(with_service):
    LAPS["n"] = 0
    i = Interpreter(build(with_service))
    await i.start()
    armed = i._seed_pending
    await i.send("GO")
    await asyncio.sleep(1.2)
    n = LAPS["n"]
    await i.stop()
    return armed, n


async def main():
    return await run(False), await run(True)


(a0, n0), (a1, n1) = asyncio.run(asyncio.wait_for(main(), 25.0))
print(f"no initial service : seed_pending={a0} laps={n0}")
print(f"slow initial service: seed_pending={a1} laps={n1}")
bad = n1 > n0
print("VERDICT:", "ARMED SEED EXTENDS THE RUNAWAY (bug)" if bad else "no difference (ok)")
sys.exit(1 if bad else 0)
