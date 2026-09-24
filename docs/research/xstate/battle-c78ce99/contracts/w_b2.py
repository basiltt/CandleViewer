# -*- coding: utf-8 -*-
"""B2 TradeGroup + B3 TradeGroupLeg end-to-end on c78ce99."""
from __future__ import annotations
import asyncio, json
import os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv78 as K
os.chdir("C:/Users/basil")

C2 = K.cfg("B2")
C3 = K.cfg("B3")


def count(key, d=1):
    def f(i, ctx, e, a):
        ctx[key] = int(ctx.get(key) or 0) + d
    return f


# =========================================================== B2 ============
B2_ACT = {
    "count_open": count("legs_open"),
    "count_failed": count("legs_failed"),
    "count_skipped": count("legs_skipped"),
    "mark_quiesced": lambda i, c, e, a: c.__setitem__("quiesced", True),
}
B2_G_BASE = {
    "all_non_skipped_open": lambda c, e: (
        c["legs_total"] > 0
        and c["legs_open"] + c["legs_skipped"] >= c["legs_total"]),
    "quiesced_and_zero_open": lambda c, e: c["quiesced"] and c["legs_open"] == 0,
    "quiesced_and_some_open": lambda c, e: c["quiesced"] and c["legs_open"] > 0,
    "some_open": lambda c, e: c["legs_open"] > 0,
    "policy_is_abort_on_first": False,
    "policy_all_or_none_and_any_failed": False,
    "unwind_complete": True,
}


def b2_stub(**kw):
    g = dict(B2_G_BASE); g.update(kw.pop("guard_vals", {}) or {})
    a = dict(B2_ACT); a.update(kw.pop("act_impl", {}) or {})
    st = K.Stub(C2, guard_vals=g, act_impl=a, **kw)
    return st


def with_total(n):
    c = K.copy.deepcopy(C2)
    c["context"]["legs_total"] = n
    return c


