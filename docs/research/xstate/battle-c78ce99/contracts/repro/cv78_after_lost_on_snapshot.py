# -*- coding: utf-8 -*-
"""STANDALONE: the two library timers have two DIFFERENT persistence contracts.

VERDICT: NEEDS-WRAPPER, not a library defect. Recorded because the two timers
look interchangeable in a chart and are not across a restart.

  raise(delay=)  #213: carried in v3 `scheduled_sends` with its REMAINING
                 delay and re-armed by `start()` automatically. No opt-in.
  after          #128: NOT persisted at all (a deadline is relative to a clock
                 that no longer exists). The default restore leaves the state
                 parked forever; `from_snapshot(..., restart_timers=True)`
                 re-arms it FROM ZERO, losing the elapsed portion.

Both behaviours are as documented. The hazard for us is the asymmetry: a
control state whose only exit is its own `after` (a lockout expiry, a flatten
deadline) silently becomes a permanent park across a process restart unless
the wrapper passes `restart_timers=True`, and even then the deadline restarts
at full duration. `has_dormant_timers` is the flag to check after every
restore.

stdlib + xstate_statemachine only.  Run from any cwd.
"""
from __future__ import annotations
import asyncio, json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

DELAY = 5000
ELAPSE = 1000  # snapshot after 1000ms -> 4000ms should remain


def cfg(mode: str):
    """`mode` = "after" (the subject) or "raise" (the positive control)."""
    locked = {"entry": ["note_locked"], "on": {}}
    if mode == "after":
        locked["after"] = {DELAY: {"target": "clear", "actions": ["fired"]}}
    else:
        locked["entry"] = ["note_locked",
                           {"type": "raise",
                            "params": {"event": "DUE", "delay": DELAY,
                                       "id": "beat"}}]
        locked["on"]["DUE"] = {"target": "clear", "actions": ["fired"]}
    return {
        "id": "t_" + mode,
        "initial": "clear",
        "strict": True,
        "strictTargets": True,
        "actionErrorPolicy": "rollback",
        "guardErrorPolicy": "raise",
        "onUnhandled": "defer",
        "context": {},
        "states": {
            "clear": {"on": {"LOCK": {"target": "locked"}}},
            "locked": locked,
        },
    }


def logic(trace):
    def mk(n):
        def f(interp, ctx, evt, ad):
            trace.append(n)
        f.__name__ = n
        return f
    return MachineLogic(actions={n: mk(n) for n in ("note_locked", "fired")},
                        strict=True)


async def run(mode: str):
    trace = []
    m = create_machine(cfg(mode), logic=logic(trace))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    for _ in range(4):
        await asyncio.sleep(0.03)
    await i.send("LOCK")
    for _ in range(4):
        await asyncio.sleep(0.03)
    await i.clock.increment(ELAPSE)
    for _ in range(4):
        await asyncio.sleep(0.03)

    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    payload = json.loads(blob)
    await i.stop()

    t2 = []
    m2 = create_machine(cfg(mode), logic=logic(t2))
    j = Interpreter.from_snapshot(blob, m2, clock=SimulatedClock())
    await j.start()
    for _ in range(4):
        await asyncio.sleep(0.03)
    restored = sorted(j.current_state_ids)
    # advance well past the remaining 4000ms -- 20x the deadline
    for _ in range(20):
        await j.clock.increment(DELAY)
        for _ in range(3):
            await asyncio.sleep(0.03)
    final = sorted(j.current_state_ids)
    await j.stop()
    return {
        "mode": mode,
        "version": payload.get("version"),
        "scheduled_sends": payload.get("scheduled_sends"),
        "pending_events": payload.get("pending_events"),
        "restored": restored,
        "final_after_20x_deadline": final,
        "fired_after_restore": "fired" in t2,
    }


async def rearm_optin():
    """The #128 opt-in: `after` re-armed FROM ZERO, not at the remainder."""
    t = []
    m = create_machine(cfg("after"), logic=logic(t))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    for _ in range(4):
        await asyncio.sleep(0.03)
    await i.send("LOCK")
    for _ in range(4):
        await asyncio.sleep(0.03)
    await i.clock.increment(ELAPSE)
    for _ in range(4):
        await asyncio.sleep(0.03)
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    await i.stop()

    t2 = []
    m2 = create_machine(cfg("after"), logic=logic(t2))
    j = Interpreter.from_snapshot(blob, m2, clock=SimulatedClock(),
                                  restart_timers=True)
    dormant = getattr(j, "has_dormant_timers", None)
    await j.start()
    for _ in range(4):
        await asyncio.sleep(0.03)
    await j.clock.increment(DELAY - ELAPSE)   # the REMAINING 4000ms
    for _ in range(4):
        await asyncio.sleep(0.03)
    at_remaining = sorted(j.current_state_ids)
    await j.clock.increment(ELAPSE + 100)     # the rest of a FULL 5000ms
    for _ in range(4):
        await asyncio.sleep(0.03)
    at_full = sorted(j.current_state_ids)
    await j.stop()
    print(json.dumps({"mode": "after+restart_timers",
                      "has_dormant_timers": dormant,
                      "at_remaining_4000ms": at_remaining,
                      "at_full_5100ms": at_full}, indent=1))
    return at_remaining == ["t_after.locked"] and at_full == ["t_after.clear"]


async def main():
    ctrl = await run("raise")
    subj = await run("after")
    for r in (ctrl, subj):
        print(json.dumps(r, indent=1))
    ok_ctrl = ctrl["fired_after_restore"] and len(ctrl["scheduled_sends"]) == 1
    parked = (not subj["fired_after_restore"]
              and subj["scheduled_sends"] == []
              and subj["final_after_20x_deadline"] == ["t_after.locked"])
    optin = await rearm_optin()
    print()
    print("raise(delay=) re-armed automatically at the remaining delay:",
          ok_ctrl)
    print("after PARKED on a DEFAULT restore:", parked)
    print("after recovered with restart_timers=True, FROM ZERO:", optin)
    if ok_ctrl and parked and optin:
        print("CONFIRMED (NEEDS-WRAPPER): `after` needs restart_timers=True "
              "and then restarts from zero; `raise(delay=)` needs neither "
              "and keeps its remainder. Both are documented (#128 / #213) -- "
              "this is an asymmetry our wrapper must own, not a library bug.")
    else:
        print("UNEXPECTED -- investigate")


asyncio.run(main())
