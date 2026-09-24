# -*- coding: utf-8 -*-
"""B17 LiveEnablement: 2FA + pen-test gating, INV-B17-b..e, snapshot parity."""
import asyncio, json
import cdrv
from cdrv import mk, step, obs, run_plain, run_snapshotted, compare, run_sync_parity

R = {}

# evidence model: guard reads a live flag dict we flip between sends
class Flags:
    def __init__(self):
        self.pentest = False
        self.key_audit = False
        self.env_sep = False
        self.runbooks = False
        self.elevated = False
        self.owner = False
    def all_evidence(self, ctx, evt):
        return all([self.pentest, self.key_audit, self.env_sep, self.runbooks])


async def main():
    F = Flags()
    gv = {
        "all_evidence_present": lambda c, e: F.all_evidence(c, e),
        "owner_and_elevated": lambda c, e: F.owner and F.elevated,
        "owner_and_elevated_and_evidence_still_valid":
            lambda c, e: F.owner and F.elevated and F.all_evidence(c, e),
    }

    # ---- INV-B17-b: enable requires owner+elevation+evidence ----------
    interp, st, tp, clock, m = await mk("B17", {"guard_vals": gv})
    trace = []
    # partial evidence -> stays locked (internal transition, evidence recorded)
    F.pentest = True
    await step(interp, clock, "EVIDENCE_RECORDED")
    trace.append(("pentest_only", sorted(interp.current_state_ids)))
    # attempt to enable while locked -> event has no handler in `locked`
    r = await step(interp, clock, "ENABLE_REQUESTED")
    trace.append(("enable_while_locked", sorted(interp.current_state_ids),
                  r.changed, r.deferred))
    R["b17b_locked_enable"] = trace

    # complete evidence -> eligible (the deferred ENABLE_REQUESTED replays!)
    F.key_audit = F.env_sep = F.runbooks = True
    await step(interp, clock, "EVIDENCE_RECORDED")
    await asyncio.sleep(0.1)
    R["b17b_after_evidence"] = {
        "ids": sorted(interp.current_state_ids),
        "deferred": interp.deferred_count,
        "acts": list(st.trace),
        "transitions": list(tp.transitions),
    }
    await interp.stop()

    # ---- clean run: 2FA(elevation) missing -> denial -------------------
    F2 = Flags(); F2.pentest = F2.key_audit = F2.env_sep = F2.runbooks = True
    F2.owner = True; F2.elevated = False
    gv2 = {"all_evidence_present": lambda c, e: F2.all_evidence(c, e),
           "owner_and_elevated": lambda c, e: F2.owner and F2.elevated,
           "owner_and_elevated_and_evidence_still_valid":
               lambda c, e: F2.owner and F2.elevated and F2.all_evidence(c, e)}
    interp, st, tp, clock, m = await mk("B17", {"guard_vals": gv2})
    await step(interp, clock, "EVIDENCE_RECORDED")
    r = await step(interp, clock, "ENABLE_REQUESTED")
    R["no_2fa"] = {"ids": sorted(interp.current_state_ids),
                   "acts": list(st.trace), "changed": r.changed,
                   "deferred": r.deferred}
    # now elevate (2FA) -> enable succeeds
    F2.elevated = True
    r = await step(interp, clock, "ENABLE_REQUESTED")
    R["with_2fa"] = {"ids": sorted(interp.current_state_ids),
                     "acts": list(st.trace), "changed": r.changed}
    # ---- INV-B17-c: EVIDENCE_INVALIDATED demotes ---------------------
    F2.pentest = False
    r = await step(interp, clock, "EVIDENCE_INVALIDATED")
    R["inv_c"] = {"ids": sorted(interp.current_state_ids),
                  "acts_tail": st.trace[-4:], "changed": r.changed}
    # ---- INV-B17-d: EMERGENCY_DISABLE ungated -------------------------
    await interp.stop()

    F3 = Flags(); F3.pentest=F3.key_audit=F3.env_sep=F3.runbooks=True
    F3.owner=True; F3.elevated=True
    gv3 = {"all_evidence_present": lambda c,e: F3.all_evidence(c,e),
           "owner_and_elevated": lambda c,e: F3.owner and F3.elevated,
           "owner_and_elevated_and_evidence_still_valid":
               lambda c,e: F3.owner and F3.elevated and F3.all_evidence(c,e)}
    interp, st, tp, clock, m = await mk("B17", {"guard_vals": gv3})
    await step(interp, clock, "EVIDENCE_RECORDED")
    await step(interp, clock, "ENABLE_REQUESTED")
    F3.owner = False; F3.elevated = False   # no authority at all
    r = await step(interp, clock, "EMERGENCY_DISABLE")
    R["inv_d_emergency"] = {"ids": sorted(interp.current_state_ids),
                            "changed": r.changed, "acts_tail": st.trace[-4:],
                            "guard_calls_tail": st.guard_calls[-3:]}
    await interp.stop()

    # ---- INV-B17-e: every enable/denial/disable audited ---------------
    # collected from the traces above.
    R["audit_trace_no2fa"] = R["no_2fa"]["acts"]

    # ---- actionErrorPolicy: "fail" -----------------------------------
    interp, st, tp, clock, m = await mk(
        "B17", {"guard_vals": gv3, "raising": {"record_enable"}})
    await step(interp, clock, "EVIDENCE_RECORDED")
    r = await step(interp, clock, "ENABLE_REQUESTED")
    R["action_fail"] = {"ids": sorted(interp.current_state_ids),
                        "status": interp.status, "changed": r.changed,
                        "error": type(r.error).__name__ if r.error else None,
                        "acts": list(st.trace)}
    try:
        r2 = await step(interp, clock, "EMERGENCY_DISABLE")
        R["after_fail_send"] = {"changed": r2.changed, "status": interp.status,
                                "ids": sorted(interp.current_state_ids)}
    except Exception as e:                                      # noqa: BLE001
        R["after_fail_send"] = f"{type(e).__name__}: {str(e)[:160]}"
    await interp.stop()

    # ---- snapshot every macrostep ------------------------------------
    F4 = Flags(); F4.pentest=F4.key_audit=F4.env_sep=F4.runbooks=True
    F4.owner=True; F4.elevated=True
    gv4 = {"all_evidence_present": lambda c,e: True,
           "owner_and_elevated": lambda c,e: True,
           "owner_and_elevated_and_evidence_still_valid": lambda c,e: True}
    seq = ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "DISABLE_REQUESTED",
           "ENABLE_REQUESTED", "EMERGENCY_DISABLE"]
    plain = await run_plain("B17", seq, {"guard_vals": gv4})
    snap = await run_snapshotted("B17", seq, {"guard_vals": gv4})
    R["snapshot"] = {"midstep_errors": snap["midstep_errors"],
                     "diffs": compare(plain, snap),
                     "acts_equal": plain["acts"] == snap["acts"],
                     "plain_acts": plain["acts"], "snap_acts": snap["acts"],
                     "ids": snap["ids"]}
    R["sync_parity"] = run_sync_parity("B17", seq, {"guard_vals": gv4})

asyncio.run(main())
print(json.dumps(R, indent=2, default=str))
json.dump(R, open("results/c2_b17.json","w",encoding="utf-8"), indent=2, default=str)
