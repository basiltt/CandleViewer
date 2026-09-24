# -*- coding: utf-8 -*-
"""STANDALONE (C-07b, OUR-CONTRACT). B18 KillSwitch with onUnhandled:"error".

`engaged` handles RELEASE only behind `owner_and_elevated`.  When the guard
denies, NO transition is selected, so the event is "unhandled" and the
`"error"` policy makes it FATAL: status -> 'error'.  From then on a
*correctly authorised* RELEASE is accepted by send() (success-shaped) but the
machine never leaves `engaged` -- one wrong button press bricks the kill
switch in the trading-blocked state.

Both service spellings are exercised.  stdlib + xstate_statemachine only.
    python cv19_c07b_killswitch_bricked.py
"""
from __future__ import annotations
import asyncio, json
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "kill_switch", "initial": "clear",
    "actionErrorPolicy": "rollback", "onUnhandled": "error",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {},
    "states": {
        "clear": {"on": {"ENGAGE": {"target": "#kill_switch.cancelling"}}},
        "cancelling": {"invoke": {"id": "cx", "src": "cancel_all_working_orders",
                                  "onDone": {"target": "#kill_switch.engaged"},
                                  "onError": {"target": "#kill_switch.engaged"}}},
        "engaged": {"on": {"RELEASE": {"target": "#kill_switch.clear",
                                       "guard": "owner_and_elevated",
                                       "actions": ["audit_released"]}}},
    },
}


def build(kind, allow):
    if kind == "async def":
        async def cancel_all_working_orders(i, c, e): return {"ok": True}
    else:
        def cancel_all_working_orders(i, c, e): return {"ok": True}

    def audit_released(i, c, e, a): pass

    return create_machine(
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(
            actions={"audit_released": audit_released},
            guards={"owner_and_elevated": lambda c, e: allow["v"]},
            services={"cancel_all_working_orders": cancel_all_working_orders},
            strict=True),
        strict_targets=True)


async def settle(i, n=4):
    for _ in range(n):
        await asyncio.sleep(0.02)


async def run(kind):
    allow = {"v": False}
    i = Interpreter(build(kind, allow), clock=SimulatedClock())
    await i.start(); await settle(i)
    await i.send("ENGAGE"); await settle(i)
    engaged = sorted(i.current_state_ids)
    # 1. the operator presses RELEASE without elevation (ordinary mistake)
    denied_exc = None
    try:
        await i.send("RELEASE")
    except Exception as e:
        denied_exc = repr(e)
    await settle(i)
    after_denied = {"states": sorted(i.current_state_ids), "status": i.status,
                    "error": None if i.error is None else repr(i.error)}
    # 2. now properly elevated -- the REAL release
    allow["v"] = True
    ok_exc = None
    try:
        await i.send("RELEASE")
    except Exception as e:
        ok_exc = repr(e)
    await settle(i)
    final = sorted(i.current_state_ids)
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    return {"kind": kind, "engaged": engaged, "denied_send_exc": denied_exc,
            "after_denied": after_denied, "authorised_send_exc": ok_exc,
            "final": final, "bricked": final != ["kill_switch.clear"]}


async def main():
    rows = [await run("async def"), await run("def")]
    for r in rows:
        print(json.dumps(r))
    bad = [r["kind"] for r in rows if r["bricked"]]
    print("\nREPRODUCED" if bad else "\nNOT REPRODUCED",
          "- kill switch bricked (authorised RELEASE cannot land) on:", bad)


asyncio.run(main())
