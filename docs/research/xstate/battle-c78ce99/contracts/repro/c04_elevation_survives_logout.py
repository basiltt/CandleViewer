# -*- coding: utf-8 -*-
"""STANDALONE repro -- C-04: a privilege elevation SURVIVES logout.

OUR-CONTRACT defect in B16 `session` (not a library defect). The chart is a
parallel machine with an `auth` region and an `elevation` region.
`elevation.elevated` handles REVOKE but NOT LOGOUT, so after a clean logout
the session is auth.revoked (a FINAL, terminal-tagged state) while the
elevation region is still `elevated` and `clear_elevated` never ran.

Any code that authorises on the `elevated` tag rather than on auth liveness
grants admin rights on a logged-out session.

stdlib + xstate_statemachine only. Exits 1 while the defect is present.
Run from any cwd, e.g.  cd C:/Users/basil && python <this file>
"""
from __future__ import annotations
import asyncio, json, sys

from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

# --- the two regions of B16, reduced to exactly what C-04 is about ---------
CFG = {
    "id": "session",
    "actionErrorPolicy": "rollback",
    "onUnhandled": "defer",
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "strict": True,
    "type": "parallel",
    "context": {"elevated_until_us": None, "revoke_reason": None},
    "states": {
        "auth": {
            "initial": "pending_mfa",
            "states": {
                "pending_mfa": {
                    "on": {"MFA_OK": {"target": "#session.auth.active",
                                      "actions": ["mark_mfa_satisfied"]}}},
                "active": {
                    "entry": ["audit_login"],
                    "on": {
                        "REVOKE": {"target": "#session.auth.revoked",
                                   "actions": ["set_revoke_admin"]},
                        # LOGOUT is handled HERE, in the auth region only
                        "LOGOUT": {"target": "#session.auth.revoked",
                                   "actions": ["set_revoke_logout"]},
                    }},
                "revoked": {"type": "final", "tags": ["terminal"],
                            "entry": ["audit_session_revoked"]},
            }},
        "elevation": {
            "initial": "normal",
            "states": {
                "normal": {"tags": ["not_elevated"],
                           "on": {"STEP_UP_OK": {
                               "target": "#session.elevation.elevated",
                               "actions": ["stamp_elevated_until"]}}},
                "elevated": {
                    "tags": ["elevated"],
                    "entry": ["schedule_elevation_deadline"],
                    "on": {
                        # REVOKE clears it ... LOGOUT is ABSENT. That is C-04.
                        "REVOKE": {"target": "#session.elevation.normal",
                                   "actions": ["clear_elevated"]},
                        "ELEVATION_DEADLINE": {
                            "target": "#session.elevation.normal",
                            "actions": ["clear_elevated"]},
                    }},
            }},
    },
}

ACTIONS = ["mark_mfa_satisfied", "audit_login", "set_revoke_admin",
           "set_revoke_logout", "audit_session_revoked", "stamp_elevated_until",
           "schedule_elevation_deadline", "clear_elevated"]


def logic(seen):
    def mk(n):
        def f(i, c, e, a):
            seen.append(n)
            if n == "stamp_elevated_until":
                c["elevated_until_us"] = 1
            if n == "clear_elevated":
                c["elevated_until_us"] = None
        f.__name__ = n
        return f
    return MachineLogic(actions={n: mk(n) for n in ACTIONS}, strict=True)


async def run(escape):
    seen = []
    m = create_machine(json.loads(json.dumps(CFG)), logic=logic(seen),
                       strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    for ev in ("MFA_OK", "STEP_UP_OK", escape):
        try:
            await asyncio.wait_for(i.send(ev), 5)
        except Exception as exc:
            seen.append("send(%s) raised %r" % (ev, exc))
        await asyncio.sleep(0.05)
    states = sorted(i.current_state_ids)
    ctx = dict(i.context)
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    return {"escape": escape, "states": states,
            "still_elevated": "session.elevation.elevated" in states,
            "elevated_until_us": ctx.get("elevated_until_us"),
            "clear_elevated_ran": "clear_elevated" in seen}


async def main():
    bad = 0
    for escape in ("REVOKE", "LOGOUT"):
        r = await run(escape)
        print(json.dumps(r, indent=1))
        if r["still_elevated"]:
            bad += 1
            print("  !! C-04: after %s the session is auth.revoked (FINAL) but "
                  "elevation is STILL `elevated`; clear_elevated did not run "
                  "and elevated_until_us=%r\n" % (escape, r["elevated_until_us"]))
        else:
            print("  ok: %s clears the elevation\n" % escape)
    print("C-04 PRESENT" if bad else "C-04 FIXED")
    return 1 if bad else 0


sys.exit(asyncio.run(main()))
