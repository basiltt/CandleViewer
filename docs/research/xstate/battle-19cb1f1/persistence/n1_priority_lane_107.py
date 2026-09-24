# -*- coding: utf-8 -*-
"""D-persistence-6 re-run, ADAPTED for 3ed3099 (#107).

The 5e07ba8 repro (`d6_priority_lane.py`) froze the run loop by cancelling
`_event_loop_task` and setting `_processing = True`. On this build that
technique no longer parks the fired `AfterEvent` in `_priority_queue` (the
loop-cancellation path now flips status / fails receipts, #114), so the old
script prints an empty lane and proves nothing either way.

This script tests the ACTUAL #107 claim directly and by two independent
routes:

  A. Unit route: put an `AfterEvent` in `_priority_queue` by hand and assert
     `_snapshot_pending_events()` / the serialized blob carry it, and that a
     restore replays it.
  B. End-to-end route: block the run loop inside a long-running action (a
     real await, no private surgery), let virtual time elapse so the timer
     fires into the priority lane, then snapshot from the OUTSIDE at a point
     where the configuration is legal.

Also re-checks D-persistence-7: `AfterEvent.scheduled_for` / `fired_at`
round-trip.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import AfterEvent, persist_event, restore_event

CONFIG = {
    "id": "lanes",
    "initial": "waiting",
    "context": {"fired": 0},
    "states": {
        "waiting": {"after": {"1000": {"target": "expired",
                                       "actions": ["mark"]}}},
        "expired": {"type": "final"},
    },
}


def mark(i, ctx, e, ad):  # noqa: ANN001
    ctx["fired"] += 1


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"mark": mark}))


async def route_a() -> None:
    print("=== A. priority lane is included in the persisted inbox (#107) ===")
    clock = SimulatedClock()
    i = Interpreter(build(), clock=clock)
    await i.start()
    await asyncio.sleep(0.02)

    ev = AfterEvent(type="after.1000.lanes.waiting")
    # ADAPTED @19cb1f1: #192 stores (event, self_generated) tuples in the lane.
    i._priority_queue.append((ev, False))
    lane = [e.type for e, _ in i._priority_queue]
    snapped = [e.type for e in i._snapshot_pending_events()]
    blob = i.get_snapshot()
    d = json.loads(blob)
    persisted = [r["type"] for r in d["pending_events"]]
    kinds = [r.get("kind") for r in d["pending_events"]]
    print(f"   _priority_queue        = {lane}")
    print(f"   _snapshot_pending_events= {snapped}")
    print(f"   SNAPSHOT pending_events= {persisted} kinds={kinds}")
    print(f"   VERDICT persisted      = {persisted == lane}")
    i._priority_queue.clear()
    await i.stop()

    c2 = SimulatedClock()
    i2 = Interpreter.from_snapshot(blob, build(), clock=c2)
    await i2.start()
    await asyncio.sleep(0.05)
    print(f"   restored: states={sorted(i2.current_state_ids)} "
          f"fired={i2.context['fired']}")
    print(f"   VERDICT replayed on restore = {i2.context['fired'] == 1}")
    if i2.status == "running":
        await i2.stop()


async def route_b() -> None:
    print("\n=== B. end-to-end: timer fires while the loop is busy ===")
    cfg = {
        "id": "lanes2",
        "initial": "waiting",
        "context": {"fired": 0, "slow": 0},
        "states": {
            "waiting": {
                "on": {"SLOW": {"actions": ["slow_action"]}},
                "after": {"1000": {"target": "expired",
                                   "actions": ["mark"]}},
            },
            "expired": {"type": "final"},
        },
    }
    gate = asyncio.Event()

    async def slow_action(i, ctx, e, ad):  # noqa: ANN001
        ctx["slow"] += 1
        await gate.wait()

    clock = SimulatedClock()
    m = create_machine(cfg, logic=MachineLogic(
        actions={"mark": mark, "slow_action": slow_action}))
    i = Interpreter(m, clock=clock)
    await i.start()
    await asyncio.sleep(0.02)
    await i.send("SLOW")
    await asyncio.sleep(0.05)          # loop is now parked inside the action
    await clock.increment(1500)        # deadline elapses
    await asyncio.sleep(0.05)
    print(f"   during the blocked action: _priority_queue="
          f"{[e.type for e, _ in i._priority_queue]} "
          f"fired={i.context['fired']} states={sorted(i.current_state_ids)}")
    try:
        blob = i.get_snapshot()
        d = json.loads(blob)
        print(f"   snapshot OK: pending={[r['type'] for r in d['pending_events']]}"
              f" state_ids={d['state_ids']}")
        ok = any(r["type"].startswith("after.") for r in d["pending_events"])
        print(f"   VERDICT fired timer carried = {ok} "
              f"(lane was {'non-empty' if i._priority_queue else 'EMPTY'})")
    except Exception as exc:
        print(f"   snapshot RAISED: {type(exc).__name__}: {exc}")
        blob = None
    gate.set()
    await asyncio.sleep(0.05)
    print(f"   after unblocking: states={sorted(i.current_state_ids)} "
          f"fired={i.context['fired']}")
    await i.stop()

    if blob:
        c2 = SimulatedClock()
        i2 = Interpreter.from_snapshot(blob, build_lanes2(cfg), clock=c2)
        await i2.start()
        await asyncio.sleep(0.05)
        print(f"   restored: states={sorted(i2.current_state_ids)} "
              f"fired={i2.context['fired']}")
        if i2.status == "running":
            await i2.stop()


def build_lanes2(cfg):
    async def slow_action(i, ctx, e, ad):  # noqa: ANN001
        ctx["slow"] += 1
    return create_machine(cfg, logic=MachineLogic(
        actions={"mark": mark, "slow_action": slow_action}))


def route_c() -> None:
    print("\n=== C. D-persistence-7: AfterEvent lateness round-trip ===")
    ev = AfterEvent(type="after.1000.x.y", scheduled_for=1.0, fired_at=2.0)
    rec = persist_event(ev)
    back = restore_event(rec)
    print(f"   record   = {rec}")
    print(f"   restored = {type(back).__name__} "
          f"scheduled_for={getattr(back, 'scheduled_for', None)} "
          f"fired_at={getattr(back, 'fired_at', None)}")
    ok = (isinstance(back, AfterEvent)
          and back.scheduled_for == 1.0 and back.fired_at == 2.0)
    print(f"   VERDICT lateness round-trips = {ok}")


async def main() -> None:
    await route_a()
    await route_b()
    route_c()


if __name__ == "__main__":
    asyncio.run(main())
