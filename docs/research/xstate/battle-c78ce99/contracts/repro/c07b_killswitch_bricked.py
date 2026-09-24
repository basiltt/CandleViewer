# -*- coding: utf-8 -*-
"""STANDALONE repro -- C-07b: a guard-denied RELEASE bricks the kill switch.

OUR-CONTRACT defect in B18 `kill_switch` (not a library defect). B18 declares
`onUnhandled: "error"`, and its `engaged` state's ONLY handler is

    "RELEASE": {"target": "clear", "guard": "owner_and_elevated"}

Under `onUnhandled: "error"` a transition whose guard denies is not "no
transition selected and we move on" -- the event is unhandled, and unhandled
is an ERROR. So an operator who presses RELEASE without the elevated role
does not merely get refused: the interpreter errors out, and the subsequent
legitimate RELEASE by a properly elevated operator can no longer be
processed. The kill switch -- the one control that must always be releasable
-- is bricked by a wrong button press.

stdlib + xstate_statemachine only. Exits 1 while the defect is present.
Run from any cwd, e.g.  cd C:/Users/basil && python <this file>
"""
from __future__ import annotations
import asyncio, json, sys

from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "kill_switch",
    "actionErrorPolicy": "rollback",
    "onUnhandled": "error",          # <-- C-07b: still on B18
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "strict": True,
    "initial": "clear",
    "context": {"released": 0},
    "states": {
        "clear": {"tags": ["trading_allowed"],
                  "on": {"ENGAGE": {"target": "#kill_switch.engaged",
                                    "actions": ["record_engagement"]}}},
        "engaged": {
            "tags": ["trading_blocked"],
            "on": {"RELEASE": {"target": "#kill_switch.clear",
                               "guard": "owner_and_elevated",
                               "actions": ["audit_kill_switch_released"]}}},
    },
}


async def main():
    # the guard denies the first RELEASE, then permits the second
    allow = [False]

    def owner_and_elevated(ctx, evt):
        return allow[0]

    def record_engagement(i, c, e, a):
        pass

    def audit_kill_switch_released(i, c, e, a):
        c["released"] = c.get("released", 0) + 1

    m = create_machine(
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(
            actions={"record_engagement": record_engagement,
                     "audit_kill_switch_released": audit_kill_switch_released},
            guards={"owner_and_elevated": owner_and_elevated},
            strict=True),
        strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()

    log = []

    async def step(ev, note):
        try:
            await asyncio.wait_for(i.send(ev), 5)
            out = "accepted"
        except Exception as exc:
            out = "raised %s: %s" % (type(exc).__name__, str(exc)[:110])
        await asyncio.sleep(0.05)
        row = {"step": note, "event": ev, "send": out,
               "states": sorted(i.current_state_ids),
               "status": i.status,
               "last_error": type(i.last_error).__name__ if i.last_error else None}
        log.append(row)
        print(json.dumps(row))

    await step("ENGAGE", "engage the kill switch")
    await step("RELEASE", "WRONG operator presses RELEASE (guard denies)")
    allow[0] = True
    await step("RELEASE", "the properly elevated operator now releases")

    released = i.context.get("released", 0)
    final = sorted(i.current_state_ids)
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass

    bricked = final != ["kill_switch.clear"] or released != 1
    print()
    if bricked:
        print("!! C-07b PRESENT: after a guard-denied RELEASE the legitimate "
              "RELEASE did not take. final=%s released=%d" % (final, released))
    else:
        print("C-07b FIXED: the denied RELEASE was inert and the legitimate "
              "one released the switch. final=%s released=%d" % (final, released))
    return 1 if bricked else 0


sys.exit(asyncio.run(main()))
