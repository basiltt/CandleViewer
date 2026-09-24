# -*- coding: utf-8 -*-
"""Verify #106 on 3ed3099: `Receipt.deferred` bookkeeping must be per-step
and by-reference, so it can neither grow unboundedly nor mislabel a later,
unrelated, fully-handled event as deferred.

Acceptance criteria (from issue #106 body + CHANGELOG [Unreleased]):
  1. `interp._deferred_this_step` must NOT be a `Set[int]` keyed on
     `id(event)` that only ever grows -- CHANGELOG says "per-step and by
     reference". After a long run of defer/replay cycles it must not have
     grown unboundedly (bounded by real outstanding deferrals, ~0 when the
     replay always drains the buffer).
  2. A deferred event that is later replayed and handled must not leave a
     stale marker that causes a LATER, fully-handled, unrelated event to
     resolve `Receipt.deferred=True` (the id()-recycling false positive).
  3. Over many cycles (>=3000) no `send(..., wait=True)` receipt for a
     fully-handled event is falsely reported `deferred=True`.

Exits 0 only if all criteria pass.
"""
from __future__ import annotations

import gc
import logging

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

# `LATE` is unhandled in `a` (-> deferred) and handled in `b`, so the GO
# transition replays and consumes it. `BACK` is always fully handled in `b`.
CFG = {
    "id": "r106",
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


def main() -> int:
    interp = SyncInterpreter(build())
    interp.start()
    false_positives = []
    deferred_set_sizes = []

    for k in range(CYCLES):
        interp.send("LATE")  # deferred in `a`
        interp.send("GO")  # a -> b, replays + handles LATE
        r = interp.send("BACK", wait=True)  # fully handled, b -> a
        if r.deferred:
            false_positives.append(k)
        deferred_set_sizes.append(len(interp._deferred_this_step))
        if k % 500 == 0:
            gc.collect()

    max_bookkeeping_size = max(deferred_set_sizes)
    final_size = len(interp._deferred_this_step)
    handled_n = interp.context["n"]
    interp.stop()

    print(f"handled LATE events (context n)          : {handled_n} (expect {CYCLES})")
    print(f"false-positive deferred=True on BACK      : {len(false_positives)} "
          f"of {CYCLES} (expect 0) first={false_positives[:5]}")
    print(f"max size of _deferred_this_step over run  : {max_bookkeeping_size} "
          f"(expect small/bounded, not growing with CYCLES)")
    print(f"final size of _deferred_this_step         : {final_size} (expect 0)")

    failures = []
    if handled_n != CYCLES:
        failures.append(f"not all LATE events handled: {handled_n} != {CYCLES}")
    if false_positives:
        failures.append(
            f"{len(false_positives)} false-positive deferred=True receipts "
            f"(id()-recycling defect present)"
        )
    if max_bookkeeping_size >= CYCLES // 10:
        failures.append(
            f"_deferred_this_step grew with CYCLES (max={max_bookkeeping_size}); "
            f"unbounded leak defect present"
        )
    if final_size != 0:
        failures.append(f"_deferred_this_step not empty at end: {final_size}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL CRITERIA PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
