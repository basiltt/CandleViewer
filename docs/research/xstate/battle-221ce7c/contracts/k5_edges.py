# -*- coding: utf-8 -*-
"""Edges: onUnhandled:error terminal-ness + snapshot; 'fail' now stops (#145);
strict at call site; B16 elevation-after-revocation; sync parity for B16/B17/B20."""
import asyncio, json
from cdrv import mk, step, cfg_of, run_sync_parity
from charness import Stub, TraceP, ids, SETTLE
from xstate_statemachine import Interpreter, OverflowPolicy, create_machine
from xstate_statemachine.clock import SimulatedClock

R = {}
CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
GOK = {"cancel_working_requested": False, "owner_and_elevated": False}

async def main():
    # B18: onUnhandled "error" after a guard-denied RELEASE -> is it terminal?
    interp, st, tp, clock, m = await mk("B18", {"guard_vals": GOK}, **CTL)
    await step(interp, clock, "ENGAGE")
    r1 = await interp.send("RELEASE", wait=True)
    await asyncio.sleep(SETTLE)
    post = {"status": interp.status, "ids": ids(interp),
            "denied": getattr(r1, "denied", "ABSENT"),
            "last_error": type(getattr(interp, "last_error", None)).__name__,
            "error_attr": type(getattr(interp, "error", None)).__name__}
    try:
        r2 = await asyncio.wait_for(interp.send("RETRY_FLATTEN", wait=True), 3)
        post["next_event"] = {"changed": r2.changed,
                              "error": type(r2.error).__name__ if r2.error else None}
    except Exception as e:
        post["next_event"] = f"{type(e).__name__}: {str(e)[:140]}"
    try:
        blob = interp.get_persisted_snapshot()
        post["snapshot"] = {"persisted": True, "status": blob.get("status")}
    except Exception as e:
        post["snapshot"] = f"{type(e).__name__}: {str(e)[:140]}"
    R["b18_error_terminal"] = post
    try: await interp.stop()
    except Exception: pass

    # actionErrorPolicy "fail" (#145) on the B17 shape, for the record
    cfg = cfg_of("B17"); cfg["actionErrorPolicy"] = "fail"
    st2 = Stub(cfg, guard_vals={"all_evidence_present": True,
                                "owner_and_elevated_and_evidence_still_valid": True},
               raising=["audit_live_enabled"])
    mm = create_machine(json.loads(json.dumps(cfg)), logic=st2.logic())
    it = Interpreter(mm, clock=SimulatedClock(), **CTL)
    await it.start(); await asyncio.sleep(SETTLE)
    await it.send("EVIDENCE_RECORDED", wait=True)
    try:
        rr = await asyncio.wait_for(it.send("ENABLE_REQUESTED", wait=True), 3)
        rrd = {"changed": rr.changed, "error": type(rr.error).__name__ if rr.error else None}
    except Exception as e:
        rrd = f"{type(e).__name__}: {str(e)[:140]}"
    await asyncio.sleep(SETTLE)
    row = {"receipt": rrd, "status": it.status, "ids": ids(it),
           "error": type(getattr(it, "error", None)).__name__}
    try:
        b = it.get_persisted_snapshot(); row["snapshot"] = {"persisted": True,
                                                            "status": b.get("status")}
    except Exception as e:
        row["snapshot"] = f"{type(e).__name__}: {str(e)[:140]}"
    R["fail_policy_b17"] = row
    try: await it.stop()
    except Exception: pass

    # strict: undeclared event at the call site (B16)
    interp, st, tp, clock, m = await mk("B16", {}, **CTL)
    try:
        await interp.send("NOT_A_REAL_EVENT", wait=True)
        R["b16_strict"] = "accepted"
    except Exception as e:
        R["b16_strict"] = f"{type(e).__name__}: {str(e)[:120]}"
    await interp.stop()

    # B16: elevation acquired AFTER revocation (INV-B16-d as a session)
    interp, st, tp, clock, m = await mk("B16", {}, **CTL)
    for ev in ["MFA_OK", "REVOKE"]:
        await step(interp, clock, ev)
    r = await asyncio.wait_for(interp.send("STEP_UP_OK", wait=True), 3)
    await asyncio.sleep(SETTLE)
    R["b16_elevate_after_revoke"] = {
        "ids": ids(interp), "receipt": {"changed": r.changed,
                                        "deferred": getattr(r, "deferred", None)},
        "acts": list(st.trace), "deferred_count": interp.deferred_count}
    await interp.stop()

    R["sync"] = {b: run_sync_parity(b, s, stub_kw={"guard_vals": gv})
                 for b, s, gv in [
                     ("B16", ["MFA_OK", "STEP_UP_OK", "LOGOUT"], {}),
                     ("B17", ["EVIDENCE_RECORDED", "ENABLE_REQUESTED"],
                      {"all_evidence_present": True,
                       "owner_and_elevated_and_evidence_still_valid": True}),
                     ("B20", ["MANUAL_LOCK", "OVERRIDE_REQUESTED"],
                      {"owner_and_elevated_and_override_permitted": True})]}

asyncio.run(main())
json.dump(R, open("results/k5_edges.json", "w", encoding="utf-8"), indent=2, default=str)
print(json.dumps(R, indent=1, default=str)[:3500])
