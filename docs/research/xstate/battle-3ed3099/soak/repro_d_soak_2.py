# -*- coding: utf-8 -*-
"""Minimal repro: D-soak-2.

`SimulatedClock._attach(settle)` (clock.py) registers a settle callable and
has no corresponding public detach/unregister method. Every interpreter that
is ever pointed at a shared `SimulatedClock` (the documented pattern for
`from_snapshot()`, which takes no `clock=` argument -- see
`docs/research/xstate/battle-5e07ba8/persistence/harness.py::attach_clock`,
itself copied from the library's own guidance) leaves a bound-method closure
(`interp._settle_for_clock`) alive in `clock._settlers` forever, even after
the interpreter is fully stopped and otherwise unreferenced. That closure
keeps the entire interpreter object graph (machine, actors, context, plugin
list) alive, and a `SimulatedClock.increment()`/`.set()` call keeps walking
the ever-growing settler list (`_drain_async`/`_settle`), so both memory
*and* CPU-per-tick grow without bound in any long-running process that
restarts interpreters against one persistent clock -- exactly the
crash-recovery / snapshot-restore pattern the library advertises for
`SimulatedClock` in tests and for a `RealClock`-free deterministic replay
harness in production.

Root cause: xstate_statemachine/clock.py, class `SimulatedClock`: `_attach`
(around line 365) has no paired `_detach`, and no caller anywhere in the
library (`interpreter.py:931`, or the documented manual re-attach idiom in
0.8's persistence guide) ever removes the OLD interpreter's settler before
attaching the new one.
"""
from __future__ import annotations

import asyncio
import gc
import json
import weakref

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.base_interpreter import _accepts_kwarg
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

    # Simulate 20 crash/restore cycles against the SAME clock -- the
    # documented pattern for restoring a snapshot with a SimulatedClock
    # (from_snapshot() takes no clock= argument, so callers must manually
    # re-point interp.clock and re-`_attach` the new settle callable).
    for _ in range(20):
        snap = interp.get_persisted_snapshot()
        snap_str = json.dumps(snap, default=repr)
        await interp.stop()

        new_m = create_machine(CFG, logic=MachineLogic())
        restored = Interpreter.from_snapshot(snap_str, new_m)
        restored.clock = clock
        restored._clock_accepts_sync = _accepts_kwarg(clock.set_timeout, "sync")
        clock._attach(restored._settle_for_clock)  # the only public hook
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


if __name__ == "__main__":
    asyncio.run(main())
