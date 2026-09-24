"""P3 (STANDALONE): a DELAYED self-send cycle is charged to nothing.

`_deliver` schedules a delayed `sendTo` to self through
`_deliver_priority(target_event)` with the default
`engine_completion=False`, so under #192 the item is tagged
`self_generated=False`: it is never counted by `_raise_depth` and, being
"external", is never shed when the chain budget trips. A two-state cycle
whose entry actions each fire a 1 ms self-send therefore spins forever with
`maxIterations` inert and no RunawayChainError.

Watchdog: 12 s. Exit 1 = unbounded (bug); exit 0 = bounded.
"""
import asyncio, json, sys
from xstate_statemachine import create_machine, Interpreter, MachineLogic

TICKS = {"n": 0}

CFG = {
    "id": "m",
    "initial": "a",
    "maxIterations": 20,
    "states": {
        "a": {"entry": [{"type": "raise",
                         "params": {"event": "GO", "delay": 1}}],
              "on": {"GO": "b"}, "exit": ["tick"]},
        "b": {"entry": [{"type": "raise",
                         "params": {"event": "GO", "delay": 1}}],
              "on": {"GO": "a"}, "exit": ["tick"]},
    },
}

async def main():
    machine = create_machine(
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(actions={"tick": lambda i, c, e, a=None: TICKS.__setitem__("n", TICKS["n"] + 1)}),
    )
    interp = Interpreter(machine)
    await interp.start()
    try:
        await asyncio.sleep(10.0)
    finally:
        laps = interp._raise_depth
        tripped = interp._chain_tripped
        ids = sorted(interp.current_state_ids)
        await interp.stop()
    print(f"laps(exits)={TICKS['n']}")
    print(f"after 10s: raise_depth={laps} chain_tripped={tripped} states={ids}")
    return tripped


try:
    tripped = asyncio.run(asyncio.wait_for(main(), 12.0))
except asyncio.TimeoutError:
    print("watchdog fired")
    sys.exit(1)
print("VERDICT:", "bounded (ok)" if tripped else "UNBOUNDED (bug)")
sys.exit(0 if tripped else 1)
