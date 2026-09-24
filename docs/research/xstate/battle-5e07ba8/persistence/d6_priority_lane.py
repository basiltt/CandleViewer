# -*- coding: utf-8 -*-
"""D-persistence-6: the PRIORITY (timer) and INTERNAL (raise) lanes are
never persisted.

`Interpreter` has three queues: the inbox (`_event_queue`), the priority
lane (`_priority_queue`, where a FIRED `after` timer is delivered so it
cannot queue behind 2,000 external events, #48) and the internal lane
(`_internal_queue`, for `raise`).

`_snapshot_pending_events()` (interpreter.py:1017) reads ONLY the inbox, so
`get_persisted_snapshot()["pending_events"]` omits both other lanes. A timer
that has ALREADY FIRED -- the deadline has genuinely elapsed -- but whose
`AfterEvent` has not yet been dequeued is therefore lost by a snapshot taken
in that window, with no log line and no hook.

Combined with D-persistence-2 (timers are not re-armed on restore), a
`after`-driven timeout can be lost in BOTH the not-yet-fired and the
already-fired window: there is no window in which it survives a crash.

The internal lane is documented as "mid-macrostep state; never persisted"
(interpreter.py:995), which is defensible; the priority lane is not
documented anywhere and holds an event the engine has already committed to
delivering.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

from harness import attach_clock

CONFIG = {
    "id": "lanes",
    "initial": "waiting",
    "context": {"fired": 0},
    "states": {
        "waiting": {
            "after": {"1000": {"target": "expired", "actions": ["mark"]}},
        },
        "expired": {"type": "final"},
    },
}


def mark(i, ctx, e, ad):  # noqa: ANN001
    ctx["fired"] += 1


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"mark": mark}))


async def main() -> None:
    clock = SimulatedClock()
    i = Interpreter(build(), clock=clock)
    await i.start()
    await asyncio.sleep(0.02)

    # Freeze the run loop so a fired timer sits in the priority lane.
    i._processing = True
    loop_task, i._event_loop_task = i._event_loop_task, None
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    # Fire the timer directly: the deadline has genuinely elapsed.
    clock._now += 1.5
    clock.pump()
    await asyncio.sleep(0.02)

    print("timer HAS fired; the AfterEvent is in the priority lane:")
    print("   _priority_queue =", [e.type for e in i._priority_queue])
    print("   pending_events  =", [e.type for e in i.pending_events])
    blob = i.get_snapshot()
    d = json.loads(blob)
    print("   SNAPSHOT pending_events =",
          [r["type"] for r in d["pending_events"]])
    print("   SNAPSHOT deferred       =",
          [r["type"] for r in d["deferred"]])
    print("   -> the fired AfterEvent is in NEITHER. It is gone.")
    i.status = "stopped"

    c2 = SimulatedClock()
    c2._now = clock.now()
    i2 = Interpreter.from_snapshot(blob, build())
    attach_clock(i2, c2)
    await i2.start()
    await asyncio.sleep(0.03)
    print("\nrestored:")
    print("   states =", sorted(i2.current_state_ids),
          "fired =", i2.context["fired"])
    await c2.increment(60000)
    await asyncio.sleep(0.03)
    print("   after a further 60 s of virtual time:",
          sorted(i2.current_state_ids), "fired =", i2.context["fired"])
    print("   -> the 1 s deadline never fires. Reference run reaches "
          "['lanes.expired'] with fired=1.")
    await i2.stop()


if __name__ == "__main__":
    asyncio.run(main())
