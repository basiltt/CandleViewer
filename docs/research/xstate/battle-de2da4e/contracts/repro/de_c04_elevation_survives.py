# -*- coding: utf-8 -*-
"""STANDALONE (C-04, OUR-CONTRACT). B16 AuthSession: the `elevation` region
only listens for REVOKE, so LOGOUT / IDLE_DEADLINE / ABSOLUTE_DEADLINE revoke
the session while leaving the parallel region in `elevated`.  A revoked
session still carries elevated privileges.

stdlib + xstate_statemachine only; runs from any cwd.
    python cv19_c04_elevation_survives.py
"""
from __future__ import annotations
import asyncio, json
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "session", "type": "parallel",
    "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {"revoke_reason": None},
    "states": {
        "auth": {
            "initial": "pending_mfa",
            "states": {
                "pending_mfa": {"on": {"MFA_OK": {"target": "#session.auth.active"}}},
                "active": {"on": {
                    "IDLE_DEADLINE": {"target": "#session.auth.revoked",
                                      "actions": ["set_revoke_idle"]},
                    "ABSOLUTE_DEADLINE": {"target": "#session.auth.revoked",
                                          "actions": ["set_revoke_expired"]},
                    "REVOKE": {"target": "#session.auth.revoked",
                               "actions": ["set_revoke_admin"]},
                    "LOGOUT": {"target": "#session.auth.revoked",
                               "actions": ["set_revoke_logout"]}}},
                "revoked": {"type": "final"},
            },
        },
        "elevation": {
            "initial": "normal",
            "states": {
                "normal": {"on": {"STEP_UP_OK": {"target": "#session.elevation.elevated"}}},
                "elevated": {"on": {
                    # NOTE: REVOKE only.  LOGOUT / the two deadlines are absent.
                    "REVOKE": {"target": "#session.elevation.normal"}}},
            },
        },
    },
}

ACTS = ["set_revoke_idle", "set_revoke_expired", "set_revoke_admin",
        "set_revoke_logout"]


def logic():
    def mk(n):
        def f(i, c, e, a): c["revoke_reason"] = n
        f.__name__ = n
        return f
    return MachineLogic(actions={n: mk(n) for n in ACTS}, strict=True)


async def once(kill_event):
    m = create_machine(json.loads(json.dumps(CFG)), logic=logic(),
                       strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    for ev in ("MFA_OK", "STEP_UP_OK", kill_event):
        await i.send(ev)
        for _ in range(3):
            await asyncio.sleep(0.02)
    states = sorted(i.current_state_ids)
    ctx = dict(i.context)
    await i.stop()
    return {"kill": kill_event, "states": states,
            "revoke_reason": ctx.get("revoke_reason"),
            "still_elevated": "session.elevation.elevated" in states}


async def main():
    rows = [await once(e) for e in
            ("REVOKE", "LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE")]
    for r in rows:
        print(json.dumps(r))
    bad = [r["kill"] for r in rows if r["still_elevated"]]
    print("\nREPRODUCED" if bad else "\nNOT REPRODUCED",
          "- session revoked but STILL ELEVATED after:", bad)


asyncio.run(main())
