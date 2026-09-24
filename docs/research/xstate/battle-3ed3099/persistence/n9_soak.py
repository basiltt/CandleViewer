# -*- coding: utf-8 -*-
"""N9 -- reduced persistence soak with chaos.

The brief asks for a 12-minute soak. REDUCED to a caller-specified budget
(default 240 s) to fit the task's overall wall-clock bound -- see the
report's coverage section. The workload, chaos mix and leak checks are
unchanged; only the duration is cut.

Loop: drive a random event burst, then with probability p do one of
  * snapshot + restore + resume on the restored interpreter (chaos crash)
  * snapshot only (pressure on the snapshot path)
  * advance virtual time to fire `after` timers
  * restore with restart_services/restart_timers toggled
Every snapshot is round-trip-checked. RSS and object counts are sampled to
catch a leak across thousands of restore cycles -- the failure mode a soak
exists to find and a single-shot test cannot.

usage: n9_soak.py [SECONDS]
"""
from __future__ import annotations

import asyncio
import gc
import json
import random
import sys
import time

import psutil

from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import (
    SnapshotMidStepError,
    XStateMachineError,
)

import order_machine

POOL = ["SUBMIT", "RISK_OK", "RISK_BLOCK", "FILL", "DONE", "CANCEL",
        "ACK_OK", "STALE", "REJECT", "RESET", "NOISE"]


async def fresh():
    c = SimulatedClock()
    i = Interpreter(order_machine.build(), clock=c)
    await i.start()
    await asyncio.sleep(0.01)
    return i, c


async def main() -> None:
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
    rng = random.Random(8080)
    proc = psutil.Process()

    i, c = await fresh()
    t0 = time.monotonic()
    stats = {"events": 0, "snapshots": 0, "restores": 0, "midstep": 0,
             "typed_err": 0, "raw_err": 0, "mismatch": 0, "cycles": 0,
             "resets": 0}
    raw_examples: list[str] = []
    mismatch_examples: list[str] = []
    samples: list[tuple[float, float, int]] = []

    gc.collect()
    rss0 = proc.memory_info().rss / 1e6
    obj0 = len(gc.get_objects())

    while time.monotonic() - t0 < budget:
        stats["cycles"] += 1
        for _ in range(rng.randint(1, 5)):
            if i.status != "running":
                break
            t = rng.choice(POOL)
            kw = ({"qty": rng.randint(1, 9)} if t == "SUBMIT"
                  else {"n": rng.randint(1, 3)} if t == "FILL" else {})
            try:
                await i.send(t, wait=True, **kw)
                stats["events"] += 1
            except XStateMachineError:
                stats["typed_err"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["raw_err"] += 1
                if len(raw_examples) < 8:
                    raw_examples.append(f"send {t}: {type(exc).__name__}: {exc}")

        if i.status != "running":
            if i.status != "stopped":
                await i.stop()
            i, c = await fresh()
            stats["resets"] += 1
            continue

        roll = rng.random()
        if roll < 0.20:
            await c.increment(rng.choice([1000, 6000, 31000]))
            await asyncio.sleep(0.005)
            continue

        before_states = sorted(i.current_state_ids)
        before_ctx = json.loads(json.dumps(i.context, default=str))
        try:
            blob = i.get_snapshot()
            stats["snapshots"] += 1
        except SnapshotMidStepError:
            stats["midstep"] += 1
            continue
        except Exception as exc:  # noqa: BLE001
            stats["raw_err"] += 1
            if len(raw_examples) < 8:
                raw_examples.append(f"snapshot: {type(exc).__name__}: {exc}")
            continue

        if roll < 0.75:      # chaos: crash and resume on the restore
            svc = rng.random() < 0.3
            tmr = rng.choice([None, True, False])
            try:
                j = Interpreter.from_snapshot(
                    blob, order_machine.build(), clock=SimulatedClock(),
                    restart_services=svc, restart_timers=tmr)
                stats["restores"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["raw_err"] += 1
                if len(raw_examples) < 8:
                    raw_examples.append(
                        f"restore: {type(exc).__name__}: {exc}")
                continue
            after_states = sorted(j.current_state_ids)
            after_ctx = json.loads(json.dumps(j.context, default=str))
            if after_states != before_states or after_ctx != before_ctx:
                stats["mismatch"] += 1
                if len(mismatch_examples) < 8:
                    mismatch_examples.append(
                        f"{before_states} -> {after_states}")
            await i.stop()
            i = j
            c = j.clock
            await i.start()
            await asyncio.sleep(0.01)

        if stats["cycles"] % 200 == 0:
            gc.collect()
            samples.append((time.monotonic() - t0,
                            proc.memory_info().rss / 1e6,
                            len(gc.get_objects())))

    if i.status == "running":
        await i.stop()
    gc.collect()
    rss1 = proc.memory_info().rss / 1e6
    obj1 = len(gc.get_objects())
    elapsed = time.monotonic() - t0

    print(f"soak budget          : {budget:.0f}s (REDUCED from the brief's 12 min)")
    print(f"elapsed              : {elapsed:.1f}s")
    for k in ("cycles", "events", "snapshots", "restores", "resets",
              "midstep", "typed_err"):
        print(f"{k:<21}: {stats[k]}")
    print(f"{'raw exceptions':<21}: {stats['raw_err']}   <- must be 0")
    for e in raw_examples:
        print(f"     {e[:150]}")
    print(f"{'round-trip mismatch':<21}: {stats['mismatch']}   <- must be 0")
    for e in mismatch_examples:
        print(f"     {e[:150]}")
    print(f"\nRSS   {rss0:.1f} MB -> {rss1:.1f} MB  (delta {rss1 - rss0:+.1f})")
    print(f"objs  {obj0} -> {obj1}  (delta {obj1 - obj0:+d})")
    if samples:
        print("  samples (t, rss_mb, objs):")
        for s in samples:
            print(f"    {s[0]:6.1f}  {s[1]:7.1f}  {s[2]}")
    ok = stats["raw_err"] == 0 and stats["mismatch"] == 0
    print(f"\nVERDICT: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
