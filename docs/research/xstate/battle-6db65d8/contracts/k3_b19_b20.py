# -*- coding: utf-8 -*-
"""B19 Reconciliation + B20 RiskLockout + B18 in-flight RELEASE redo."""
import asyncio, json
from cdrv import run_plain, run_snapshotted, compare, run_sync_parity, mk, step
from charness import ids, SETTLE
from xstate_statemachine import OverflowPolicy

R = {}
CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)

async def hang(i, c, e):
    await asyncio.sleep(3600)

async def main():
    # ---- B18 redo: RELEASE arriving while cancelling (undeclared there) ----
    GOK = {"cancel_working_requested": True, "flatten_requested": False,
           "all_accounts_flat": True, "owner_and_elevated": True,
           "owner_and_elevated_and_acknowledged_residual": True}
    interp, st, tp, clock, m = await mk(
        "B18", {"guard_vals": GOK, "svc": {"cancel_all_working_orders": hang}}, **CTL)
    await step(interp, clock, "ENGAGE")
    mid = ids(interp)
    err = None; r = None
    try:
        r = await interp.send("RELEASE", wait=True)
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:160]}"
    await asyncio.sleep(SETTLE)
    R["b18_release_in_flight"] = {
        "ids_mid": mid, "ids_after": ids(interp), "status": interp.status, "raised": err,
        "receipt": None if r is None else
        {"changed": r.changed, "denied": getattr(r, "denied", "ABSENT"),
         "deferred": getattr(r, "deferred", None),
         "error": type(r.error).__name__ if r.error else None},
        "unhandled": tp.unhandled, "dropped": tp.dropped}
    try: await interp.stop()
    except Exception: pass

    # ---- B19 ----
    GV = {"auto_remediate_allowed": True, "should_backoff": True,
          "too_many_failures": False}
    R["b19_happy"] = await run_plain("B19", ["SWEEP_DUE"], stub_kw={"guard_vals": GV}, **CTL)
    R["b19_startup"] = await run_plain("B19", ["STARTUP"], stub_kw={"guard_vals": GV}, **CTL)
    R["b19_unknown_order"] = await run_plain("B19", ["UNKNOWN_ORDER"], stub_kw={"guard_vals": GV}, **CTL)
    # fetch fails -> backing_off; too many failures -> stale_lockout
    R["b19_fetch_fail"] = await run_plain(
        "B19", ["SWEEP_DUE"],
        stub_kw={"guard_vals": GV, "svc": {"fetch_exchange_state": RuntimeError("net")}}, **CTL)
    R["b19_stale"] = await run_plain(
        "B19", ["SWEEP_DUE"],
        stub_kw={"guard_vals": dict(GV, too_many_failures=True, should_backoff=False),
                 "svc": {"fetch_exchange_state": RuntimeError("net")}}, **CTL)
    # INV-B19-b flap: stale_lockout then RECONNECTED / OPERATOR_RESOLVED
    for ev in ["RECONNECTED", "OPERATOR_RESOLVED", "SWEEP_DUE"]:
        try:
            R["b19_stale_" + ev] = await run_plain(
                "B19", ["SWEEP_DUE", ev],
                stub_kw={"guard_vals": dict(GV, too_many_failures=True, should_backoff=False),
                         "svc": {"fetch_exchange_state": RuntimeError("net")}}, **CTL)
        except Exception as e:
            R["b19_stale_" + ev] = {"raised": f"{type(e).__name__}: {str(e)[:160]}"}
    # UNKNOWN_ORDER arriving during a sweep (was C-02: eaten by "*")
    interp, st, tp, clock, m = await mk(
        "B19", {"guard_vals": GV, "svc": {"fetch_exchange_state": hang}}, **CTL)
    await step(interp, clock, "SWEEP_DUE")
    r = await interp.send("UNKNOWN_ORDER", wait=True)
    await asyncio.sleep(SETTLE)
    R["b19_unknown_during_sweep"] = {
        "ids": ids(interp), "deferred": interp.deferred_count,
        "receipt": {"changed": r.changed, "deferred": getattr(r, "deferred", None),
                    "denied": getattr(r, "denied", "ABSENT"),
                    "error": type(r.error).__name__ if r.error else None},
        "unhandled": tp.unhandled, "dropped": tp.dropped, "acts": list(st.trace)}
    try: await interp.stop()
    except Exception: pass
    # CANCEL during fetching
    R["b19_cancel"] = await run_plain(
        "B19", ["SWEEP_DUE", "CANCEL"],
        stub_kw={"guard_vals": GV, "svc": {"fetch_exchange_state": hang}}, **CTL)
    for name, s in [("sweep", ["SWEEP_DUE"]), ("fail", ["SWEEP_DUE"])]:
        kw = {"guard_vals": GV} if name == "sweep" else {
            "guard_vals": GV, "svc": {"fetch_exchange_state": RuntimeError("net")}}
        snap = await run_snapshotted("B19", s, stub_kw=kw, **CTL)
        plain = await run_plain("B19", s, stub_kw=kw, **CTL)
        R["b19_snap_" + name] = {"midstep": snap["midstep_errors"],
                                 "diffs": compare(plain, snap),
                                 "trace_eq": plain["transitions"] == snap["transitions"],
                                 "ids": snap["ids"]}

    # ---- B20 ----
    GB = {"breaches_daily_loss_cap": True}
    R["b20_breach"] = await run_plain("B20", ["PNL_UPDATE"], stub_kw={"guard_vals": GB}, **CTL)
    R["b20_warn"] = await run_plain(
        "B20", ["PNL_UPDATE", "PNL_UPDATE"],
        stub_kw={"guard_vals": {"within_warning_band": True, "outside_warning_band": True}}, **CTL)
    R["b20_manual"] = await run_plain("B20", ["MANUAL_LOCK"], **CTL)
    R["b20_expiry_time"] = await run_plain(
        "B20", ["MANUAL_LOCK", "EXPIRY_DUE"],
        stub_kw={"guard_vals": {"until_mode_is_time_based": True}}, **CTL)
    R["b20_expiry_manual"] = await run_plain(
        "B20", ["MANUAL_LOCK", "EXPIRY_DUE"],
        stub_kw={"guard_vals": {"until_mode_is_time_based": False}}, **CTL)
    R["b20_override_ok"] = await run_plain(
        "B20", ["MANUAL_LOCK", "OVERRIDE_REQUESTED"],
        stub_kw={"guard_vals": {"owner_and_elevated_and_override_permitted": True}}, **CTL)
    R["b20_override_denied"] = await run_plain(
        "B20", ["MANUAL_LOCK", "OVERRIDE_REQUESTED"],
        stub_kw={"guard_vals": {"owner_and_elevated_and_override_permitted": False}}, **CTL)
    # rollback on last entry action raising (the old "fail" scenario)
    R["b20_rollback"] = await run_plain(
        "B20", ["MANUAL_LOCK"], stub_kw={"raising": ["broadcast_lockout"]}, **CTL)
    R["b20_rollback_snapshot_ok"] = None
    for name, s in [("lock", ["MANUAL_LOCK"]), ("override", ["MANUAL_LOCK", "OVERRIDE_REQUESTED"])]:
        kw = {"guard_vals": {"owner_and_elevated_and_override_permitted": True}}
        snap = await run_snapshotted("B20", s, stub_kw=kw, **CTL)
        plain = await run_plain("B20", s, stub_kw=kw, **CTL)
        R["b20_snap_" + name] = {"midstep": snap["midstep_errors"],
                                 "diffs": compare(plain, snap),
                                 "trace_eq": plain["transitions"] == snap["transitions"],
                                 "ids": snap["ids"]}
    R["b20_sync"] = run_sync_parity("B20", ["MANUAL_LOCK"], stub_kw={})
    R["b19_sync"] = run_sync_parity("B19", ["SWEEP_DUE"], stub_kw={"guard_vals": GV})

asyncio.run(main())
json.dump(R, open("results/k3_b19_b20.json", "w", encoding="utf-8"), indent=2, default=str)
print("done")
