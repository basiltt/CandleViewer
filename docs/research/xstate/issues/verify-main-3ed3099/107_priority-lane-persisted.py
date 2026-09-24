# -*- coding: utf-8 -*-
"""Verify #107 on 3ed3099: the priority (fired-timer) lane must be included
in `get_persisted_snapshot()["pending_events"]`, and restoring from that
snapshot must not lose an already-fired `after` deadline.

Acceptance criteria (from issue #107 body + CHANGELOG [Unreleased]):
  1. `_snapshot_pending_events()` / `get_persisted_snapshot()["pending_events"]`
     must include events sitting in `_priority_queue` (a fired `after` timer),
     not just the inbox.
  2. A snapshot taken while a fired `AfterEvent` sits in the priority lane,
     followed by `from_snapshot(...)`, must deliver that event to the
     restored machine (it must reach the transition's target and its
     actions must run) -- i.e. the deadline is not silently lost.
  3. `AfterEvent` lateness telemetry round-trips through the snapshot
     (CHANGELOG: "AfterEvent lateness telemetry round-trips (#118)" is a
     related but separate ride-along; here we just check the pending
     record for the fired timer is well-formed / typed correctly, i.e. its
     `type` matches the original `after.*` event).

Exits 0 only if all criteria pass.
"""
from __future__ import annotations

import asyncio
import json
import logging

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

logging.disable(logging.CRITICAL)

CONFIG = {
    "id": "lanes",
    "initial": "waiting",
    "context": {"fired": 0},
    "states": {
        "waiting": {"after": {"1000": {"target": "expired", "actions": ["mark"]}}},
        "expired": {"type": "final"},
    },
}


def mark(interp, ctx, event, action_def):
    ctx["fired"] += 1


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"mark": mark}))


async def main() -> int:
    failures = []

    clock = SimulatedClock()
    i = Interpreter(build(), clock=clock)
    await i.start()
    await asyncio.sleep(0.02)

    # Freeze the run loop so a fired timer sits in the priority lane,
    # simulating a crash in exactly that window (mirrors the original
    # repro; the interpreter's own run loop is stopped by cancelling its
    # task, then its status is put back to "running" so `clock.pump()`'s
    # fire callback -- which checks `self.status != "running"` -- still
    # delivers into the priority lane rather than bailing out, exactly as
    # it would in a real process that is about to crash mid-loop).
    i._processing = True
    loop_task, i._event_loop_task = i._event_loop_task, None
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass
    i.status = "running"

    clock._now += 1.5  # the 1s deadline has genuinely elapsed
    clock.pump()
    await asyncio.sleep(0.02)

    prio_types = [e.type for e in i._priority_queue]
    print(f"priority_queue after fire: {prio_types}")
    if not prio_types:
        failures.append("fired AfterEvent did not land in the priority queue "
                         "(test setup issue, not the defect under test)")

    blob = i.get_snapshot()
    d = json.loads(blob)
    snap_pending_types = [r["type"] for r in d["pending_events"]]
    print(f"snapshot pending_events: {snap_pending_types}")

    # Criterion 1: priority lane event appears in the snapshot.
    if not (prio_types and prio_types[0] in snap_pending_types):
        failures.append(
            f"criterion 1 FAILED: fired priority-lane event {prio_types} "
            f"not present in snapshot pending_events {snap_pending_types}"
        )

    i.status = "stopped"

    # Criterion 2: restoring from that snapshot must deliver the event.
    c2 = SimulatedClock()
    c2._now = clock.now()
    i2 = Interpreter.from_snapshot(blob, build())
    i2.clock = c2
    await i2.start()
    await asyncio.sleep(0.03)
    await c2.increment(60000)
    await asyncio.sleep(0.03)
    restored_states = sorted(i2.current_state_ids)
    fired = i2.context["fired"]
    print(f"restored: states={restored_states} fired={fired}")
    await i2.stop()

    if restored_states != ["lanes.expired"] or fired != 1:
        failures.append(
            f"criterion 2 FAILED: restored machine did not process the "
            f"fired timer (states={restored_states}, fired={fired}, "
            f"expected ['lanes.expired'], 1)"
        )

    # Criterion 3: the pending record's type is well-formed (matches the
    # original after-event type, so it can be reconstructed/replayed
    # faithfully rather than corrupted/generic).
    if prio_types and snap_pending_types:
        if snap_pending_types[0] != prio_types[0]:
            failures.append(
                f"criterion 3 FAILED: persisted event type {snap_pending_types[0]!r} "
                f"!= original {prio_types[0]!r}"
            )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL CRITERIA PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
