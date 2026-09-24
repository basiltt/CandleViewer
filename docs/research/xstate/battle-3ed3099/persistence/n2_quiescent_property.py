# -*- coding: utf-8 -*-
"""N2 -- the brief's headline persistence property, on 3ed3099.

Two claims, measured:

  CLAIM 1 "a snapshot at EVERY quiescent point of a long event run must
           always succeed and round-trip."
           -> drive a 2,000-event run; after every event, once settled,
              take a snapshot, restore it into a fresh interpreter, and
              compare state ids + context. Any raise is a failure; any
              round-trip mismatch is a failure.

  CLAIM 2 "SnapshotMidStepError never fires at quiescence."
           -> counted above; a `SnapshotMidStepError` at a settled point is
              a false positive and is reported separately from other raises.

Scale is a parameter so the run fits the time bound.

  usage: n2_quiescent_property.py [N_EVENTS] [--restore-every K]

Restoring after every one of 2,000 events costs ~2,000 interpreter builds;
`--restore-every` snapshots every event (that is the claim under test) but
performs the full restore+compare on every K-th, which is where the cost is.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import time

from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import SnapshotMidStepError

import order_machine

POOL = ["SUBMIT", "RISK_OK", "RISK_BLOCK", "FILL", "DONE", "CANCEL",
        "ACK_OK", "STALE", "REJECT", "RESET", "NOISE"]
PAYLOAD = {"SUBMIT": lambda r: {"qty": r.randint(1, 9)},
           "FILL": lambda r: {"n": r.randint(1, 3)}}


async def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else 2000
    restore_every = 25
    if "--restore-every" in sys.argv:
        restore_every = int(sys.argv[sys.argv.index("--restore-every") + 1])

    rng = random.Random(20260919)
    clock = SimulatedClock()
    i = Interpreter(order_machine.build(), clock=clock)
    await i.start()
    await asyncio.sleep(0.02)

    snaps = 0
    midstep_raises = 0
    other_raises: list[str] = []
    restores = 0
    mismatches: list[str] = []
    restarted = 0
    t0 = time.monotonic()

    for k in range(n):
        if i.status != "running":
            # Restart on a fresh machine so the run keeps exercising the
            # snapshot path rather than idling in a terminal state.
            if i.status != "stopped":
                await i.stop()
            clock = SimulatedClock()
            i = Interpreter(order_machine.build(), clock=clock)
            await i.start()
            await asyncio.sleep(0.02)
            restarted += 1

        t = rng.choice(POOL)
        payload = PAYLOAD.get(t, lambda r: {})(rng)
        try:
            # wait=True is the library's own documented quiescence barrier.
            await i.send(t, wait=True, **payload)
        except Exception:
            pass
        if rng.random() < 0.12:
            await clock.increment(rng.choice([1000, 6000, 31000]))
        await asyncio.sleep(0)

        # --- the property: snapshot at this quiescent point ---
        blob = None
        try:
            blob = i.get_snapshot()
            snaps += 1
        except SnapshotMidStepError:
            midstep_raises += 1
        except Exception as exc:  # noqa: BLE001
            other_raises.append(f"k={k} {type(exc).__name__}: {exc}")

        if blob is not None and k % restore_every == 0:
            before_states = sorted(i.current_state_ids)
            before_ctx = json.loads(json.dumps(i.context, default=str))
            try:
                j = Interpreter.from_snapshot(
                    blob, order_machine.build(), clock=SimulatedClock())
                restores += 1
                after_states = sorted(j.current_state_ids)
                after_ctx = json.loads(json.dumps(j.context, default=str))
                if after_states != before_states:
                    mismatches.append(
                        f"k={k} states {before_states} -> {after_states}")
                elif after_ctx != before_ctx:
                    mismatches.append(f"k={k} context differs")
                if j.status == "running":
                    await j.stop()
            except Exception as exc:  # noqa: BLE001
                mismatches.append(
                    f"k={k} RESTORE RAISED {type(exc).__name__}: {exc}")

    dt = time.monotonic() - t0
    if i.status == "running":
        await i.stop()

    print(f"events sent            : {n}")
    print(f"machine restarts       : {restarted}")
    print(f"snapshots taken OK     : {snaps}")
    print(f"SnapshotMidStepError   : {midstep_raises}   <- must be 0")
    print(f"other snapshot raises  : {len(other_raises)}   <- must be 0")
    for line in other_raises[:10]:
        print("    ", line)
    print(f"restore+compare runs   : {restores}")
    print(f"round-trip mismatches  : {len(mismatches)}   <- must be 0")
    for line in mismatches[:10]:
        print("    ", line)
    print(f"wall clock             : {dt:.1f}s")
    ok = midstep_raises == 0 and not other_raises and not mismatches
    print(f"\nVERDICT: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
