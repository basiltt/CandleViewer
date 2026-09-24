# -*- coding: utf-8 -*-
"""B17 extras: deferred ENABLE_REQUESTED auto-replay; actionErrorPolicy=fail."""
import asyncio, json
from cdrv import mk, step

ALL_TRUE = {"all_evidence_present": True, "owner_and_elevated": True,
            "owner_and_elevated_and_evidence_still_valid": True}
R = {}

async def main():
    # ---- HAZARD: ENABLE_REQUESTED arrives while locked, is DEFERRED by
    #      policy, and fires the instant the gate becomes eligible.
    ev = {"all": False}
    gv = {"all_evidence_present": lambda c, e: ev["all"],
          "owner_and_elevated": lambda c, e: True,
          "owner_and_elevated_and_evidence_still_valid": lambda c, e: True}
    interp, st, tp, clock, m = await mk("B17", {"guard_vals": gv})
    r1 = await step(interp, clock, "ENABLE_REQUESTED")   # while locked
    a = {"after_enable_while_locked": sorted(interp.current_state_ids),
         "receipt": {"changed": r1.changed, "deferred": r1.deferred},
         "deferred_count": interp.deferred_count}
    ev["all"] = True
    r2 = await step(interp, clock, "EVIDENCE_RECORDED")
    await asyncio.sleep(0.15)
    a["after_evidence"] = sorted(interp.current_state_ids)
    a["acts"] = list(st.trace)
    a["transitions"] = list(tp.transitions)
    a["evidence_receipt"] = {"changed": r2.changed, "deferred": r2.deferred}
    R["deferred_enable_autoreplay"] = a
    await interp.stop()

    # ---- actionErrorPolicy: "fail" on a live-gate action --------------
    for bad in ["record_enable", "audit_live_enabled",
                "broadcast_live_enabled"]:
        interp, st, tp, clock, m = await mk(
            "B17", {"guard_vals": ALL_TRUE, "raising": {bad}})
        await step(interp, clock, "EVIDENCE_RECORDED")
        r = await step(interp, clock, "ENABLE_REQUESTED")
        rec = {"ids": sorted(interp.current_state_ids),
               "status": interp.status, "changed": r.changed,
               "error": type(r.error).__name__ if r.error else None,
               "err": str(r.error)[:120] if r.error else None,
               "acts": list(st.trace)}
        # can the machine still be driven after a "fail"?
        try:
            r2 = await step(interp, clock, "EMERGENCY_DISABLE")
            rec["after"] = {"changed": r2.changed,
                            "status": interp.status,
                            "ids": sorted(interp.current_state_ids)}
        except Exception as e:                                  # noqa: BLE001
            rec["after"] = f"{type(e).__name__}: {str(e)[:160]}"
        R[f"fail_{bad}"] = rec
        try: await interp.stop()
        except Exception: pass

    # ---- snapshot refused while faulted? ------------------------------
    interp, st, tp, clock, m = await mk(
        "B17", {"guard_vals": ALL_TRUE, "raising": {"record_enable"}})
    await step(interp, clock, "EVIDENCE_RECORDED")
    await step(interp, clock, "ENABLE_REQUESTED")
    try:
        s = interp.get_persisted_snapshot()
        R["snapshot_after_fail"] = {"ok": True, "status": s.get("status"),
                                    "state_ids": s.get("state_ids")}
    except Exception as e:                                       # noqa: BLE001
        R["snapshot_after_fail"] = f"{type(e).__name__}: {str(e)[:200]}"
    try: await interp.stop()
    except Exception: pass

asyncio.run(main())
print(json.dumps(R, indent=2, default=str))
json.dump(R, open("results/c2b_b17x.json","w",encoding="utf-8"), indent=2, default=str)
