# -*- coding: utf-8 -*-
"""STANDALONE: R10-C1 correct-usage control. Same B16 shape, but the
elevation region also handles LOGOUT/IDLE_DEADLINE/ABSOLUTE_DEADLINE, and we
also test re-elevation of a dead session (STEP_UP_OK after LOGOUT)."""
import asyncio, os, sys, copy
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
STYLE = os.environ.get("CV", "async")
KILLS = ("LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE", "REVOKE")
def cfg(fixed):
    elev_on = {
        "ELEVATION_DEADLINE": {"target": "#session.elevation.normal", "actions": ["clear_elevated"]},
        "REVOKE": {"target": "#session.elevation.normal", "actions": ["clear_elevated"]},
    }
    norm_on = {"STEP_UP_OK": {"target": "#session.elevation.elevated",
                              "actions": ["stamp_elevated_until", "audit_step_up"]}}
    if fixed:
        for k in ("LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE"):
            elev_on[k] = {"target": "#session.elevation.normal", "actions": ["clear_elevated"]}
        norm_on["STEP_UP_OK"] = [
            {"target": "#session.elevation.elevated", "guard": "session_alive",
             "actions": ["stamp_elevated_until", "audit_step_up"]},
            {"actions": ["audit_step_up_denied"]},
        ]
    auth_on = {k: {"target": "#session.auth.revoked", "actions": ["set_revoke"]} for k in KILLS}
    return {"id": "session", "type": "parallel", "actionErrorPolicy": "rollback",
            "onUnhandled": "defer", "guardErrorPolicy": "raise",
            "strictTargets": True, "strict": True,
            "context": {"elevated_until_us": None, "revoke_reason": None},
            "states": {
              "auth": {"initial": "pending_mfa", "states": {
                "pending_mfa": {"on": {"MFA_OK": {"target": "#session.auth.active"}}},
                "active": {"on": auth_on},
                "revoked": {"type": "final", "entry": ["audit_session_revoked"]}}},
              "elevation": {"initial": "normal", "states": {
                "normal": {"on": norm_on},
                "elevated": {"entry": ["schedule_elevation_deadline"], "on": elev_on}}}}}
ACTS = ("set_revoke", "audit_session_revoked", "stamp_elevated_until",
        "audit_step_up", "audit_step_up_denied", "schedule_elevation_deadline",
        "clear_elevated")
def mk(n, is_async):
    if is_async:
        async def f(i, c, e, a):
            body(n, c, e)
    else:
        def f(i, c, e, a):
            body(n, c, e)
    f.__name__ = n
    return f
def body(n, c, e):
    if n == "stamp_elevated_until": c["elevated_until_us"] = 9_999_999
    if n == "clear_elevated": c["elevated_until_us"] = None
    if n == "set_revoke": c["revoke_reason"] = getattr(e, "type", "?")
def alive(i, c, e):  # guard
    return c.get("revoke_reason") is None
async def run(fixed, kill):
    isa = STYLE == "async"
    logic = MachineLogic(actions={n: mk(n, isa) for n in ACTS},
                         guards={"session_alive": alive}, strict=True)
    i = Interpreter(create_machine(copy.deepcopy(cfg(fixed)), logic=logic,
                                   strict_targets=True), clock=SimulatedClock())
    await i.start()
    for ev in ("MFA_OK", "STEP_UP_OK"):
        await i.send(ev); await asyncio.sleep(0.1)
    await i.send(kill)
    for _ in range(30):  # poll to convergence
        await asyncio.sleep(0.02)
        if "session.auth.revoked" in set(i.current_state_ids): break
    after = sorted(i.current_state_ids)
    # re-elevation of a dead session
    await i.send("STEP_UP_OK"); await asyncio.sleep(0.2)
    re_el = "session.elevation.elevated" in set(i.current_state_ids)
    out = (sorted(after), re_el, i.context.get("elevated_until_us"))
    try: await asyncio.wait_for(i.stop(), 5)
    except Exception: pass
    return out
async def main():
    for fixed in (False, True):
        for kill in KILLS:
            after, re_el, eu = await run(fixed, kill)
            still = "session.elevation.elevated" in after
            print("style=%s fixed=%-5s kill=%-18s still_elevated=%-5s "
                  "re_elevated_dead=%-5s eu=%r" % (STYLE, fixed, kill, still, re_el, eu))
asyncio.run(main())
