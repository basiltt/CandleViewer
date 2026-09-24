# -*- coding: utf-8 -*-
"""B16 AuthSession + B17 LiveEnablement: happy path, invariants, snapshots."""
import asyncio, json
from cdrv import run_plain, run_snapshotted, compare, run_sync_parity
from xstate_statemachine import OverflowPolicy

R = {}
CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)

async def main():
    # ---------------- B16 ----------------
    seq = ["MFA_OK", "REQUEST", "STEP_UP_OK", "REQUEST"]
    R["b16_happy"] = await run_plain("B16", seq)
    # INV-B16-a: elevation must not outlive the session
    for ev in ["REVOKE", "LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE"]:
        R["b16_inv_a_" + ev] = await run_plain("B16", ["MFA_OK", "STEP_UP_OK", ev])
    # INV-B16-b reasons
    R["b16_inv_b"] = {ev: (await run_plain("B16", ["MFA_OK", ev]))["acts"]
                      for ev in ["REVOKE", "LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE"]}
    R["b16_inv_b_timeout"] = (await run_plain("B16", ["MFA_TIMEOUT"]))["acts"]
    R["b16_inv_b_locked"] = (await run_plain(
        "B16", ["MFA_FAILED"], stub_kw={"guard_vals": {"mfa_attempts_exhausted": True}}))["acts"]
    # INV-B16-c step-up audit
    R["b16_inv_c"] = (await run_plain(
        "B16", ["MFA_OK", "STEP_UP_FAILED", "STEP_UP_OK", "STEP_UP_OK"]))["acts"]
    # INV-B16-d revoked terminal / elevation after revocation
    R["b16_inv_d"] = await run_plain(
        "B16", ["MFA_OK", "REVOKE", "MFA_OK", "REQUEST", "STEP_UP_OK"])
    # snapshots at quiescence
    for name, s in [("happy", seq), ("revoke", ["MFA_OK", "STEP_UP_OK", "REVOKE"]),
                    ("term", ["MFA_OK", "REVOKE", "REQUEST"])]:
        snap = await run_snapshotted("B16", s); plain = await run_plain("B16", s)
        R["b16_snap_" + name] = {"midstep": snap["midstep_errors"],
                                 "diffs": compare(plain, snap),
                                 "trace_eq": plain["transitions"] == snap["transitions"],
                                 "ids": snap["ids"]}
    R["b16_sync"] = run_sync_parity("B16", seq)

    # ---------------- B17 ----------------
    GV = {"all_evidence_present": True,
          "owner_and_elevated_and_evidence_still_valid": True,
          "owner_and_elevated": True}
    R["b17_happy"] = await run_plain(
        "B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "DISABLE_REQUESTED"],
        stub_kw={"guard_vals": GV}, **CTL)
    # INV-B17-b: 2FA + pen-test gate -> denied when not elevated
    R["b17_denied"] = await run_plain(
        "B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"],
        stub_kw={"guard_vals": dict(GV, owner_and_elevated_and_evidence_still_valid=False)},
        **CTL)
    # evidence incomplete -> stays locked, ENABLE_REQUESTED is undeclared in locked
    R["b17_locked_enable"] = await run_plain(
        "B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "EVIDENCE_RECORDED"],
        stub_kw={"guard_vals": {"all_evidence_present": False}}, **CTL)
    R["b17_locked_enable_then_ok"] = await run_plain(
        "B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"],
        stub_kw={"guard_vals": {"all_evidence_present": False,
                                "owner_and_elevated_and_evidence_still_valid": True}},
        **CTL)
    # INV-B17-c/d
    R["b17_inv_c"] = await run_plain(
        "B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "EVIDENCE_INVALIDATED"],
        stub_kw={"guard_vals": GV}, **CTL)
    R["b17_inv_d"] = await run_plain(
        "B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "EMERGENCY_DISABLE"],
        stub_kw={"guard_vals": dict(GV, owner_and_elevated=False)}, **CTL)
    # rollback on action raise (replaces withdrawn "fail")
    R["b17_rollback"] = await run_plain(
        "B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"],
        stub_kw={"guard_vals": GV, "raising": ["audit_live_enabled"]}, **CTL)
    for name, s in [("happy", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "DISABLE_REQUESTED"]),
                    ("invalidate", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "EVIDENCE_INVALIDATED"])]:
        snap = await run_snapshotted("B17", s, stub_kw={"guard_vals": GV}, **CTL)
        plain = await run_plain("B17", s, stub_kw={"guard_vals": GV}, **CTL)
        R["b17_snap_" + name] = {"midstep": snap["midstep_errors"],
                                 "diffs": compare(plain, snap),
                                 "trace_eq": plain["transitions"] == snap["transitions"]}
    R["b17_sync"] = run_sync_parity(
        "B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"], stub_kw={"guard_vals": GV})

asyncio.run(main())
json.dump(R, open("results/k1_b16_b17.json", "w", encoding="utf-8"), indent=2, default=str)
print(json.dumps(R, indent=1, default=str)[:7000])
