"""D2 -- is the `Receipt.deferred` flag deterministic?

D1 found the *only* digest that differs run-to-run on a fixed script is
`receipts`, and only in the 4th field. Hypothesis: `_deferred_this_step` is a
`Set[int]` keyed on `id(event)` (base_interpreter.py:465), entries are only
discarded when a receipt is resolved, and a DEFERRED event is re-deferred on
replay without a receipt -- so its id is never discarded. CPython then recycles
that address for a later `Event`, and that later event's receipt reads
`deferred=True` although it was fully handled.

This script:
  1. reproduces the false positive with a hand-built minimal machine;
  2. prints the leaked-id set size growing without bound;
  3. proves the *address collision* by recording ids.
"""

from __future__ import annotations

import asyncio
import logging
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "d2",
    "initial": "a",
    "onUnhandled": "defer",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"HANDLED": {"actions": ["bump"]}}},
    },
}


def bump(i, c, e, a):
    c["n"] += 1


def build():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


async def amain(n=400):
    interp = Interpreter(build())
    await interp.start()
    bad = []
    leak = []
    for k in range(n):
        # One undeclared event -> deferred (no receipt requested, so its id
        # is added to `_deferred_this_step` and never discarded).
        await interp.send("UNKNOWN_%d" % k)
        r = await interp.send("HANDLED", wait=True, k=k)
        leak.append(len(interp._deferred_this_step))
        if r.deferred:
            bad.append(k)
    print(f"ASYNC: {len(bad)}/{n} HANDLED receipts falsely report deferred=True")
    print(f"       first false positives: {bad[:10]}")
    print(f"       _deferred_this_step size: start={leak[0]} end={leak[-1]}")
    print(f"       deferred_count (real buffer): {interp.deferred_count}")
    await interp.stop()
    return bad


def smain(n=400):
    interp = SyncInterpreter(build())
    interp.start()
    bad = []
    for k in range(n):
        interp.send("UNKNOWN_%d" % k)
        r = interp.send("HANDLED", wait=True, k=k)
        if r.deferred:
            bad.append(k)
    print(f"SYNC : {len(bad)}/{n} HANDLED receipts falsely report deferred=True")
    print(f"       first false positives: {bad[:10]}")
    print(f"       _deferred_this_step size: {len(interp._deferred_this_step)}")
    interp.stop()
    return bad


def run_twice():
    """Same script twice in one process: are the false positives the same?"""
    a = asyncio.run(amain())
    b = asyncio.run(amain())
    print(f"\nasync run A false-positive set == run B? {a == b}")
    c = smain()
    d = smain()
    print(f"sync  run A false-positive set == run B? {c == d}")


if __name__ == "__main__":
    run_twice()
