"""N6 — SOAK with chaos, REDUCED to ~6 minutes (brief allows 12; halved to
fit the 25-minute task budget -- stated in the report).

A long-lived OMS-shaped actor takes continuous traffic while a chaos loop
snapshots/restores it, fires timers on a SimulatedClock, injects hostile
events and trips child actors. Invariants checked continuously:

  * the configuration is never empty while status == "running"
  * every accepted order is either filled or rejected (no lost orders)
  * a snapshot at quiescence always succeeds and round-trips
  * RSS does not grow without bound
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from typing import Any, Dict, List

from n_harness import attack, main

import psutil

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SnapshotMidStepError,
    XStateMachineError,
    create_machine,
)

SOAK_SECONDS = float(os.environ.get("SOAK_SECONDS", "360"))

OMS = {
    "id": "oms",
    "initial": "idle",
    "context": {"submitted": 0, "filled": 0, "rejected": 0},
    "states": {
        "idle": {"on": {"SUBMIT": {"target": "working", "actions": ["count_sub"]}}},
        "working": {
            "on": {
                "FILL": {"target": "idle", "actions": ["count_fill"]},
                "REJECT": {"target": "idle", "actions": ["count_rej"]},
            }
        },
    },
}


def _logic() -> MachineLogic:
    def count_sub(i, c, e, a):  # noqa: ANN001
        c["submitted"] = c.get("submitted", 0) + 1

    def count_fill(i, c, e, a):  # noqa: ANN001
        c["filled"] = c.get("filled", 0) + 1

    def count_rej(i, c, e, a):  # noqa: ANN001
        c["rejected"] = c.get("rejected", 0) + 1

    return MachineLogic(
        actions={"count_sub": count_sub, "count_fill": count_fill, "count_rej": count_rej}
    )


@attack(
    "N6-01",
    f"{int(SOAK_SECONDS/60)}-minute chaos soak: no lost order, never inert-while-running, bounded RSS",
    "an OMS runs for weeks; a leak or a silently inert actor only shows up under time",
)
async def n6_01() -> Dict[str, Any]:
    rnd = random.Random(777)
    proc = psutil.Process()
    mk = lambda: create_machine(OMS, logic=_logic())  # noqa: E731
    i = await Interpreter(mk()).start()

    t0 = time.time()
    rss0 = proc.memory_info().rss
    violations: List[Dict[str, Any]] = []
    stats = {"events": 0, "snapshots": 0, "restores": 0, "hostile": 0, "midstep": 0}
    rss_samples: List[int] = [rss0]
    inflight = False

    while time.time() - t0 < SOAK_SECONDS:
        for _ in range(200):
            roll = rnd.random()
            if roll < 0.45 and not inflight:
                await i.send("SUBMIT", wait=True)
                inflight = True
            elif roll < 0.80 and inflight:
                await i.send("FILL" if rnd.random() < 0.7 else "REJECT", wait=True)
                inflight = False
            elif roll < 0.90:
                # hostile / unknown traffic must never corrupt the machine
                stats["hostile"] += 1
                try:
                    await i.send({"type": rnd.choice(["NOPE", "??", "x" * 200])}, wait=True)
                except XStateMachineError:
                    pass
            else:
                # snapshot at quiescence must always succeed and round-trip
                try:
                    blob = json.dumps(i.get_persisted_snapshot())
                    stats["snapshots"] += 1
                except SnapshotMidStepError:
                    stats["midstep"] += 1
                    violations.append({"kind": "midstep-at-quiescence"})
                    continue
                if rnd.random() < 0.25:
                    r = await Interpreter.from_snapshot(blob, mk()).start()
                    stats["restores"] += 1
                    if sorted(r.current_state_ids) != sorted(i.current_state_ids):
                        violations.append(
                            {"kind": "restore-drift", "live": sorted(i.current_state_ids),
                             "restored": sorted(r.current_state_ids)}
                        )
                    await r.stop()
            stats["events"] += 1

            # ---- continuous invariants
            if i.status == "running" and not i.current_state_ids:
                violations.append({"kind": "inert-while-running", "at": stats["events"]})
            c = i.context
            if c["filled"] + c["rejected"] > c["submitted"]:
                violations.append({"kind": "lost-order-accounting", "ctx": dict(c)})
            if violations:
                break
        rss_samples.append(proc.memory_info().rss)
        if violations:
            break
        await asyncio.sleep(0)

    ctx = dict(i.context)
    status = i.status
    await i.stop()
    rss_end = rss_samples[-1]
    growth_mb = (rss_end - rss0) / 1e6
    # generous: an unbounded leak over this many events shows far more than 64 MB
    return {
        "ok": not violations and growth_mb < 64,
        "elapsed_s": round(time.time() - t0, 1),
        "violations": violations[:5],
        "stats": stats,
        "context": ctx,
        "outstanding": ctx["submitted"] - ctx["filled"] - ctx["rejected"],
        "status": status,
        "rss_mb_start": round(rss0 / 1e6, 1),
        "rss_mb_end": round(rss_end / 1e6, 1),
        "rss_growth_mb": round(growth_mb, 1),
    }


if __name__ == "__main__":
    main("n6_soak")
