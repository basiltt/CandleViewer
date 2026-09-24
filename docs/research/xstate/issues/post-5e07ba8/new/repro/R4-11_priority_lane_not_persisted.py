# -*- coding: utf-8 -*-
"""R4-11: the priority (timer) lane is never persisted, so an already-FIRED
`after` event is lost by a snapshot taken before it is dequeued.

`_snapshot_pending_events()` reads ONLY the inbox (`_event_queue`), so
`get_persisted_snapshot()["pending_events"]` omits `_priority_queue` -- the
lane a fired `after` timer is delivered on. A deadline that has genuinely
elapsed, but whose `AfterEvent` has not yet been dequeued, is silently dropped
by a snapshot taken in that window. Combined with timers not being re-armed on
restore, no window exists in which an `after` deadline survives a crash.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

CONFIG = {
    "id": "lanes",
    "initial": "waiting",
    "context": {"fired": 0},
    "states": {
        "waiting": {"after": {"1000": {"target": "expired", "actions": ["mark"]}}},
        "expired": {"type": "final"},
    },
}


def mark(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["fired"] += 1


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"mark": mark}))


async def main() -> int:
    clock = SimulatedClock()
    i = Interpreter(build(), clock=clock)
    await i.start()
    await asyncio.sleep(0.02)

    # 🧊 Freeze the run loop so a fired timer sits in the priority lane
    #    (simulating a crash in exactly that window).
    i._processing = True
    loop_task, i._event_loop_task = i._event_loop_task, None
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    clock._now += 1.5  # the 1 s deadline has genuinely elapsed
    clock.pump()
    await asyncio.sleep(0.02)

    prio = [e.type for e in i._priority_queue]
    pending = [e.type for e in i.pending_events]
    blob = i.get_snapshot()
    d = json.loads(blob)
    snap_pending = [r["type"] for r in d["pending_events"]]
    snap_deferred = [r["type"] for r in d.get("deferred", [])]
    print("OBSERVED: _priority_queue=%r pending_events=%r" % (prio, pending))
    print("OBSERVED: snapshot pending_events=%r deferred=%r"
          % (snap_pending, snap_deferred))
    i.status = "stopped"

    c2 = SimulatedClock()
    c2._now = clock.now()
    i2 = Interpreter.from_snapshot(blob, build())
    i2.clock = c2
    await i2.start()
    await asyncio.sleep(0.03)
    await c2.increment(60000)
    await asyncio.sleep(0.03)
    restored = sorted(i2.current_state_ids)
    fired = i2.context["fired"]
    print("OBSERVED: restored after +60 s virtual time: states=%r fired=%d"
          % (restored, fired))
    await i2.stop()

    print("EXPECTED: the fired AfterEvent appears in the snapshot, and the "
          "restored machine reaches ['lanes.expired'] with fired=1 (the "
          "uninterrupted reference run's outcome).")
    ok = bool(prio) and prio[0] in snap_pending and fired == 1
    print("RESULT:", "PASS" if ok else
          "FAIL (fired AfterEvent lost across the snapshot)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
