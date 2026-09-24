"""D-concurrency-3 re-run, adapted for 3ed3099 (#102).

Original intent: an `await` inside a transition action must not be able to
durabilise an empty configuration. On 3ed3099 `get_persisted_snapshot()`
raises `SnapshotMidStepError` in that window, so the original script dies
with an exception instead of printing a verdict.

This version asks the three questions the intent actually covers:

  Q1  Does the mid-step snapshot refusal fire (and not corrupt)?
  Q2  Are the *live reader* properties still observably empty in the window
      (`current_state_ids`, `matches`)?  #102 only fixed the snapshot.
  Q3  Once the step settles, does a snapshot succeed and round-trip to a
      live machine that handles FILL?
"""

from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError

GATE: dict = {}

CFG = {
    "id": "order",
    "initial": "submitted",
    "context": {"fills": 0},
    "states": {
        "submitted": {
            "on": {"ACK": {"target": "working", "actions": ["notify_venue"]}}
        },
        "working": {"on": {"FILL": {"actions": ["record_fill"]}}},
    },
}


async def notify_venue(interpreter, ctx, event, action_def):  # noqa: ANN001
    GATE["entered"].set()
    await GATE["release"].wait()


def record_fill(interpreter, ctx, event, action_def):  # noqa: ANN001
    ctx["fills"] += 1


def machine():
    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={"notify_venue": notify_venue, "record_fill": record_fill}
        ),
    )


async def main() -> int:
    GATE["entered"] = asyncio.Event()
    GATE["release"] = asyncio.Event()

    live = Interpreter(machine())
    await live.start()
    print("before           :", sorted(live.current_state_ids), live.status)

    async def _trigger():
        await live.send("ACK")

    t = asyncio.create_task(_trigger())
    await asyncio.wait_for(GATE["entered"].wait(), 5)

    # ---- Q1: snapshot in the window ----
    q1_refused = False
    snap_in_window = None
    try:
        snap_in_window = live.get_persisted_snapshot()
    except SnapshotMidStepError as exc:
        q1_refused = True
        print("Q1 snapshot in window: refused ->", type(exc).__name__)
    if not q1_refused:
        print("Q1 snapshot in window: ALLOWED, state_ids =",
              snap_in_window["state_ids"])

    # ---- Q2: live readers in the window ----
    ids_in_window = sorted(live.current_state_ids)
    q2 = {
        "current_state_ids": ids_in_window,
        "matches_submitted": live.matches("submitted"),
        "matches_working": live.matches("working"),
        "status": live.status,
    }
    print("Q2 live readers       :", q2)
    q2_empty = not ids_in_window and live.status == "running"

    GATE["release"].set()
    await t
    await asyncio.sleep(0.05)
    print("after            :", sorted(live.current_state_ids), live.status)

    # ---- Q3: snapshot at quiescence round-trips ----
    snap = live.get_persisted_snapshot()
    await live.stop()

    GATE["entered"] = asyncio.Event()
    GATE["release"] = asyncio.Event()
    GATE["release"].set()
    restored = Interpreter.from_snapshot(json.dumps(snap), machine())
    await restored.start()
    r = await asyncio.wait_for(restored.send("FILL", wait=True), 5)
    q3_ok = (
        sorted(restored.current_state_ids) == ["order.working"]
        and restored.context["fills"] == 1
        and r.error is None
    )
    print("Q3 restored      :", sorted(restored.current_state_ids),
          restored.status, dict(restored.context), "receipt.error=", r.error)
    await restored.stop()

    print()
    print("Q1 mid-step snapshot refused        :", q1_refused)
    print("Q2 live config observably EMPTY     :", q2_empty,
          "(residual of D-concurrency-3, not covered by #102)")
    print("Q3 quiescent snapshot round-trips   :", q3_ok)
    fail = (not q1_refused) or (not q3_ok)
    print("RESULT:", "FAIL" if fail else
          "PASS (durability closed; live-reader window remains)")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
