# -*- coding: utf-8 -*-
"""s3: B16-B20 happy paths + catalogue invariants + snapshot-every-macrostep,
run for BOTH service kinds, plus sync-engine parity."""
import asyncio, json, logging
logging.disable(logging.CRITICAL)
from d import run_plain, run_snapshotted, compare, run_sync_parity

R = {}
GV17 = {"all_evidence_present": True,
        "owner_and_elevated_and_evidence_still_valid": True,
        "owner_and_elevated": True}
GOK18 = {"cancel_working_requested": True, "flatten_requested": True,
         "all_accounts_flat": True, "owner_and_elevated": True,
         "owner_and_elevated_and_acknowledged_residual": True}
GV19 = {"auto_remediate_allowed": True, "should_backoff": True,
        "too_many_failures": False}


async def pair(name, b, seq, stub_kw=None, snap=False, **kw):
    out = {}
    for kind in ("async", "sync"):
        out[kind] = await run_plain(b, seq, kind=kind, stub_kw=stub_kw, **kw)
        if snap:
            s = await run_snapshotted(b, seq, kind=kind, stub_kw=stub_kw, **kw)
            out[kind + "_snap"] = {
                "midstep": s["midstep_errors"], "raised": s["raised"],
                "diffs": compare(out[kind], s),
                "trace_eq": out[kind]["transitions"] == s["transitions"],
                "ids": s["ids"]}
    out["kind_parity"] = compare(out["async"], out["sync"])
    out["acts_eq"] = out["async"]["acts"] == out["sync"]["acts"]
    R[name] = out
    print(name, "parity_ok=", not out["kind_parity"], "acts_eq=", out["acts_eq"],
          out["async"]["ids"], flush=True)


