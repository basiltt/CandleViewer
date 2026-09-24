# -*- coding: utf-8 -*-
"""D4: the two OUR-CONTRACT catalogue Blockers, re-read from the corrected JSON.

C-04  (B16 `session`)  -- does a privilege elevation survive LOGOUT / REVOKE?
C-07b (B18 kill switch) -- does `onUnhandled: "error"` still sit on B18, so a
      guard-denied RELEASE bricks the kill switch?
Plus B18 send_priority under a runaway chain (#192): 0 external drops, kill
preempts.
"""
from __future__ import annotations
import asyncio, json
import cv78 as H
from xstate_statemachine import Interpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock


def static_c07b():
    c = H.cfg("B18")
    pol = c.get("onUnhandled", "<absent>")
    # C-07b is PRESENT if B18 still declares onUnhandled: error
    present = pol == "error"
    H.rec("D4/C-07b/onUnhandled-removed-from-B18", not present,
          "B18 onUnhandled=%r (C-07b %s)" % (pol, "PRESENT" if present else "fixed"))
    return c, pol


def static_c04():
    c = H.cfg("B16")
    txt = json.dumps(c)
    states = list(c.get("states", {}).keys())
    # C-04: an elevated state must be exited by LOGOUT and by REVOKE.
    elev = [s for s in states if "elev" in s or "privile" in s or "admin" in s]
    info = {}
    for s in states:
        node = c["states"][s]
        info[s] = sorted((node.get("on") or {}).keys())
    has_logout = "LOGOUT" in txt
    has_revoke = "REVOKE" in txt
    H.RESULTS["[%s]D4/C-04/B16-shape" % H.STYLE] = {
        "pass": True, "note": json.dumps(
            {"states": info, "elevated_like": elev,
             "LOGOUT_in_chart": has_logout, "REVOKE_in_chart": has_revoke})}
    return c, elev, info, has_logout, has_revoke


async def c04_drive(c, elev, info):
    """B16 is PARALLEL: `elevation` is a region. C-04 asks whether an
    elevation survives an escape in the `auth` region."""
    tags = c["states"]["elevation"]["states"]["elevated"].get("tags", [])
    handled = sorted((c["states"]["elevation"]["states"]["elevated"].get("on") or {}).keys())
    H.rec("D4/C-04/elevated-handles-REVOKE", "REVOKE" in handled,
          "elevation.elevated handles %s" % handled)
    H.rec("D4/C-04/elevated-handles-LOGOUT", "LOGOUT" in handled,
          "elevation.elevated handles %s -- LOGOUT absent => elevation "
          "survives logout" % handled)
    outs = {}
    for esc in ("REVOKE", "LOGOUT"):
        st = H.Stub(c, guard_vals={"mfa_attempts_exhausted": False})
        r = await H.drive(c, st, ["MFA_OK", "STEP_UP_OK", esc], snapshots=False)
        still = "session.elevation.elevated" in r["states"]
        outs[esc] = {"states": r["states"], "actions": r["actions"][-5:],
                     "still_elevated": still}
        H.rec("D4/C-04/elevation-cleared-by-%s" % esc, not still,
              "after MFA_OK,STEP_UP_OK,%s -> %s (clear_elevated=%s)"
              % (esc, r["states"], "clear_elevated" in r["actions"]))
    H.RESULTS["[%s]D4/C-04/drive" % H.STYLE] = {"pass": True,
                                                "note": json.dumps(outs, default=str)}


# ---------------------------------------------- B18 priority under a chain --
CHAIN = {
    "id": "prio", "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "strictTargets": True, "strict": True, "maxIterations": 20,
    "initial": "run", "context": {"n": 0, "killed": 0},
    "states": {
        "run": {
            "on": {
                # self-generated runaway: each SPIN raises another SPIN
                "SPIN": {"actions": ["bump", {"type": "raise", "params": {"event": "SPIN"}}]},
                "EXT": {"actions": ["bump_ext"]},
                "KILL": {"target": "#prio.dead"},
            }
        },
        "dead": {"type": "final"},
    },
}


async def b18_priority():
    from xstate_statemachine import MachineLogic, create_machine
    seen = {"n": 0, "ext": 0}

    def bump(i, c, e, a):
        seen["n"] += 1

    def bump_ext(i, c, e, a):
        seen["ext"] += 1

    m = create_machine(json.loads(json.dumps(CHAIN)),
                       logic=MachineLogic(actions={"bump": bump,
                                                   "bump_ext": bump_ext},
                                          strict=True),
                       strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=4096,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.CvHooks(); i.use(p)
    await i.start()
    try:
        await asyncio.wait_for(i.send("SPIN"), 10)
    except Exception:
        pass
    # 60 EXTERNAL priority sends while the chain is tripped
    sent = 0
    for _ in range(60):
        try:
            await asyncio.wait_for(i.send("EXT", priority=True), 5)
            sent += 1
        except Exception as e:
            p.errors.append("extsend:%r" % (e,))
    await H.quiesce(i, 6)
    ext_drops = [d for d in p.dropped if d[0] == "EXT"]
    H.rec("D4/B18/external-priority-not-shed", not ext_drops,
          "sent=%d applied=%d dropped=%s (chain_budget drops of EXT)"
          % (sent, seen["ext"], ext_drops[:5]))
    H.rec("D4/B18/all-60-applied", seen["ext"] == 60,
          "applied=%d of 60" % seen["ext"])
    # kill must still preempt
    try:
        await asyncio.wait_for(i.send("KILL", priority=True), 5)
    except Exception:
        pass
    await H.quiesce(i, 4)
    H.rec("D4/B18/kill-preempts", H.ids(i) == ["prio.dead"],
          "states=%s chain_err=%s" % (
              H.ids(i), type(i.last_error).__name__ if i.last_error else None))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


async def main():
    static_c07b()
    c16, elev, info, hl, hr = static_c04()
    await c04_drive(c16, elev, info)
    await b18_priority()
    H.dump("h_d4_blockers.json")


asyncio.run(main())
