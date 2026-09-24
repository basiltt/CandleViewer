# -*- coding: utf-8 -*-
"""B18 KillSwitch: happy paths, INV-B18-c/d, onUnhandled error, send_priority,
plus the B17 deferred-replay (stale authorisation) hazard."""
import asyncio, json
import cdrv
from cdrv import run_plain, run_snapshotted, compare, run_sync_parity, mk, step, obs
from charness import Stub, build, TraceP, ids, SETTLE
from xstate_statemachine import Interpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock

R = {}
CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
GOK = {"cancel_working_requested": True, "flatten_requested": True,
       "all_accounts_flat": True, "owner_and_elevated": True,
       "owner_and_elevated_and_acknowledged_residual": True}

async def main():
    # B17 stale-authorisation replay: ENABLE_REQUESTED deferred in locked,
    # replays the instant evidence lands.
    R["b17_stale_replay"] = await run_plain(
        "B17", ["ENABLE_REQUESTED", "EVIDENCE_RECORDED"],
        stub_kw={"guard_vals": {"all_evidence_present": True,
                                "owner_and_elevated_and_evidence_still_valid": True}},
        **CTL)

    # ---- B18 happy: ENGAGE -> engaging -> cancelling -> flattening -> engaged
    R["b18_happy"] = await run_plain("B18", ["ENGAGE"], stub_kw={"guard_vals": GOK}, **CTL)
    # INV-B18-c: not all flat -> engaged_incomplete + page_owner
    R["b18_incomplete"] = await run_plain(
        "B18", ["ENGAGE"], stub_kw={"guard_vals": dict(GOK, all_accounts_flat=False)}, **CTL)
    R["b18_retry"] = await run_plain(
        "B18", ["ENGAGE", "RETRY_FLATTEN"],
        stub_kw={"guard_vals": dict(GOK, all_accounts_flat=False)}, **CTL)
    # service failures
    R["b18_cancel_fail"] = await run_plain(
        "B18", ["ENGAGE"],
        stub_kw={"guard_vals": GOK, "svc": {"cancel_all_working_orders": RuntimeError("x")}}, **CTL)
    R["b18_flatten_fail"] = await run_plain(
        "B18", ["ENGAGE"],
        stub_kw={"guard_vals": GOK, "svc": {"flatten_all_positions": RuntimeError("x")}}, **CTL)
    # INV-B18-d: release requires owner+elevation; denial under onUnhandled:error
    for name, gv in [("ok", GOK), ("denied", dict(GOK, owner_and_elevated=False))]:
        try:
            R["b18_release_" + name] = await run_plain(
                "B18", ["ENGAGE", "RELEASE"],
                stub_kw={"guard_vals": dict(gv, cancel_working_requested=False)}, **CTL)
        except Exception as e:
            R["b18_release_" + name] = {"raised": f"{type(e).__name__}: {str(e)[:180]}"}
    # RELEASE while engaging/cancelling (undeclared there) under onUnhandled:error
    try:
        interp, st, tp, clock, m = await mk(
            "B18", {"guard_vals": dict(GOK, cancel_working_requested=True),
                    "svc": {"cancel_all_working_orders":
                            lambda i, c, e: asyncio.sleep(3600)}}, **CTL)
        await step(interp, clock, "ENGAGE")
        r = None; err = None
        try:
            r = await interp.send("RELEASE", wait=True)
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:160]}"
        await asyncio.sleep(SETTLE)
        R["b18_release_in_flight"] = {
            "ids": ids(interp), "status": interp.status, "err": err,
            "receipt": None if r is None else
            {"changed": r.changed, "error": type(r.error).__name__ if r.error else None,
             "deferred": getattr(r, "deferred", None), "denied": getattr(r, "denied", None)},
            "unhandled": tp.unhandled, "dropped": tp.dropped,
            "last_error": type(getattr(interp, "last_error", None)).__name__,
        }
        await interp.stop()
    except Exception as e:
        R["b18_release_in_flight"] = {"raised": f"{type(e).__name__}: {str(e)[:200]}"}

    # Receipt.denied on a guard-denied RELEASE in engaged
    interp, st, tp, clock, m = await mk(
        "B18", {"guard_vals": dict(GOK, cancel_working_requested=False,
                                   owner_and_elevated=False)}, **CTL)
    await step(interp, clock, "ENGAGE")
    try:
        r = await interp.send("RELEASE", wait=True)
        R["b18_denied_receipt"] = {
            "changed": r.changed, "denied": getattr(r, "denied", "ABSENT"),
            "deferred": getattr(r, "deferred", None),
            "error": type(r.error).__name__ if r.error else None,
            "unhandled": tp.unhandled, "ids": ids(interp), "status": interp.status}
    except Exception as e:
        R["b18_denied_receipt"] = {"raised": f"{type(e).__name__}: {str(e)[:180]}"}
    await interp.stop()

    # send_priority preemption with a saturated inbox
    interp, st, tp, clock, m = await mk(
        "B18", {"guard_vals": dict(GOK, cancel_working_requested=False)},
        max_queue_size=8, overflow_policy=OverflowPolicy.DROP_NEWEST)
    has_pri = hasattr(interp, "send_priority")
    pre = None
    if has_pri:
        for _ in range(8):
            try: interp.send_nowait("RETRY_FLATTEN") if hasattr(interp, "send_nowait") else None
            except Exception: pass
        try:
            pre = await interp.send_priority("ENGAGE", wait=True)
        except Exception as e:
            pre = f"{type(e).__name__}: {str(e)[:150]}"
    await asyncio.sleep(SETTLE * 3)
    R["b18_send_priority"] = {
        "has_send_priority": has_pri,
        "result": None if pre is None else (pre if isinstance(pre, str) else
                  {"changed": pre.changed}),
        "ids": ids(interp), "acts": list(st.trace)}
    await interp.stop()

    # snapshots
    for name, s in [("engage", ["ENGAGE"]), ("incomplete", ["ENGAGE", "RETRY_FLATTEN"])]:
        gv = GOK if name == "engage" else dict(GOK, all_accounts_flat=False)
        snap = await run_snapshotted("B18", s, stub_kw={"guard_vals": gv}, **CTL)
        plain = await run_plain("B18", s, stub_kw={"guard_vals": gv}, **CTL)
        R["b18_snap_" + name] = {"midstep": snap["midstep_errors"],
                                 "diffs": compare(plain, snap),
                                 "trace_eq": plain["transitions"] == snap["transitions"],
                                 "ids": snap["ids"]}
    R["b18_sync"] = run_sync_parity("B18", ["ENGAGE"], stub_kw={"guard_vals": GOK})

asyncio.run(main())
json.dump(R, open("results/k2_b18.json", "w", encoding="utf-8"), indent=2, default=str)
print("done")