async def main():
    await pair("b16_happy", "B16", ["MFA_OK", "REQUEST", "STEP_UP_OK", "REQUEST"],
               snap=True)
    for ev in ["REVOKE", "LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE"]:
        await pair("b16_inv_a_" + ev, "B16", ["MFA_OK", "STEP_UP_OK", ev])
    await pair("b16_inv_c", "B16",
               ["MFA_OK", "STEP_UP_FAILED", "STEP_UP_OK", "STEP_UP_OK"])
    await pair("b16_inv_d", "B16",
               ["MFA_OK", "REVOKE", "MFA_OK", "REQUEST", "STEP_UP_OK"], snap=True)
    await pair("b16_locked", "B16", ["MFA_FAILED"],
               stub_kw={"guard_vals": {"mfa_attempts_exhausted": True}})

    await pair("b17_happy", "B17",
               ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "DISABLE_REQUESTED"],
               stub_kw={"guard_vals": GV17}, snap=True)
    await pair("b17_denied", "B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"],
               stub_kw={"guard_vals": dict(
                   GV17, owner_and_elevated_and_evidence_still_valid=False)})
    await pair("b17_inv_c", "B17",
               ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "EVIDENCE_INVALIDATED"],
               stub_kw={"guard_vals": GV17}, snap=True)
    await pair("b17_inv_d", "B17",
               ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "EMERGENCY_DISABLE"],
               stub_kw={"guard_vals": dict(GV17, owner_and_elevated=False)})
    await pair("b17_rollback", "B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"],
               stub_kw={"guard_vals": GV17, "raising": ["audit_live_enabled"]})
    await pair("b17_stale_replay", "B17", ["ENABLE_REQUESTED", "EVIDENCE_RECORDED"],
               stub_kw={"guard_vals": GV17})

    await pair("b18_happy", "B18", ["ENGAGE"],
               stub_kw={"guard_vals": GOK18}, snap=True)
    await pair("b18_incomplete", "B18", ["ENGAGE"],
               stub_kw={"guard_vals": dict(GOK18, all_accounts_flat=False)})
    await pair("b18_retry", "B18", ["ENGAGE", "RETRY_FLATTEN"],
               stub_kw={"guard_vals": dict(GOK18, all_accounts_flat=False)},
               snap=True)
    await pair("b18_cancel_fail", "B18", ["ENGAGE"],
               stub_kw={"guard_vals": GOK18,
                        "svc": {"cancel_all_working_orders": RuntimeError("x")}})
    await pair("b18_flatten_fail", "B18", ["ENGAGE"],
               stub_kw={"guard_vals": GOK18,
                        "svc": {"flatten_all_positions": RuntimeError("x")}})
    await pair("b18_release_ok", "B18", ["ENGAGE", "RELEASE"],
               stub_kw={"guard_vals": dict(GOK18, cancel_working_requested=False,
                                           flatten_requested=False)})
    await pair("b18_release_denied", "B18", ["ENGAGE", "RELEASE"],
               stub_kw={"guard_vals": dict(GOK18, cancel_working_requested=False,
                                           flatten_requested=False,
                                           owner_and_elevated=False)})

    await pair("b19_happy", "B19", ["SWEEP_DUE"],
               stub_kw={"guard_vals": GV19}, snap=True)
    await pair("b19_startup", "B19", ["STARTUP"], stub_kw={"guard_vals": GV19})
    await pair("b19_unknown_order", "B19", ["UNKNOWN_ORDER"],
               stub_kw={"guard_vals": GV19})
    await pair("b19_fetch_fail", "B19", ["SWEEP_DUE"],
               stub_kw={"guard_vals": GV19,
                        "svc": {"fetch_exchange_state": RuntimeError("net")}},
               snap=True)
    await pair("b19_stale", "B19", ["SWEEP_DUE"],
               stub_kw={"guard_vals": dict(GV19, too_many_failures=True,
                                           should_backoff=False),
                        "svc": {"fetch_exchange_state": RuntimeError("net")}})
    for ev in ["RECONNECTED", "OPERATOR_RESOLVED", "SWEEP_DUE"]:
        await pair("b19_stale_" + ev, "B19", ["SWEEP_DUE", ev],
                   stub_kw={"guard_vals": dict(GV19, too_many_failures=True,
                                               should_backoff=False),
                            "svc": {"fetch_exchange_state": RuntimeError("net")}})

    await pair("b20_breach", "B20", ["PNL_UPDATE"],
               stub_kw={"guard_vals": {"breaches_daily_loss_cap": True}})
    await pair("b20_manual", "B20", ["MANUAL_LOCK"], snap=True)
    await pair("b20_expiry_time", "B20", ["MANUAL_LOCK", "EXPIRY_DUE"],
               stub_kw={"guard_vals": {"until_mode_is_time_based": True}})
    await pair("b20_expiry_manual", "B20", ["MANUAL_LOCK", "EXPIRY_DUE"],
               stub_kw={"guard_vals": {"until_mode_is_time_based": False}})
    await pair("b20_override_ok", "B20", ["MANUAL_LOCK", "OVERRIDE_REQUESTED"],
               stub_kw={"guard_vals":
                        {"owner_and_elevated_and_override_permitted": True}},
               snap=True)
    await pair("b20_override_denied", "B20", ["MANUAL_LOCK", "OVERRIDE_REQUESTED"],
               stub_kw={"guard_vals":
                        {"owner_and_elevated_and_override_permitted": False}})
    await pair("b20_rollback", "B20", ["MANUAL_LOCK"],
               stub_kw={"raising": ["broadcast_lockout"]})

    R["sync_engine"] = {
        "B16": run_sync_parity("B16", ["MFA_OK", "REQUEST", "STEP_UP_OK"]),
        "B17": run_sync_parity("B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"],
                               stub_kw={"guard_vals": GV17}),
        "B18": run_sync_parity("B18", ["ENGAGE"], kind="sync",
                               stub_kw={"guard_vals": GOK18}),
        "B19": run_sync_parity("B19", ["SWEEP_DUE"], kind="sync",
                               stub_kw={"guard_vals": GV19}),
        "B20": run_sync_parity("B20", ["MANUAL_LOCK"]),
    }

asyncio.run(main())
json.dump(R, open("results/s3_inv.json", "w", encoding="utf-8"),
          indent=2, default=str)
print("DONE")
