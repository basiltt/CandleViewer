# -*- coding: utf-8 -*-
"""B16 AuthSession: happy path + INV-B16-a..e, snapshot parity."""
import asyncio, json
import cdrv
from cdrv import run_plain, run_snapshotted, compare, run_sync_parity

R = {}

async def main():
    # --- happy path: MFA -> active -> step up -> elevated ---------------
    seq = ["MFA_OK", "REQUEST", "STEP_UP_OK", "REQUEST"]
    R["happy"] = await run_plain("B16", seq)

    # --- INV-B16-a: elevation cannot outlive the session ---------------
    # REVOKE while elevated: both regions must react.
    seq_a = ["MFA_OK", "STEP_UP_OK", "REVOKE"]
    R["inv_a"] = await run_plain("B16", seq_a)

    # same via LOGOUT / IDLE_DEADLINE / ABSOLUTE_DEADLINE (no elevation clause)
    for ev in ["LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE"]:
        R[f"inv_a_{ev}"] = await run_plain("B16", ["MFA_OK", "STEP_UP_OK", ev])

    # --- INV-B16-b: revocation reason recorded, broadcast ---------------
    R["inv_b"] = {ev: (await run_plain("B16", ["MFA_OK", ev]))["acts"]
                  for ev in ["REVOKE", "LOGOUT", "IDLE_DEADLINE",
                             "ABSOLUTE_DEADLINE"]}
    R["inv_b_mfa"] = (await run_plain(
        "B16", ["MFA_TIMEOUT"]))["acts"]
    R["inv_b_locked"] = (await run_plain(
        "B16", ["MFA_FAILED"],
        stub_kw={"guard_vals": {"mfa_attempts_exhausted": True}}))["acts"]
    R["inv_b_retry"] = (await run_plain(
        "B16", ["MFA_FAILED", "MFA_FAILED", "MFA_OK"],
        stub_kw={"guard_vals": {"mfa_attempts_exhausted": False}}))["acts"]

    # --- INV-B16-c: every step-up attempt audited ----------------------
    R["inv_c"] = (await run_plain(
        "B16", ["MFA_OK", "STEP_UP_FAILED", "STEP_UP_OK", "STEP_UP_OK"]))["acts"]

    # --- INV-B16-d: revoked is terminal; never un-revoked --------------
    R["inv_d"] = await run_plain("B16", ["MFA_OK", "REVOKE", "MFA_OK",
                                          "REQUEST", "STEP_UP_OK"])

    # --- snapshot at quiescence between every macrostep ----------------
    for name, s in [("happy", seq), ("inv_a", seq_a),
                    ("inv_d", ["MFA_OK", "REVOKE", "REQUEST"])]:
        snap = await run_snapshotted("B16", s)
        plain = await run_plain("B16", s)
        R[f"snap_{name}"] = {
            "midstep_errors": snap["midstep_errors"],
            "diffs": compare(plain, snap),
            "ids": snap["ids"],
        }

    R["sync_parity"] = run_sync_parity("B16", seq)

asyncio.run(main())
print(json.dumps(R, indent=2, default=str))
json.dump(R, open("results/c1_b16.json", "w", encoding="utf-8"), indent=2, default=str)
