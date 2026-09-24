# -*- coding: utf-8 -*-
"""D-soak-2 re-check using the NEW `from_snapshot(clock=)` API (#117),
which supersedes the old manual `interp.clock = clock; clock._attach(...)`
idiom the original repro used. If the new documented path itself detaches
the old settler (or never needs to, because `clock=` handles attach
internally and pairs it with the library's own new `_detach`, #115), this
defect's *documented* trigger path is closed even though the underlying
`_attach`/`_detach` pair is manual plumbing.
"""
from __future__ import annotations

import asyncio
import gc
import json
import weakref

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"GO": {"target": "a"}}}},
}


async def main() -> None:
    clock = SimulatedClock()
    refs = []

    m = create_machine(CFG, logic=MachineLogic())
    interp = Interpreter(m, clock=clock)
    await interp.start()
    refs.append(weakref.ref(interp))

    for _ in range(20):
        snap = interp.get_persisted_snapshot()
        snap_str = json.dumps(snap, default=repr)
        await interp.stop()  # #115: should _detach_clock() here

        new_m = create_machine(CFG, logic=MachineLogic())
        restored = Interpreter.from_snapshot(snap_str, new_m, clock=clock)
        await restored.start()

        refs.append(weakref.ref(restored))
        interp = restored

    await interp.stop()
    gc.collect()

    alive = sum(1 for r in refs if r() is not None)
    print("settlers registered on the clock:", len(clock._settlers))
    print(f"interpreters still reachable (not GC'able): {alive} / {len(refs)}")
    if alive == len(refs):
        print("REPRODUCED: every stopped interpreter is kept alive by the clock")
    else:
        print("NOT REPRODUCED via documented from_snapshot(clock=) + stop() path")


if __name__ == "__main__":
    asyncio.run(main())
