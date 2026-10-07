"""D2c -- minimal repro + mechanism for the nondeterministic `Receipt.deferred`.

Mechanism
---------
`base_interpreter.py:465`  `self._deferred_this_step: Set[int] = set()`
`base_interpreter.py:3335` `self._deferred_this_step.add(id(event))`
`interpreter.py:1278-1279` / `sync_interpreter.py:512-513`
        `deferred = id(event) in self._deferred_this_step; ...discard(...)`

An id is added for EVERY deferred event, but discarded only when a receipt is
resolved for that same object. A deferred event held in `_deferred_events` is
later replayed (`_take_deferred_for_replay`, interpreter.py:1357 /
sync_interpreter.py:785). The replayed copy carries no receipt, so:

  * if the replay HANDLES it, the event is dropped from the buffer and freed --
    but its `id()` stays in `_deferred_this_step` forever;
  * CPython reuses that heap address for a later `Event`;
  * that later event's `wait=True` receipt reads `deferred=True` although it
    was fully processed.

Whether a given address is reused depends on allocator state, which is not a
function of the event script. Hence: same script, same clock, different flags.

This script forces the collision deterministically.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import sys

sys.path.insert(
    0, "<workspace>/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

# `LATE` is unhandled in `a` (-> deferred) and handled in `b`, so a state
# change replays it and it is consumed. `GO` moves a->b, `BACK` moves b->a.
CFG = {
    "id": "d2c",
    "initial": "a",
    "onUnhandled": "defer",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b"}}},
        "b": {
            "on": {
                "LATE": {"actions": ["bump"]},
                "BACK": {"target": "a"},
            }
        },
    },
}


def bump(i, c, e, a):
    c["n"] += 1


def build():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


CYCLES = 3000


async def amain():
    interp = Interpreter(build())
    await interp.start()
    leaked = []
    false_pos = []
    for k in range(CYCLES):
        await interp.send("LATE")  # deferred in `a`, id recorded
        await interp.send("GO")  # state change -> replay -> handled, freed
        r = await interp.send("BACK", wait=True)  # fully handled event
        if r.deferred:
            false_pos.append(k)
        leaked.append(len(interp._deferred_this_step))
        if k % 500 == 0:
            gc.collect()
    print("ASYNC")
    print(f"  cycles                     : {CYCLES}")
    print(f"  events actually handled    : context n = {interp.context['n']}")
    print(f"  real deferral buffer       : {interp.deferred_count}")
    print(f"  leaked ids in _deferred_this_step: {leaked[-1]}")
    print(
        f"  BACK receipts falsely deferred=True: {len(false_pos)}"
        f"  first: {false_pos[:8]}"
    )
    await interp.stop()
    return false_pos


def smain():
    interp = SyncInterpreter(build())
    interp.start()
    false_pos = []
    for k in range(CYCLES):
        interp.send("LATE")
        interp.send("GO")
        r = interp.send("BACK", wait=True)
        if r.deferred:
            false_pos.append(k)
        if k % 500 == 0:
            gc.collect()
    print("SYNC")
    print(f"  events actually handled    : context n = {interp.context['n']}")
    print(f"  real deferral buffer       : {interp.deferred_count}")
    print(
        f"  leaked ids in _deferred_this_step: "
        f"{len(interp._deferred_this_step)}"
    )
    print(
        f"  BACK receipts falsely deferred=True: {len(false_pos)}"
        f"  first: {false_pos[:8]}"
    )
    interp.stop()
    return false_pos


if __name__ == "__main__":
    a1 = asyncio.run(amain())
    a2 = asyncio.run(amain())
    print(f"  async run A == run B ? {a1 == a2}\n")
    s1 = smain()
    s2 = smain()
    print(f"  sync  run A == run B ? {s1 == s2}")
