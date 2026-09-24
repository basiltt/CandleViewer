"""R9-06 (STANDALONE): a DELAYED self-send cycle is charged to no budget.

`_deliver` schedules a delayed self-send through `_deliver_priority(target_event)`
with the default `engine_completion=False` (interpreter.py:2172-2173), so under
#192 the item is tagged `self_generated=False`: never counted by `_raise_depth`
(interpreter.py:2465-2477) and, being "external", never shed when the chain
budget trips (interpreter.py:1676, `over = self._raise_depth > limit and
self_generated`). A two-state cycle whose entry actions each fire a 1 ms
self-send therefore spins forever with `maxIterations` inert and no
RunawayChainError.

Watchdog: 15 s. Exit 1 = unbounded (defect, still present). Exit 0 = bounded
(a RunawayChainError fired -- defect fixed).
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

TICKS = {"n": 0}

CFG = {
    "id": "m",
    "initial": "a",
    "maxIterations": 20,
    "states": {
        "a": {
            "entry": [{"type": "raise", "params": {"event": "GO", "delay": 1}}],
            "on": {"GO": "b"},
            "exit": ["tick"],
        },
        "b": {
            "entry": [{"type": "raise", "params": {"event": "GO", "delay": 1}}],
            "on": {"GO": "a"},
            "exit": ["tick"],
        },
    },
}


async def main() -> int:
    machine = create_machine(
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(
            actions={"tick": lambda i, c, e, a=None: TICKS.__setitem__("n", TICKS["n"] + 1)}
        ),
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
    print(f"after 10s: raise_depth={laps} chain_tripped={tripped} states={ids} "
          f"maxIterations={machine.max_iterations}")
    print("VERDICT:", "bounded (ok)" if tripped else "UNBOUNDED (bug)")
    return 0 if tripped else 1


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 15.0))
    except asyncio.TimeoutError:
        print("watchdog fired -- unbounded")
        rc = 1
    sys.exit(rc)
