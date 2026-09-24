# -*- coding: utf-8 -*-
"""m3: B16-B20 happy path + every catalogue invariant + snapshot/restore at
EVERY quiescence, run twice (CV_SVC_STYLE=async then def).

Uses cv19.py (the round harness copied unchanged from battle-6db65d8), which
snapshots and restores at every quiescence point and compares states+context.
"""
from __future__ import annotations
import asyncio, json, os, sys

os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
STYLE = os.environ["CV_SVC_STYLE"]

import cvde as H
from cvde import Stub


def S(c, **kw):
    kw.setdefault("svc_style", STYLE)
    return Stub(c, **kw)


def leaves(out):
    return [s.split(".", 1)[1] for s in out["states"]]


def rec(n, ok, note=""):
    return H.rec(n, ok, note)


# ===================================================================== B16 ==
async def b16():
    c = H.cfg("B16")
    o = await H.drive(c, S(c), ["MFA_OK", "REQUEST", "STEP_UP_OK", "REQUEST"])
    rec("B16/happy", set(leaves(o)) == {"auth.active", "elevation.elevated"}
        and o["snapshot_ok"],
        json.dumps({"st": o["states"], "snap": o["snapshot_ok"],
                    "notes": o["notes"]}))

    # INV-B16-a: elevation must not outlive the session
    inv_a = {}
    for ev in ["REVOKE", "LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE"]:
        oo = await H.drive(c, S(c), ["MFA_OK", "STEP_UP_OK", ev])
        inv_a[ev] = leaves(oo)
    still = [e for e, v in inv_a.items() if "elevation.elevated" in v]
    rec("B16/INV-a elevation dies with session", not still,
        "still elevated after: %s  (%s)" % (still, json.dumps(inv_a)))

    # INV-B16-b: every revocation records a reason + broadcasts
    inv_b = {}
    for ev, act in [("REVOKE", "set_revoke_admin"), ("LOGOUT", "set_revoke_logout"),
                    ("IDLE_DEADLINE", "set_revoke_idle"),
                    ("ABSOLUTE_DEADLINE", "set_revoke_expired")]:
        oo = await H.drive(c, S(c), ["MFA_OK", ev])
        inv_b[ev] = (act in oo["actions"],
                     "broadcast_revocation" in oo["actions"])
    oo = await H.drive(c, S(c), ["MFA_TIMEOUT"])
    inv_b["MFA_TIMEOUT"] = ("set_revoke_timeout" in oo["actions"],
                            "broadcast_revocation" in oo["actions"])
    oo = await H.drive(c, S(c), ["MFA_FAILED"],
                       )  # guard false -> no revoke
    oo2 = await H.drive(c, S(c, guard_vals={"mfa_attempts_exhausted": True}),
                        ["MFA_FAILED"])
    inv_b["MFA_LOCKED"] = ("set_revoke_locked" in oo2["actions"],
                           "broadcast_revocation" in oo2["actions"])
    rec("B16/INV-b reason+broadcast on 6 paths",
        all(a and b for a, b in inv_b.values()), json.dumps(inv_b))

    # INV-B16-c: every step-up audited
    oo = await H.drive(c, S(c), ["MFA_OK", "STEP_UP_FAILED", "STEP_UP_OK",
                                 "STEP_UP_OK"])
    n_ok = 2
    rec("B16/INV-c every step-up audited",
        oo["actions"].count("audit_step_up") == n_ok,
        "audit_step_up=%d for %d STEP_UP_OK; acts=%s"
        % (oo["actions"].count("audit_step_up"), n_ok, oo["actions"]))

    # INV-B16-d: revoked is terminal; no elevation after revocation
    oo = await H.drive(c, S(c), ["MFA_OK", "REVOKE", "MFA_OK", "REQUEST",
                                 "STEP_UP_OK"])
    rec("B16/INV-d revoked terminal, no post-revoke elevation",
        "auth.revoked" in leaves(oo) and "elevation.elevated" not in leaves(oo),
        json.dumps({"st": oo["states"], "unh": oo["unhandled"]}))

    # rollback on a raising audit action
    oo = await H.drive(c, S(c, raising=["audit_login"]), ["MFA_OK"])
    rec("B16/rollback on entry raise",
        "auth.pending_mfa" in leaves(oo),
        json.dumps({"st": oo["states"], "err": oo["action_errors"][:2]}))

    # sync parity
    so = H.drive_sync(c, S(c), ["MFA_OK", "REQUEST", "STEP_UP_OK", "REQUEST"])
    rec("B16/sync parity",
        set(so["states"]) == {"session.auth.active",
                              "session.elevation.elevated"},
        json.dumps({"st": so["states"], "err": so["error"]}))


