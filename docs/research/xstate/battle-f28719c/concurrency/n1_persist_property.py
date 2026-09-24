"""N1 - persistence property run (#102, #107, #110, #117, #118, #128, #131).

Attack: drive a non-trivial machine (parallel regions, invoke, after timer,
guarded transitions) with N events. At EVERY quiescent point -- i.e. after
`await send(ev, wait=True)` returns -- take `get_persisted_snapshot()`.

Invariants:
  I1  the snapshot must ALWAYS succeed (SnapshotMidStepError must never
      fire at quiescence -- that is the whole contract of #102).
  I2  it must be json.dumps-able.
  I3  it must round-trip: from_snapshot(...).start() reproduces the same
      configuration + context as the live machine.
  I4  the restored machine must accept the next event without error.

Reduced: default 600 events (2,000 with `--events=2000`); each event costs
a full snapshot + restore + start + stop, so 2,000 exceeds the run budget.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import (
    SnapshotMidStepError,
    SnapshotSerializationError,
)

CFG = {
    "id": "oms",
    "type": "parallel",
    "context": {"n": 0, "fills": 0, "flag": False},
    "states": {
        "order": {
            "initial": "idle",
            "states": {
                "idle": {
                    "on": {
                        "SUBMIT": {"target": "working"},
                        "PING": {"actions": ["bump"]},
                    }
                },
                "working": {
                    "after": {80: {"target": "idle"}},
                    "on": {
                        "FILL": {"actions": ["fill"]},
                        "CANCEL": {"target": "idle"},
                        "DONE": {
                            "target": "closed",
                            "guard": "enough",
                        },
                    },
                },
                "closed": {"on": {"REOPEN": {"target": "idle"}}},
            },
        },
        "risk": {
            "initial": "ok",
            "states": {
                "ok": {"on": {"BREACH": {"target": "halted"}}},
                "halted": {"on": {"CLEAR": {"target": "ok"}}},
            },
        },
    },
}

EVENTS = ["SUBMIT", "PING", "FILL", "CANCEL", "DONE", "REOPEN",
          "BREACH", "CLEAR"]


def bump(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1


def fill(i, ctx, e, a):  # noqa: ANN001
    ctx["fills"] += 1


def enough(i, ctx, e):  # noqa: ANN001
    return ctx["fills"] > 0


def logic():
    return MachineLogic(
        actions={"bump": bump, "fill": fill}, guards={"enough": enough}
    )


def machine():
    return create_machine(CFG, logic=logic())


async def main() -> int:
    n_events = 600
    for a in sys.argv[1:]:
        if a.startswith("--events="):
            n_events = int(a.split("=", 1)[1])
    rng = random.Random(20260919)

    live = Interpreter(machine())
    await live.start()

    snaps_ok = 0
    midstep_at_quiescence = 0
    serialization_errors = 0
    roundtrip_mismatch = []
    restored_event_errors = []
    dormant_seen = 0

    for k in range(n_events):
        ev = rng.choice(EVENTS)
        try:
            await asyncio.wait_for(live.send(ev, wait=True), 5)
        except asyncio.TimeoutError:
            roundtrip_mismatch.append({"k": k, "why": "send timeout", "ev": ev})
            break

        # ---- I1/I2: snapshot at quiescence ----
        try:
            snap = live.get_persisted_snapshot()
        except SnapshotMidStepError:
            midstep_at_quiescence += 1
            continue
        except SnapshotSerializationError:
            serialization_errors += 1
            continue
        try:
            blob = json.dumps(snap)
        except TypeError as exc:
            roundtrip_mismatch.append(
                {"k": k, "why": f"not json-dumpable: {exc}"}
            )
            continue
        snaps_ok += 1

        # ---- I3/I4: round-trip every 10th (cost) ----
        if k % 10:
            continue
        live_ids = sorted(live.current_state_ids)
        live_ctx = dict(live.context)
        r = Interpreter.from_snapshot(blob, machine(), restart_timers=True)
        if r.has_dormant_timers:
            dormant_seen += 1
        await r.start()
        r_ids = sorted(r.current_state_ids)
        r_ctx = dict(r.context)
        if r_ids != live_ids or r_ctx != live_ctx:
            roundtrip_mismatch.append(
                {"k": k, "ev": ev, "live": live_ids, "restored": r_ids,
                 "live_ctx": live_ctx, "restored_ctx": r_ctx}
            )
        try:
            rec = await asyncio.wait_for(r.send("PING", wait=True), 5)
            if rec.error is not None:
                restored_event_errors.append(
                    {"k": k, "error": repr(rec.error)}
                )
        except Exception as exc:  # noqa: BLE001
            restored_event_errors.append({"k": k, "exc": repr(exc)})
        await r.stop()

    await live.stop()

    ok = (
        midstep_at_quiescence == 0
        and serialization_errors == 0
        and not roundtrip_mismatch
        and not restored_event_errors
    )
    emit(
        "n1_persist_property",
        {
            "events": n_events,
            "snapshots_ok": snaps_ok,
            "midstep_at_quiescence": midstep_at_quiescence,
            "serialization_errors": serialization_errors,
            "roundtrip_mismatches": roundtrip_mismatch[:10],
            "roundtrip_mismatch_count": len(roundtrip_mismatch),
            "restored_event_errors": restored_event_errors[:10],
            "restored_event_error_count": len(restored_event_errors),
            "dormant_timers_observed": dormant_seen,
            "result": "PASS" if ok else "FAIL",
        },
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