async def b2():
    # --- happy: CONFIRM, 2 LEG_OPEN -> open -> closed -----------------
    c = with_total(2)
    st = b2_stub()
    st.acts = K.collect(c)[0]
    r = await K.drive(c, st, ["CONFIRM", "LEG_OPEN", "LEG_OPEN",
                              "ALL_LEGS_FLAT"])
    K.rec("B2.happy.terminal", r["states"] == ["trade_group.closed"],
          str(r["states"]))
    K.rec("B2.happy.snapshot", r["snapshot_ok"], str(r["notes"])[:200])
    K.rec("B2.happy.no_error", r["error"] is None, str(r["error"]))
    K.rec("B2.happy.raise_chain_bounded",
          not any(s.get("timeout") for s in r["sends"]), str(r["sends"])[:200])
    json.dump(r, open(K.STYLE + "_out_b2_happy.json", "w"), indent=1, default=str)

    # --- invariant: EVALUATE is raise-driven; a leg failing under
    #     best_effort with one open ends partially_open at quiesce --------
    c = with_total(2)
    st = b2_stub()
    r = await K.drive(c, st, ["CONFIRM", "LEG_OPEN", "LEG_FAILED",
                              "QUIESCE_DEADLINE"])
    K.rec("B2.partial.quiesce", r["states"] == ["trade_group.partially_open"],
          str(r["states"]) + " ctx=" + str({k: r["context"][k] for k in
                                            ("legs_open", "legs_failed",
                                             "quiesced")}))
    K.rec("B2.partial.snapshot", r["snapshot_ok"], str(r["notes"])[:300])

    # --- invariant: zero open at quiesce -> failed ----------------------
    c = with_total(2)
    st = b2_stub()
    r = await K.drive(c, st, ["CONFIRM", "LEG_FAILED", "LEG_FAILED",
                              "QUIESCE_DEADLINE"])
    K.rec("B2.allfail.failed", r["states"] == ["trade_group.failed"],
          str(r["states"]))

    # --- invariant: abort_on_first -> aborting -> always -> failed ------
    c = with_total(2)
    st = b2_stub(guard_vals={"policy_is_abort_on_first": True})
    r = await K.drive(c, st, ["CONFIRM", "LEG_FAILED"])
    K.rec("B2.abort.always_resolves", r["states"] == ["trade_group.failed"],
          str(r["states"]))
    K.rec("B2.abort.entry_ran",
          "stop_submitting_remaining_legs" in r["actions"], "")

    # --- abort with one open -> aborting always -> partially_open -------
    c = with_total(3)
    st = b2_stub(guard_vals={"policy_is_abort_on_first": True})
    r = await K.drive(c, st, ["CONFIRM", "LEG_OPEN", "LEG_FAILED"])
    K.rec("B2.abort.some_open", r["states"] == ["trade_group.partially_open"],
          str(r["states"]))

    # --- R6-03 class: rollback + invoke.onDone (unwinding) --------------
    # all_or_none + failure -> unwinding, invoke unwind_machine.
    c = with_total(2)
    st = b2_stub(guard_vals={"policy_all_or_none_and_any_failed": True})
    r = await K.drive(c, st, ["CONFIRM", "LEG_FAILED"])
    K.rec("B2.unwind.onDone_terminal", r["states"] == ["trade_group.failed"],
          str(r["states"]))
    K.rec("B2.unwind.svc_once", r["svc_calls"].count("unwind_machine") == 1,
          str(r["svc_calls"]))
    K.rec("B2.unwind.mark_unwound", "mark_unwound" in r["actions"],
          str(r["actions"][-4:]))

    # --- R6-03 EXPLICIT: rollback raised by an onDone action ------------
    # mark_unwound raises -> rollback returns to `unwinding`, re-arming the
    # invoke. Must terminate, bounded, observable.
    c = with_total(2)
    st = b2_stub(guard_vals={"policy_all_or_none_and_any_failed": True},
                 raising=["mark_unwound"])
    r = await asyncio.wait_for(
        K.drive(c, st, ["CONFIRM", "LEG_FAILED"], snapshots=False), 40)
    spins = r["svc_calls"].count("unwind_machine")
    K.rec("B2.R6-03.terminates",
          not any(s.get("timeout") for s in r["sends"]),
          "sends=" + str(r["sends"]))
    K.rec("B2.R6-03.bounded", spins <= 200, "unwind_machine invocations=%d" % spins)
    K.rec("B2.R6-03.observable",
          r["error"] is not None or bool(r["action_errors"])
          or bool(r["transitions"]),
          "err=%s action_errors=%d" % (r["error"], len(r["action_errors"])))
    json.dump(r, open(K.STYLE + "_out_b2_r603.json", "w"), indent=1, default=str)

    # --- unwind service fails -> onError -> failed + critical alert -----
    c = with_total(2)
    st = b2_stub(guard_vals={"policy_all_or_none_and_any_failed": True},
                 svc={"unwind_machine": RuntimeError("unwind-down")})
    r = await K.drive(c, st, ["CONFIRM", "LEG_FAILED"])
    K.rec("B2.unwind.onError_failed", r["states"] == ["trade_group.failed"],
          str(r["states"]))
    K.rec("B2.unwind.onError_alert", "raise_critical_alert" in r["actions"],
          str(r["actions"][-4:]))

    # --- onUnhandled defer: ALL_LEGS_FLAT in draft is deferred ----------
    c = with_total(2)
    st = b2_stub()
    r = await K.drive(c, st, ["ALL_LEGS_FLAT", "CONFIRM", "LEG_OPEN",
                              "LEG_OPEN"])
    K.rec("B2.defer.flushed_to_closed", r["states"] == ["trade_group.closed"],
          "states=%s unhandled=%s" % (r["states"], r["unhandled"]))

    # --- guardErrorPolicy raise: a crashed guard surfaces ---------------
    c = with_total(2)
    st = b2_stub(guard_raise=["all_non_skipped_open"])
    r = await K.drive(c, st, ["CONFIRM", "LEG_OPEN"], snapshots=False)
    K.rec("B2.guard_raise.observable",
          bool(r["guard_errors"]) or r["error"] is not None
          or any(not s.get("ok", True) for s in r["sends"]),
          "guard_errors=%s err=%s sends=%s" % (r["guard_errors"][:1],
                                               r["error"], r["sends"][-1:]))

    # --- sync parity on the happy path ---------------------------------
    c = with_total(2)
    sa = b2_stub(); ra = await K.drive(c, sa, ["CONFIRM", "LEG_OPEN",
                                               "LEG_OPEN", "ALL_LEGS_FLAT"],
                                       snapshots=False)
    ss = b2_stub(); ss.sync = True; ss.svc_style = "def"
    rs = K.drive_sync(c, ss, ["CONFIRM", "LEG_OPEN", "LEG_OPEN",
                              "ALL_LEGS_FLAT"])
    K.rec("B2.parity.states", ra["states"] == rs["states"],
          "async=%s sync=%s" % (ra["states"], rs["states"]))
    K.rec("B2.parity.context", ra["context"] == rs["context"], "")
    K.rec("B2.parity.actions", ra["actions"] == rs["actions"],
          "async=%s\nsync=%s" % (ra["actions"], rs["actions"]))


async def main():
    await b2()
    K.dump("res_b2.json")


asyncio.run(main())