# ===================================================================== B17 ==
async def b17():
    c = H.cfg("B17")
    GV = {"all_evidence_present": True,
          "owner_and_elevated_and_evidence_still_valid": True,
          "owner_and_elevated": True}
    o = await H.drive(c, S(c, guard_vals=dict(GV)),
                      ["EVIDENCE_RECORDED", "ENABLE_REQUESTED",
                       "DISABLE_REQUESTED"])
    rec("B17/happy", leaves(o) == ["eligible"] and o["snapshot_ok"],
        json.dumps({"st": o["states"], "snap": o["snapshot_ok"],
                    "notes": o["notes"]}))

    # INV-B17-a: cannot enable from locked (evidence incomplete)
    o2 = await H.drive(c, S(c, guard_vals={"all_evidence_present": False,
                                           "owner_and_elevated_and_evidence_still_valid": True}),
                       ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"])
    rec("B17/INV-a no enable without evidence",
        leaves(o2) == ["locked"] and "record_enable" not in o2["actions"],
        json.dumps({"st": o2["states"], "unh": o2["unhandled"],
                    "def": o2["deferred"]}))

    # INV-B17-b: denied without owner+elevation
    o3 = await H.drive(c, S(c, guard_vals=dict(
        GV, owner_and_elevated_and_evidence_still_valid=False)),
        ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"])
    rec("B17/INV-b denial audited, stays eligible",
        leaves(o3) == ["eligible"] and "audit_enable_denied" in o3["actions"],
        json.dumps({"st": o3["states"], "acts": o3["actions"]}))

    # INV-B17-c: invalidated evidence drops live immediately + alerts
    o4 = await H.drive(c, S(c, guard_vals=dict(GV)),
                       ["EVIDENCE_RECORDED", "ENABLE_REQUESTED",
                        "EVIDENCE_INVALIDATED"])
    rec("B17/INV-c invalidation -> locked + alert",
        leaves(o4) == ["locked"] and "raise_critical_alert" in o4["actions"],
        json.dumps({"st": o4["states"], "acts": o4["actions"][-4:]}))

    # INV-B17-d: emergency disable needs no elevation
    o5 = await H.drive(c, S(c, guard_vals=dict(GV, owner_and_elevated=False)),
                       ["EVIDENCE_RECORDED", "ENABLE_REQUESTED",
                        "EMERGENCY_DISABLE"])
    rec("B17/INV-d emergency disable unguarded",
        leaves(o5) == ["locked"], json.dumps({"st": o5["states"]}))

    # INV-B17-e: rollback leaves the gate where it was
    o6 = await H.drive(c, S(c, guard_vals=dict(GV),
                            raising=["audit_live_enabled"]),
                       ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"])
    rec("B17/INV-e rollback keeps gate shut",
        leaves(o6) == ["eligible"]
        and "broadcast_live_enabled" not in o6["actions"],
        json.dumps({"st": o6["states"], "acts": o6["actions"]}))

    so = H.drive_sync(c, S(c, guard_vals=dict(GV)),
                      ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"])
    rec("B17/sync parity", so["states"] == ["live_gate.enabled"],
        json.dumps({"st": so["states"], "err": so["error"]}))


async def main():
    await b16()
    await b17()
    H.dump("results/p1_b16_b17.json")


asyncio.run(main())
