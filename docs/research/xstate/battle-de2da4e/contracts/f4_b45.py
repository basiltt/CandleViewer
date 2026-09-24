# -*- coding: utf-8 -*-
"""B4 OCO + B5 Iceberg end-to-end on c78ce99."""
from __future__ import annotations
import asyncio, json
import os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cvf as K
os.chdir("C:/Users/basil")

C4, C5 = K.cfg("B4"), K.cfg("B5")


def inc(key, d=1):
    def f(i, ctx, e, a):
        ctx[key] = int(ctx.get(key) or 0) + d
    return f


# ================================================================ B4 =======
def s4(**kw):
    g = {"position_overshoots": False, "other_leg_terminal": True,
         "partial_settle_remaining": False, "error_is_order_gone": False,
         "settle_retries_left": lambda c, e: int(c["settle_failures"]) < 2,
         "cancel_on_position_flat": True}
    g.update(kw.pop("guard_vals", {}) or {})
    a = {"bump_settle_failures": inc("settle_failures")}
    a.update(kw.pop("act_impl", {}) or {})
    return K.Stub(C4, guard_vals=g, act_impl=a, **kw)


async def b4():
    r = await K.drive(C4, s4(), ["LEG_A_FILL", "CHILDREN_TERMINAL"])
    K.rec("B4.happy.completed", r["states"] == ["oco.completed"], str(r["states"]))
    K.rec("B4.happy.arm_then_settle",
          r["svc_calls"] == ["submit_both_legs", "settle_other_leg"],
          str(r["svc_calls"]))
    K.rec("B4.happy.snapshot", r["snapshot_ok"], str(r["notes"])[:200])

    # invariant: double fill -> overshoot -> flatten excess, alerts fired
    r = await K.drive(C4, s4(guard_vals={"position_overshoots": True}),
                      ["LEG_B_FILL", "CHILDREN_TERMINAL"])
    K.rec("B4.overshoot.completed", r["states"] == ["oco.completed"],
          str(r["states"]))
    K.rec("B4.overshoot.alerts",
          {"raise_warning_alert", "journal_double_fill"} <= set(r["actions"]),
          str(r["actions"]))
    K.rec("B4.overshoot.flatten_called",
          "reduce_only_market_excess" in r["svc_calls"], str(r["svc_calls"]))

    # invariant: arming fails -> failed (no racing ever entered)
    r = await K.drive(C4, s4(svc={"submit_both_legs": RuntimeError("down")}),
                      [])
    K.rec("B4.arm_fail.failed", r["states"] == ["oco.failed"], str(r["states"]))
    K.rec("B4.arm_fail.map_error", "map_error" in r["actions"], str(r["actions"]))

    # settle retry ladder is bounded by settle_retries_left
    r = await K.drive(C4, s4(svc={"settle_other_leg": RuntimeError("x")}),
                      ["LEG_A_FILL"], snapshots=False)
    n = r["svc_calls"].count("settle_other_leg")
    K.rec("B4.settle.retry_bounded", 1 <= n <= 6,
          "settle_other_leg x%d -> %s" % (n, r["states"]))
    K.rec("B4.settle.retry_terminal", r["states"] == ["oco.failed"],
          str(r["states"]))
    K.rec("B4.settle.alert", "raise_critical_alert" in r["actions"], "")

    # order-gone -> reconciling -> completing
    r = await K.drive(C4, s4(guard_vals={"error_is_order_gone": True},
                             svc={"settle_other_leg": RuntimeError("gone")}),
                      ["LEG_A_FILL", "CHILDREN_TERMINAL"])
    K.rec("B4.reconcile.completed", r["states"] == ["oco.completed"],
          str(r["states"]))

    # R6-01 class: settling -> racing reenter, then fill again (ping-pong)
    r = await asyncio.wait_for(K.drive(
        C4, s4(guard_vals={"other_leg_terminal": False,
                           "partial_settle_remaining": True}),
        ["LEG_A_FILL"], snapshots=False), 40)
    spins = r["svc_calls"].count("settle_other_leg")
    K.rec("B4.R6-01.pingpong_terminates",
          not any(s.get("timeout") for s in r["sends"]), str(r["sends"]))
    K.rec("B4.R6-01.pingpong_settles", r["states"] == ["oco.racing"],
          "states=%s settle x%d status=%s" % (r["states"], spins, r["status"]))
    json.dump(r, open(K.STYLE + "_out_b4_pingpong.json", "w"), indent=1, default=str)

    # USER_CANCEL from racing
    r = await K.drive(C4, s4(), ["USER_CANCEL"])
    K.rec("B4.cancel.cancelled", r["states"] == ["oco.cancelled"],
          str(r["states"]))

    # sync parity
    ra = await K.drive(C4, s4(), ["LEG_A_FILL", "CHILDREN_TERMINAL"],
                       snapshots=False)
    ss = s4(); ss.sync = True; ss.svc_style = "def"
    rs = K.drive_sync(C4, ss, ["LEG_A_FILL", "CHILDREN_TERMINAL"])
    K.rec("B4.parity.states", ra["states"] == rs["states"],
          "async=%s sync=%s" % (ra["states"], rs["states"]))
    K.rec("B4.parity.svc", ra["svc_calls"] == rs["svc_calls"],
          "async=%s sync=%s" % (ra["svc_calls"], rs["svc_calls"]))


