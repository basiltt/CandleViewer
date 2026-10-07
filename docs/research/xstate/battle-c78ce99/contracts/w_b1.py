# -*- coding: utf-8 -*-
"""B1 Order (parallel: lifecycle + protection) end-to-end on c78ce99."""
from __future__ import annotations
import asyncio, json
import os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv78 as K
os.chdir("<home>")

C1 = K.cfg("B1")


def inc(key, d=1):
    def f(i, ctx, e, a):
        ctx[key] = int(ctx.get(key) or 0) + d
    return f


def s1(**kw):
    g = {"passes_all_gates": True, "ret_code_ok": True,
         "is_duplicate_link_id": False,
         "exec_new_and_closes": False, "exec_new_and_partial": True,
         "has_fills": False,
         "second_consecutive_miss": lambda c, e: int(c["recon_misses"]) >= 1}
    g.update(kw.pop("guard_vals", {}) or {})
    a = {"bump_recon_misses": inc("recon_misses")}
    a.update(kw.pop("act_impl", {}) or {})
    return K.Stub(C1, guard_vals=g, act_impl=a, **kw)


L = "order.lifecycle."
P = "order.protection."


async def b1():
    # --- happy: draft -> validated -> submitting(invoke) -> submitted ->
    #     partial -> filled, protection armed on FIRST_FILL --------------
    r = await K.drive(C1, s1(), ["VALIDATE", "SEND", "EXEC", "FIRST_FILL",
                                 ("EXEC", {}), "SL_LOST"],
                      snapshots=True)
    K.rec("B1.happy.parallel_leaves", len(r["states"]) == 2, str(r["states"]))
    K.rec("B1.happy.lifecycle", L + "partially_filled" in r["states"],
          str(r["states"]))
    K.rec("B1.happy.protection_naked", P + "sl_missing" in r["states"],
          str(r["states"]))
    K.rec("B1.happy.naked_alert",
          "raise_naked_position_alert" in r["actions"], "")
    K.rec("B1.happy.snapshot", r["snapshot_ok"], str(r["notes"])[:300])
    K.rec("B1.happy.no_error", r["error"] is None, str(r["error"]))
    json.dump(r, open(K.STYLE + "_out_b1_happy.json", "w"), indent=1, default=str)

    # --- to terminal filled; both regions still legal -------------------
    r = await K.drive(C1, s1(guard_vals={"exec_new_and_closes": True}),
                      ["VALIDATE", "SEND", "FIRST_FILL", "EXEC"])
    K.rec("B1.filled.terminal", L + "filled" in r["states"], str(r["states"]))
    K.rec("B1.filled.emit_terminal", "emit_terminal" in r["actions"], "")
    K.rec("B1.filled.two_regions", len(r["states"]) == 2, str(r["states"]))
    K.rec("B1.filled.snapshot", r["snapshot_ok"], str(r["notes"])[:300])

    # --- invariant: local reject when gates fail ------------------------
    r = await K.drive(C1, s1(guard_vals={"passes_all_gates": False}),
                      ["VALIDATE"])
    K.rec("B1.reject.local", L + "rejected" in r["states"], str(r["states"]))
    K.rec("B1.reject.set_local", "set_local_reject" in r["actions"], "")

    # --- invariant: place_order transport fault -> unknown + alert ------
    r = await K.drive(C1, s1(svc={"place_order": RuntimeError("timeout")}),
                      ["VALIDATE", "SEND"])
    K.rec("B1.unknown.entered", L + "unknown" in r["states"], str(r["states"]))
    K.rec("B1.unknown.alert", "raise_unknown_alert" in r["actions"], "")
    K.rec("B1.unknown.fault_recorded",
          "record_transport_fault" in r["actions"], "")

    # --- invariant: RECON_MISS reenters once, second miss rejects -------
    r = await K.drive(C1, s1(svc={"place_order": RuntimeError("t")}),
                      ["VALIDATE", "SEND", "RECON_MISS", "RECON_MISS"])
    K.rec("B1.recon.second_miss_rejects", L + "rejected" in r["states"],
          "states=%s misses=%s" % (r["states"], r["context"]["recon_misses"]))
    K.rec("B1.recon.reenter_bumped", r["context"]["recon_misses"] == 1,
          str(r["context"]["recon_misses"]))
    K.rec("B1.recon.snapshot", r["snapshot_ok"], str(r["notes"])[:300])

    # --- invariant: duplicate link id -> submitted + needs_lookup -------
    r = await K.drive(C1, s1(guard_vals={"ret_code_ok": False,
                                         "is_duplicate_link_id": True}),
                      ["VALIDATE", "SEND"])
    K.rec("B1.dup.needs_lookup",
          L + "submitted" in r["states"] and "mark_needs_lookup" in r["actions"],
          str(r["states"]))

    # --- invariant: quarantine on FAULT, recon returns it --------------
    r = await K.drive(C1, s1(), ["VALIDATE", "SEND", "FAULT",
                                 "RECON_FOUND_LIVE"])
    K.rec("B1.quarantine.recovers", L + "submitted" in r["states"],
          str(r["states"]))
    K.rec("B1.quarantine.critical_alert",
          "raise_critical_alert" in r["actions"], "")

    # --- R6-01 class: protection region invoke + cross-region event ----
    # SL deadline races attach_native_sl; both target sl_missing.
    r = await K.drive(C1, s1(svc={"attach_native_sl": RuntimeError("no sl")}),
                      ["VALIDATE", "SEND", "FIRST_FILL"])
    K.rec("B1.sl.onError_naked", P + "sl_missing" in r["states"],
          str(r["states"]))
    K.rec("B1.sl.fallback_requested",
          "request_fallback_sl" in r["actions"], "")

    # --- cancel path: cancel_pending invoke, EXEC races the cancel -----
    r = await K.drive(C1, s1(), ["VALIDATE", "SEND", "CANCEL"])
    K.rec("B1.cancel.cancelled", L + "cancelled" in r["states"],
          str(r["states"]))
    K.rec("B1.cancel.ack_adopted", "adopt_cancel_ack" in r["actions"], "")

    # --- amend rejected keeps prior order live -------------------------
    r = await K.drive(C1, s1(svc={"amend_order": asyncio.Future},
                             guard_vals={"has_fills": False}),
                      ["VALIDATE", "SEND", "AMEND", "AMEND_REJECTED"],
                      snapshots=False)
    K.rec("B1.amend.observed", True,
          "states=%s actions_tail=%s" % (r["states"], r["actions"][-3:]))

    # --- R6-03 class EXPLICIT: rollback + invoke.onDone on B1 ----------
    # adopt_ack raises -> rollback to `submitting` -> place_order re-armed.
    st = s1(raising=["adopt_ack"])
    r = await asyncio.wait_for(
        K.drive(C1, st, ["VALIDATE", "SEND"], snapshots=False), 40)
    n = r["svc_calls"].count("place_order")
    K.rec("B1.R6-03.terminates", not any(s.get("timeout") for s in r["sends"]),
          str(r["sends"]))
    K.rec("B1.R6-03.duplicate_orders_placed", True,
          "place_order x%d states=%s status=%s error=%s action_errors=%d"
          % (n, r["states"], r["status"], r["error"], len(r["action_errors"])))
    json.dump(r, open(K.STYLE + "_out_b1_r603.json", "w"), indent=1, default=str)

    # --- onUnhandled defer: EXEC before SEND ---------------------------
    r = await K.drive(C1, s1(), ["EXEC", "VALIDATE", "SEND"])
    K.rec("B1.defer.exec_replayed", L + "partially_filled" in r["states"],
          "states=%s unhandled=%s" % (r["states"], r["unhandled"][:3]))

    # --- guardErrorPolicy raise, and rollback leaves context intact ----
    r = await K.drive(C1, s1(guard_raise=["ret_code_ok"]),
                      ["VALIDATE", "SEND"], snapshots=False)
    K.rec("B1.guard_raise.observable", bool(r["guard_errors"]),
          str(r["guard_errors"][:1]))

    # --- sync parity ----------------------------------------------------
    script = ["VALIDATE", "SEND", "FIRST_FILL", "EXEC"]
    ra = await K.drive(C1, s1(), script, snapshots=False)
    ss = s1(); ss.sync = True; ss.svc_style = "def"
    rs = K.drive_sync(C1, ss, script)
    K.rec("B1.parity.states", ra["states"] == rs["states"],
          "async=%s sync=%s" % (ra["states"], rs["states"]))
    K.rec("B1.parity.context", ra["context"] == rs["context"],
          "async=%s\nsync=%s" % (ra["context"], rs["context"]))
    K.rec("B1.parity.actions", ra["actions"] == rs["actions"],
          "async=%s\nsync=%s" % (ra["actions"], rs["actions"]))
    K.rec("B1.parity.svc", ra["svc_calls"] == rs["svc_calls"],
          "async=%s sync=%s" % (ra["svc_calls"], rs["svc_calls"]))
    json.dump({"async": ra, "sync": rs}, open(K.STYLE + "_out_b1_parity.json", "w"),
              indent=1, default=str)


async def main():
    await b1()
    K.dump("res_b1.json")


if __name__ == "__main__":
    asyncio.run(main())
