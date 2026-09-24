# -*- coding: utf-8 -*-
"""STANDALONE: is our catalogue Blocker C-04 still present on 19cb1f1?

C-04: B16 `session` is a parallel chart with an `auth` region and an
`elevation` region.  `elevation.elevated` handles `REVOKE` (drops to
`normal`) but has NO handler for `LOGOUT`.  So a logout revokes the auth
region while the elevation region stays `elevated` -- an authorisation
predicate written as "is the `elevated` tag present" grants privilege on a
dead session.

Runs B16's exact corrected shape (inlined) with CV=async|def.
Case 1: STEP_UP_OK then LOGOUT.   Case 2: STEP_UP_OK then REVOKE (control).
stdlib + xstate_statemachine only.
"""
import asyncio, os, sys
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

STYLE = os.environ.get("CV", "async")

CFG = {
    "id": "session", "type": "parallel",
    "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {"user_id": None, "elevated_until_us": None,
                "mfa_satisfied": False, "revoke_reason": None,
                "mfa_attempts": 0},
    "states": {
        "auth": {"initial": "pending_mfa", "states": {
            "pending_mfa": {"on": {
                "MFA_OK": {"target": "#session.auth.active",
                           "actions": ["mark_mfa_satisfied"]},
                "MFA_TIMEOUT": {"target": "#session.auth.revoked",
                                "actions": ["set_revoke_timeout"]}}},
            "active": {
                "entry": ["stamp_idle_deadline", "audit_login"],
                "on": {
                    "REVOKE": {"target": "#session.auth.revoked",
                               "actions": ["set_revoke_admin"]},
                    "LOGOUT": {"target": "#session.auth.revoked",
                               "actions": ["set_revoke_logout"]}}},
            "revoked": {"type": "final", "tags": ["terminal"],
                        "entry": ["audit_session_revoked",
                                  "broadcast_revocation"]}}},
        "elevation": {"initial": "normal", "states": {
            "normal": {"tags": ["not_elevated"], "on": {
                "STEP_UP_OK": {"target": "#session.elevation.elevated",
                               "actions": ["stamp_elevated_until",
                                           "audit_step_up"]}}},
            "elevated": {"tags": ["elevated"],
                         "entry": ["schedule_elevation_deadline"],
                         "on": {
                             "ELEVATION_DEADLINE": {
                                 "target": "#session.elevation.normal",
                                 "actions": ["clear_elevated"]},
                             # NOTE: REVOKE is handled, LOGOUT is NOT.
                             "REVOKE": {
                                 "target": "#session.elevation.normal",
                                 "actions": ["clear_elevated"]}}}}},
    },
}

ACTS = ("mark_mfa_satisfied", "set_revoke_timeout", "stamp_idle_deadline",
        "audit_login", "set_revoke_admin", "set_revoke_logout",
        "audit_session_revoked", "broadcast_revocation",
        "stamp_elevated_until", "audit_step_up",
        "schedule_elevation_deadline", "clear_elevated")


def mk(n):
    def f(i, c, e, a):
        if n == "stamp_elevated_until":
            c["elevated_until_us"] = 9_999_999
        if n == "clear_elevated":
            c["elevated_until_us"] = None
        if n.startswith("set_revoke_"):
            c["revoke_reason"] = n[len("set_revoke_"):]
    f.__name__ = n
    return f


def tags_of(i):
    out = set()
    for n in i.current_state_nodes if hasattr(i, "current_state_nodes") else []:
        out |= set(getattr(n, "tags", ()) or ())
    return sorted(out)


async def run(kill_event):
    logic = MachineLogic(actions={n: mk(n) for n in ACTS}, strict=True)
    i = Interpreter(create_machine(CFG, logic=logic, strict_targets=True),
                    clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.15)
    for ev in ("MFA_OK", "STEP_UP_OK"):
        await i.send(ev)
        await asyncio.sleep(0.15)
    before = sorted(i.current_state_ids)
    await i.send(kill_event)
    await asyncio.sleep(0.3)
    after = sorted(i.current_state_ids)
    res = {"kill": kill_event, "before": before, "after": after,
           "tags": tags_of(i), "deferred": i.deferred_count,
           "elevated_until_us": i.context.get("elevated_until_us"),
           "revoke_reason": i.context.get("revoke_reason"),
           "status": i.status}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    return res


async def main():
    bad = []
    for ev in ("LOGOUT", "REVOKE"):
        r = await run(ev)
        still = "session.elevation.elevated" in r["after"]
        print("style=%s kill=%-7s after=%s" % (STYLE, ev, r["after"]))
        print("   tags=%s elevated_until_us=%r revoke_reason=%r deferred=%d "
              "status=%s" % (r["tags"], r["elevated_until_us"],
                             r["revoke_reason"], r["deferred"], r["status"]))
        print("   STILL_ELEVATED_AFTER_%s=%s" % (ev, still))
        if ev == "LOGOUT" and still:
            bad.append("elevation survives LOGOUT")
        if ev == "REVOKE" and still:
            bad.append("elevation survives REVOKE")
    print("C-04 PRESENT=%s  %s" % (bool(bad), "; ".join(bad) or "-"))
    sys.exit(1 if bad else 0)


asyncio.run(main())