# ================================================================ B5 =======
def s5(**kw):
    g = {"preflight_invalid": False, "is_post_only_reject": False,
         "failures_exhausted": lambda c, e: int(c["failure_count"]) >= 3,
         "remaining_is_zero": False, "slices_exhausted": False,
         "two_consecutive_post_only_rejects":
             lambda c, e: int(c["post_only_rejects"]) >= 2,
         "on_disconnect_is_freeze": True, "cancel_on_position_flat": True}
    g.update(kw.pop("guard_vals", {}) or {})
    a = {"bump_slices_done": inc("slices_done"),
         "bump_failure": inc("failure_count"),
         "bump_post_only_rejects": inc("post_only_rejects"),
         "reset_post_only_rejects":
             lambda i, c, e, ad: c.__setitem__("post_only_rejects", 0)}
    a.update(kw.pop("act_impl", {}) or {})
    return K.Stub(C5, guard_vals=g, act_impl=a, **kw)


async def b5():
    # R6-01 class: `pending.always` descends straight into submitting_slice,
    # which invokes submit_child at start().
    r = await K.drive(C5, s5(), ["CHILD_FILLED", "REFILL_DUE",
                                 "CHILD_FILLED"])
    K.rec("B5.refill.loop_progresses", r["states"] == ["iceberg.waiting_refill"],
          "states=%s slices=%s" % (r["states"], r["context"]["slices_done"]))
    K.rec("B5.refill.two_slices", r["context"]["slices_done"] == 2,
          str(r["context"]["slices_done"]))
    K.rec("B5.refill.snapshot", r["snapshot_ok"], str(r["notes"])[:200])

    # completion path
    r = await K.drive(C5, s5(guard_vals={"remaining_is_zero": True}),
                      ["CHILD_FILLED", "CHILDREN_TERMINAL"])
    K.rec("B5.complete.completed", r["states"] == ["iceberg.completed"],
          str(r["states"]))

    # invariant: preflight_invalid short-circuits at start
    r = await K.drive(C5, s5(guard_vals={"preflight_invalid": True}), [])
    K.rec("B5.preflight.failed", r["states"] == ["iceberg.failed"],
          str(r["states"]))
    K.rec("B5.preflight.no_submit", "submit_child" not in r["svc_calls"],
          str(r["svc_calls"]))

    # R6-01 class: post-only reject -> repricing.always -> submitting_slice
    # -> invoke rejects again -> repricing ... must reach cooling_down.
    r = await asyncio.wait_for(K.drive(
        C5, s5(guard_vals={"is_post_only_reject": True},
               svc={"submit_child": RuntimeError("post-only")}),
        [], snapshots=False), 40)
    n = r["svc_calls"].count("submit_child")
    K.rec("B5.R6-01.reprice_terminates", r["states"] == ["iceberg.cooling_down"],
          "states=%s submit_child x%d status=%s" % (r["states"], n, r["status"]))
    K.rec("B5.R6-01.reprice_bounded", n <= 10, "submit_child x%d" % n)
    json.dump(r, open(K.STYLE + "_out_b5_reprice.json", "w"), indent=1, default=str)

    # submit failure ladder -> failed after failures_exhausted
    r = await asyncio.wait_for(K.drive(
        C5, s5(svc={"submit_child": RuntimeError("nope")}), [],
        snapshots=False), 40)
    n = r["svc_calls"].count("submit_child")
    K.rec("B5.fail_ladder.terminal", r["states"] == ["iceberg.failed"],
          "states=%s submit_child x%d" % (r["states"], n))
    K.rec("B5.fail_ladder.bounded", n <= 10, "submit_child x%d" % n)

    # pause / resume / reconcile
    r = await K.drive(C5, s5(), ["USER_PAUSE", "RESUME"])
    K.rec("B5.pause.resume_to_working", r["states"] == ["iceberg.working"],
          str(r["states"]))
    K.rec("B5.pause.reconciled", "reconcile_children" in r["svc_calls"],
          str(r["svc_calls"]))
    r = await K.drive(C5, s5(svc={"reconcile_children": RuntimeError("r")}),
                      ["WS_DISCONNECT", "RESUME"])
    K.rec("B5.disconnect.freeze_then_fail", r["states"] == ["iceberg.failed"],
          str(r["states"]))

    # cancel path
    r = await K.drive(C5, s5(), ["POSITION_FLAT"])
    K.rec("B5.flat.cancelled", r["states"] == ["iceberg.cancelled"],
          str(r["states"]))

    # R6-03 class: rollback + invoke.onDone (record_child raises)
    r = await asyncio.wait_for(K.drive(
        C5, s5(raising=["record_child"]), [], snapshots=False), 40)
    n = r["svc_calls"].count("submit_child")
    K.rec("B5.R6-03.observed",
          True, "submit_child x%d states=%s status=%s err=%s action_errors=%d"
          % (n, r["states"], r["status"], r["error"], len(r["action_errors"])))
    json.dump(r, open(K.STYLE + "_out_b5_r603.json", "w"), indent=1, default=str)

    # sync parity
    ra = await K.drive(C5, s5(), ["CHILD_FILLED", "REFILL_DUE"],
                       snapshots=False)
    ss = s5(); ss.sync = True; ss.svc_style = "def"
    rs = K.drive_sync(C5, ss, ["CHILD_FILLED", "REFILL_DUE"])
    K.rec("B5.parity.states", ra["states"] == rs["states"],
          "async=%s sync=%s" % (ra["states"], rs["states"]))
    K.rec("B5.parity.context", ra["context"] == rs["context"],
          "async=%s\nsync=%s" % (ra["context"], rs["context"]))


async def main():
    await b4()
    await b5()
    K.dump("res_b45.json")


if __name__ == "__main__":
    asyncio.run(main())
