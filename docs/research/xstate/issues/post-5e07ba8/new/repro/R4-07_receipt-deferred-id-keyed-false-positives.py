"""R4-07 -- `Receipt.deferred` is keyed on `id(event)` in a set that only
shrinks on the receipt path: it leaks unboundedly AND reports `deferred=True`
for events that were fully handled.

Exits 1 while the defect is present, 0 once fixed.
"""

import gc
import logging
import sys

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

# `LATE` is unhandled in `a` (-> deferred, its id() is recorded) and handled
# in `b`, so the GO transition replays and consumes it. The replayed copy
# carries no receipt, so its id() is never discarded -- and CPython reuses
# that freed address for the next Event object.
CFG = {
    "id": "r407",
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

def false_positives() -> int:
    interp = SyncInterpreter(build())
    interp.start()
    bad = []
    for k in range(CYCLES):
        interp.send("LATE")  # deferred in `a`
        interp.send("GO")  # a -> b, replays + handles LATE
        r = interp.send("BACK", wait=True)  # fully handled, b -> a
        if r.deferred:
            bad.append(k)
        if k % 500 == 0:
            gc.collect()
    print(
        f"  handled LATE events (context n) : {interp.context['n']}\n"
        f"  real deferral buffer            : {interp.deferred_count}\n"
        f"  leaked ids in _deferred_this_step: "
        f"{len(interp._deferred_this_step)}\n"
        f"  BACK receipts falsely deferred=True: {len(bad)} of {CYCLES}"
        f"  first: {bad[:8]}"
    )
    interp.stop()
    return len(bad)

def leak() -> int:
    """No replay ever happens, so the id set grows without bound."""
    cfg = {
        "id": "leak",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {"a": {"on": {"NEVER": {"target": "a"}}}},
    }
    interp = SyncInterpreter(create_machine(cfg, logic=MachineLogic()))
    interp.start()
    for _ in range(5000):
        interp.send("UNHANDLED")
    size = len(interp._deferred_this_step)
    print(
        f"  5000 fire-and-forget defers -> deferred_count="
        f"{interp.deferred_count} (correctly capped), "
        f"_deferred_this_step={size}"
    )
    interp.stop()
    return size

if __name__ == "__main__":
    print("OBSERVED:")
    fp = false_positives()
    leaked = leak()
    print("\nEXPECTED: 0 falsely-deferred receipts (BACK is always handled),")
    print("  and _deferred_this_step bounded by the real deferral buffer")
    print(f"  (DEFER_MAX), not by the number of events ever deferred.")
    defect = fp > 0 or leaked > 1000
    print("\nRESULT:", "DEFECT PRESENT" if defect else "OK")
    sys.exit(1 if defect else 0)
