# -*- coding: utf-8 -*-
"""R4-18: `SimulatedClock._attach()` (clock.py) has no paired detach. Every
interpreter ever restored onto (or pointed at) a shared `SimulatedClock`
leaks forever: its `_settle_for_clock` bound method stays in
`clock._settlers`, keeping the whole interpreter object graph alive, and
`_settle_sync`/`_settle` walk the ever-growing list on every tick.

Standalone, derived from battle-5e07ba8/soak/repro_d_soak_2.py, trimmed to
run well under the time budget (20 restore cycles instead of a 25-minute
soak).

Exits 1 (defect present) if, after 20 crash/restore cycles against ONE
shared SimulatedClock and a forced `gc.collect()`, every stopped
interpreter is still reachable (not GC'able) and the clock's settler list
has grown to match. Exits 0 once a detach exists and is called on stop.
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

CYCLES = 20


async def main() -> int:
    clock = SimulatedClock()
    refs = []

    m = create_machine(CFG, logic=MachineLogic())
    interp = Interpreter(m, clock=clock)
    await interp.start()
    refs.append(weakref.ref(interp))

    # This is the documented workaround pattern: from_snapshot() takes no
    # clock= argument, so callers must manually re-point interp.clock and
    # re-`_attach` the new settle callable to keep virtual time across a
    # restore (see docs/research/xstate/battle-5e07ba8/persistence/harness.py
    # ::attach_clock).
    for _ in range(CYCLES):
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
    settlers = len(clock._settlers)
    print(f"OBSERVED: settlers registered on the clock: {settlers}")
    print(f"OBSERVED: interpreters still reachable (not GC'able): {alive} / {len(refs)}")
    print(
        "EXPECTED: a stopped interpreter's settler is removed from the clock "
        "(settlers stays bounded) and the interpreter is GC'able once "
        "otherwise unreferenced"
    )

    defect = alive == len(refs) and settlers >= len(refs)
    print(f"\nVERDICT: leak_reproduced={defect}")
    return 1 if defect else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
