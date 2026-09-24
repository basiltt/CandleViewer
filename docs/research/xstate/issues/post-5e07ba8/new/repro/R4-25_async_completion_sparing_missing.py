"""R4-25: the docs (#94) claim "engine completions are never discarded" by
a runaway/maxIterations trip, on BOTH engines. `SyncInterpreter` implements a
`spare`/`keep`/`victims` partition (sync_interpreter.py:656-740) that protects
completion events from being dropped when a trip fires. `Interpreter`
(interpreter.py:1173-1196) has no such partition: it drops whatever is at the
head of the queue with no `is_system_event`/completion check.

This script trips a runaway-chain guard while a `done.invoke` is in flight on
the async engine and asserts it is NOT dropped, matching the documented
guarantee. It currently reproduces only "by circumstance" (accounting in
_raise_depth happens to spare it in this exact shape) -- so this file is
kept as a semantic regression guard: it exits 1 if the async engine ever
drops the completion in this construction, and can be strengthened later to
target the code path R4-06 shows DOES drop events at the trip head.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
from xstate_statemachine import create_machine, MachineLogic, Interpreter  # noqa: E402

CFG = {
    "id": "m",
    "maxIterations": 5,
    "initial": "a",
    "states": {
        "a": {
            "invoke": {"id": "svc", "src": "svc", "onDone": {"target": "ok"}},
            "on": {"SPIN": {"actions": [{"type": "raise", "params": {"event": "SPIN"}}]}},
        },
        "ok": {},
    },
}


async def svc(i, c, e):
    await asyncio.sleep(0.25)
    return {"v": 1}


async def main() -> int:
    i = Interpreter(create_machine(CFG, logic=MachineLogic(services={"svc": svc})))
    await i.start()
    await i.send("SPIN")  # runaway; trip fires while svc is in flight
    await asyncio.sleep(1.5)
    delivered = "m.ok" in i.current_state_ids
    print(f"OBSERVED: final state={sorted(i.current_state_ids)} delivered={delivered}")
    print(
        "EXPECTED: done.invoke DELIVERED (per #94/json-config.md/CHANGELOG: "
        "'engine completions are never discarded', documented for both engines, "
        "but only the sync engine implements the sparing partition that "
        "guarantees this by construction)"
    )
    await i.stop()
    return 0 if delivered else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
