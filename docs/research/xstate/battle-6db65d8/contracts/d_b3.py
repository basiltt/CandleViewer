# -*- coding: utf-8 -*-
"""B3 Leg + B4 OCO + B5 Iceberg end-to-end on 221ce7c."""
from __future__ import annotations
import asyncio, json
import cv221 as K

C3, C4, C5 = K.cfg("B3"), K.cfg("B4"), K.cfg("B5")


def setctx(c, **kw):
    c = K.copy.deepcopy(c)
    c["context"].update(kw)
    return c


def inc(key, d=1):
    def f(i, ctx, e, a):
        ctx[key] = int(ctx.get(key) or 0) + d
    return f


# ================================================================ B3 =======
B3_A = {"bump_close_attempts": inc("close_attempts")}


def s3(**kw):
    g = {"should_skip": False, "passes_preflight": True,
         "lookup_says_live": False, "lookup_says_filled": False,
         "fully_filled": False, "is_flat": True,
         "close_attempts_left": lambda c, e: int(c["close_attempts"]) < 3}
    g.update(kw.pop("guard_vals", {}) or {})
    a = dict(B3_A); a.update(kw.pop("act_impl", {}) or {})
    return K.Stub(C3, guard_vals=g, act_impl=a, **kw)


async def b3():
    # R6-01 class: `pending` has an `always` ladder evaluated at start().
    r = await K.drive(C3, s3(), ["ORDER_OPEN", ("EXEC", {}), "CLOSE", "FLAT"])
    K.rec("B3.happy.terminal", r["states"] == ["leg.closed"], str(r["states"]))
    K.rec("B3.happy.entry_always",
          r["actions"][:2] == ["size_from_profile", "submit_entry_order"],
          str(r["actions"][:3]))
    K.rec("B3.happy.snapshot", r["snapshot_ok"], str(r["notes"])[:200])

    # invariant: should_skip wins the always ladder -> terminal skipped
    r = await K.drive(C3, s3(guard_vals={"should_skip": True}), [])
    K.rec("B3.skip.first_wins", r["states"] == ["leg.skipped"], str(r["states"]))
    # invariant: neither guard -> error (the ladder has a default)
    r = await K.drive(C3, s3(guard_vals={"passes_preflight": False}), [])
    K.rec("B3.preflight_fail.error", r["states"] == ["leg.error"],
          str(r["states"]))

    # R6-01 class: always-into-an-invoked-child. SUBMIT_TIMEOUT -> resolving,
    # which invokes lookup_by_link_id; onDone ladder must settle.
    r = await K.drive(C3, s3(guard_vals={"lookup_says_live": True}),
                      ["SUBMIT_TIMEOUT"])
    K.rec("B3.resolving.live_to_open", r["states"] == ["leg.open"],
          str(r["states"]))
    K.rec("B3.resolving.svc_once",
          r["svc_calls"].count("lookup_by_link_id") == 1, str(r["svc_calls"]))
    r = await K.drive(C3, s3(svc={"lookup_by_link_id": RuntimeError("gone")}),
                      ["SUBMIT_TIMEOUT"])
    K.rec("B3.resolving.onError_error", r["states"] == ["leg.error"],
          str(r["states"]))

    # UNWIND ladder: nested compound with three chained invokes.
    r = await K.drive(C3, s3(), ["ORDER_OPEN", "UNWIND"])
    K.rec("B3.unwind.flat_to_closed", r["states"] == ["leg.closed"],
          str(r["states"]))
    K.rec("B3.unwind.chain_order",
          r["svc_calls"][-3:] == ["cancel_children_svc", "reduce_only_close",
                                  "poll_until_flat"], str(r["svc_calls"]))
    K.rec("B3.unwind.snapshot", r["snapshot_ok"], str(r["notes"])[:200])

    # retry ladder: close fails, reenter close_position up to the guard bound
    r = await K.drive(C3, s3(svc={"reduce_only_close": RuntimeError("no")}),
                      ["ORDER_OPEN", "UNWIND"], snapshots=False)
    n = r["svc_calls"].count("reduce_only_close")
    K.rec("B3.unwind.retry_bounded", 1 <= n <= 5,
          "reduce_only_close x%d states=%s" % (n, r["states"]))
    K.rec("B3.unwind.retry_terminal", r["states"] == ["leg.error"],
          str(r["states"]))
    K.rec("B3.unwind.naked_alert_path", "mark_incomplete" in r["actions"],
          str(r["actions"][-4:]))

    # naked-position invariant: verify_sl onError raises the alert
    r = await K.drive(C3, s3(svc={"reduce_only_close": RuntimeError("no"),
                                  "assert_native_sl": RuntimeError("no sl")}),
                      ["ORDER_OPEN", "UNWIND"], snapshots=False)
    K.rec("B3.unwind.naked_alert_fired",
          "raise_naked_position_alert" in r["actions"], str(r["actions"][-3:]))

    # R6-03 class on B3: rollback + invoke.onDone (note_cancel_failure raises)
    st = s3(svc={"cancel_children_svc": RuntimeError("cx")},
            raising=["note_cancel_failure"])
    r = await asyncio.wait_for(
        K.drive(C3, st, ["ORDER_OPEN", "UNWIND"], snapshots=False), 60)
    spins = r["svc_calls"].count("cancel_children_svc")
    K.rec("B3.R6-03.terminates", not any(s.get("timeout") for s in r["sends"]),
          str(r["sends"]))
    K.rec("B3.R6-03.bounded", spins <= 200,
          "cancel_children_svc x%d states=%s status=%s err=%s"
          % (spins, r["states"], r["status"], r["error"]))
    json.dump(r, open("out_b3_r603.json", "w"), indent=1, default=str)

    # defer: FLAT arrives before CLOSE
    r = await K.drive(C3, s3(), ["ORDER_OPEN", "FLAT", "CLOSE"])
    K.rec("B3.defer.flat_before_close", r["states"] == ["leg.closed"],
          "states=%s unhandled=%s" % (r["states"], r["unhandled"]))

    # sync parity
    ra = await K.drive(C3, s3(), ["ORDER_OPEN", "UNWIND"], snapshots=False)
    ss = s3(); ss.sync = True
    rs = K.drive_sync(C3, ss, ["ORDER_OPEN", "UNWIND"])
    K.rec("B3.parity.states", ra["states"] == rs["states"],
          "async=%s sync=%s" % (ra["states"], rs["states"]))
    K.rec("B3.parity.actions", ra["actions"] == rs["actions"],
          "async=%s\nsync=%s" % (ra["actions"], rs["actions"]))
    K.rec("B3.parity.svc", ra["svc_calls"] == rs["svc_calls"],
          "async=%s sync=%s" % (ra["svc_calls"], rs["svc_calls"]))


async def main():
    await b3()
    K.dump("res_b3.json")


if __name__ == "__main__":
    asyncio.run(main())
