# -*- coding: utf-8 -*-
"""D5: `after` timers under SimulatedClock + #203 provenance.

B11-B15 declare no `after` (the deadlines are context stamps driven by
LINGER_DUE / PONG_DEADLINE events), so the timer contract is exercised on a
minimal chart shaped like the deadlines the catalogue *would* use, plus the
#203 check: a hand-built AfterEvent must NOT fire a 60 s timer instantly.
"""
from __future__ import annotations
import asyncio, json
import cv19 as H
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine, OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

TIMER = {
    "id": "tmr", "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "strictTargets": True, "strict": True,
    "initial": "idle", "context": {},
    "states": {
        "idle": {"on": {"ARM": {"target": "#tmr.waiting"}}},
        "waiting": {"after": {60000: {"target": "#tmr.fired",
                                      "actions": ["mark"]}},
                    "on": {"CANCEL": {"target": "#tmr.idle"}}},
        "fired": {},
    },
}


def mk(marks):
    def mark(i, c, e, a):
        marks.append(getattr(e, "type", "?"))
    return MachineLogic(actions={"mark": mark}, strict=True)


async def timer_drive():
    marks = []
    m = create_machine(json.loads(json.dumps(TIMER)), logic=mk(marks),
                       strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.CvHooks(); i.use(p)
    await i.start(); await H.quiesce(i, 2)
    await asyncio.wait_for(i.send("ARM"), 5); await H.quiesce(i, 2)
    H.rec("D5/after/armed-not-fired", H.ids(i) == ["tmr.waiting"], str(H.ids(i)))
    # advance 59 s -- must NOT fire
    await i.clock.increment(59000.0); await H.quiesce(i, 3)
    H.rec("D5/after/59s-still-waiting", H.ids(i) == ["tmr.waiting"],
          "%s marks=%s" % (H.ids(i), marks))
    # advance past 60 s -- must fire exactly once
    await i.clock.increment(2000.0); await H.quiesce(i, 4)
    H.rec("D5/after/60s-fires-once", H.ids(i) == ["tmr.fired"] and len(marks) == 1,
          "%s marks=%s" % (H.ids(i), marks))
    await i.stop()

    # CANCEL before the deadline must disarm it for good
    marks2 = []
    m2 = create_machine(json.loads(json.dumps(TIMER)), logic=mk(marks2),
                        strict_targets=True)
    j = Interpreter(m2, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    await j.start(); await H.quiesce(j, 2)
    await asyncio.wait_for(j.send("ARM"), 5); await H.quiesce(j, 2)
    await asyncio.wait_for(j.send("CANCEL"), 5); await H.quiesce(j, 2)
    await j.clock.increment(120000.0); await H.quiesce(j, 4)
    H.rec("D5/after/cancel-disarms", H.ids(j) == ["tmr.idle"] and not marks2,
          "%s marks=%s" % (H.ids(j), marks2))
    await j.stop()


async def forged_after():
    """#203: a hand-built AfterEvent must not drive a real `after`."""
    from xstate_statemachine.events import AfterEvent
    marks = []
    m = create_machine(json.loads(json.dumps(TIMER)), logic=mk(marks),
                       strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.CvHooks(); i.use(p)
    await i.start(); await H.quiesce(i, 2)
    await asyncio.wait_for(i.send("ARM"), 5); await H.quiesce(i, 2)
    ev_type = "after.60000.tmr.waiting"
    forged = None
    for ctor in (lambda: AfterEvent(ev_type),
                 lambda: AfterEvent(type=ev_type)):
        try:
            forged = ctor(); break
        except Exception:
            continue
    note = "ctor-failed"
    if forged is not None:
        try:
            await asyncio.wait_for(i.send(forged), 5)
        except Exception as e:
            note = "send-refused:%r" % (e,)
        else:
            note = "sent"
        await H.quiesce(i, 3)
    ok = H.ids(i) == ["tmr.waiting"] and not marks
    H.rec("D5/after/forged-AfterEvent-refused", ok,
          "%s states=%s marks=%s unhandled=%s" % (note, H.ids(i), marks,
                                                  p.unhandled[:2]))
    await i.stop()


def timer_sync():
    marks = []
    m = create_machine(json.loads(json.dumps(TIMER)), logic=mk(marks),
                       strict_targets=True)
    clk = SimulatedClock()
    i = SyncInterpreter(m, clock=clk)
    i.start(); i.send("ARM")
    s1 = H.ids(i)
    clk.increment(59000.0); i.tick()
    s2 = H.ids(i)
    clk.increment(2000.0); i.tick()
    s3 = H.ids(i)
    H.rec("D5/after/sync-engine-parity", s1 == ["tmr.waiting"]
          and s2 == ["tmr.waiting"] and s3 == ["tmr.fired"],
          "arm=%s t59=%s t61=%s marks=%s" % (s1, s2, s3, marks))
    try:
        i.stop()
    except Exception:
        pass


async def main():
    await timer_drive()
    await forged_after()


asyncio.run(main())
# the sync engine + SimulatedClock must be driven OUTSIDE a running loop:
# clock.increment() is a no-op-with-warning inside one.
timer_sync()
H.dump("g9_d5_timers.json")
