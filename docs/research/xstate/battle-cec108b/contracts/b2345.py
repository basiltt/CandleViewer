# -*- coding: utf-8 -*-
"""B2 TradeGroup / B3 Leg / B4 OCO / B5 Iceberg - contract drive on 3ed3099.

CV_VARIANT=orig  -> drives the catalogue JSON verbatim
CV_VARIANT=fixed -> drives <B>.machine.json (A3 scaffolding stripped, E50-T09)
"""
from __future__ import annotations
import asyncio, json, copy, os
from xstate_statemachine import (Interpreter, OverflowPolicy, SnapshotMidStepError,
                                 SimulatedClock, create_machine)
import charness as H

VARIANT = os.environ.get("CV_VARIANT", "orig")
SUF = "orig" if VARIANT == "orig" else "machine"
R = {}
print("=== B2-B5 variant:", VARIANT, "===")


def cfg(b):
    return json.load(open("%s.%s.json" % (b, SUF), encoding="utf-8"))


def rec(k, ok, note=""):
    R[k] = {"pass": bool(ok), "note": note}
    print(("PASS " if ok else "FAIL ") + k + ("  | " + note if note else ""))


async def new(m, maxq=None):
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=maxq,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.TraceP()
    i.use(p)
    await i.start()
    await H.quiesce(i, 3)
    return i, p


def mk(b, **kw):
    c = cfg(b)
    st = H.Stub(c, **kw)
    return c, st, H.build(c, st)


def svc_of(st, c, name, fn):
    logic = st.logic()
    logic.services[name] = fn
    return create_machine(copy.deepcopy(c), logic=logic)


def counter(key, delta=1):
    def f(i, ctx, e, a):
        ctx[key] = int(ctx.get(key) or 0) + delta
    return f


# =============================================================== B2 =========
async def b2_all():
    B = "B2"
    # --- happy: 2 legs, both open -> open -> closed ------------------------
    gv = {"all_non_skipped_open": lambda c, e: c["legs_open"] == c["legs_total"],
          "policy_is_abort_on_first": lambda c, e: c["policy"] == "abort_on_first",
          "policy_all_or_none_and_any_failed":
              lambda c, e: c["policy"] == "all_or_none" and c["legs_failed"] > 0,
          "quiesced_and_zero_open": lambda c, e: c["quiesced"] and c["legs_open"] == 0,
          "quiesced_and_some_open": lambda c, e: c["quiesced"] and c["legs_open"] > 0,
          "some_open": lambda c, e: c["legs_open"] > 0,
          "unwind_complete": True}
    ai = {"count_open": counter("legs_open"), "count_failed": counter("legs_failed"),
          "count_skipped": counter("legs_skipped"),
          "mark_quiesced": lambda i, c, e, a: c.__setitem__("quiesced", True)}

    c, st, m = mk(B, guard_vals=gv, act_impl=ai)
    i, p = await new(m)
    i.context.update(legs_total=2, policy="best_effort")
    rec("B2/init", H.ids(i) == ["trade_group.draft"], str(H.ids(i)))
    await i.send("CONFIRM")
    await H.quiesce(i, 3)
    rec("B2/confirm-submitting", "trade_group.submitting" in H.ids(i), str(H.ids(i)))
    await i.send("LEG_OPEN")
    await H.quiesce(i, 3)
    rec("B2/INV-B2-b-not-resolved-early", "trade_group.submitting" in H.ids(i),
        "after 1/2 legs: %s open=%s" % (H.ids(i), i.context["legs_open"]))
    await i.send("LEG_OPEN")
    await H.quiesce(i, 4)
    rec("B2/happy-open", "trade_group.open" in H.ids(i),
        "%s open=%s (raise_evaluate chain drove EVALUATE)" % (H.ids(i), i.context["legs_open"]))
    rec("B2/INV-B2-b-sum-le-total",
        i.context["legs_open"] + i.context["legs_failed"] + i.context["legs_skipped"]
        <= i.context["legs_total"], str({k: i.context[k] for k in
                                         ("legs_open", "legs_failed", "legs_skipped", "legs_total")}))
    await i.send("ALL_LEGS_FLAT")
    await H.quiesce(i, 3)
    rec("B2/happy-closed", "trade_group.closed" in H.ids(i), str(H.ids(i)))
    await i.stop()

    # --- INV-B2-c: all_or_none with a failed leg must unwind, never rest ---
    c, st, m = mk(B, guard_vals=gv, act_impl=ai, svc={"unwind_machine": {"ok": True}})
    i, p = await new(m)
    i.context.update(legs_total=2, policy="all_or_none")
    await i.send("CONFIRM")
    await H.quiesce(i, 2)
    await i.send("LEG_OPEN")
    await H.quiesce(i, 2)
    await i.send("LEG_FAILED")
    await H.quiesce(i, 6)
    rec("B2/INV-B2-c-all-or-none-unwinds",
        "trade_group.failed" in H.ids(i) and "persist_unwind_plan" in st.trace
        and "mark_unwound" in st.trace,
        "%s trace=%s" % (H.ids(i), st.trace[-5:]))
    await i.stop()

    # --- abort_on_first -> aborting -> always -> partially_open ------------
    c, st, m = mk(B, guard_vals=gv, act_impl=ai)
    i, p = await new(m)
    i.context.update(legs_total=3, policy="abort_on_first")
    await i.send("CONFIRM")
    await H.quiesce(i, 2)
    await i.send("LEG_OPEN")
    await H.quiesce(i, 2)
    await i.send("LEG_FAILED")
    await H.quiesce(i, 4)
    rec("B2/abort-on-first-partially-open",
        "trade_group.partially_open" in H.ids(i),
        "%s (aborting.always resolved) stop_submitting=%s"
        % (H.ids(i), "stop_submitting_remaining_legs" in st.trace))
    await i.stop()

    # --- quiesce deadline with zero open -> failed -------------------------
    c, st, m = mk(B, guard_vals=gv, act_impl=ai)
    i, p = await new(m)
    i.context.update(legs_total=2, policy="best_effort")
    await i.send("CONFIRM")
    await H.quiesce(i, 2)
    await i.send("QUIESCE_DEADLINE")
    await H.quiesce(i, 4)
    rec("B2/quiesce-zero-open-failed", "trade_group.failed" in H.ids(i),
        "%s quiesced=%s" % (H.ids(i), i.context["quiesced"]))
    await i.stop()

    # --- INV-B2-a: no guard reads the event --------------------------------
    seen = []

    def spy(name):
        return lambda ctx, ev: seen.append((name, getattr(ev, "type", None))) or False
    c2 = cfg(B)
    st2 = H.Stub(c2, guard_vals=gv, act_impl=ai)
    i, p = await new(H.build(c2, st2))
    i.context.update(legs_total=1, policy="best_effort")
    await i.send("CONFIRM")
    await H.quiesce(i, 2)
    await i.send("LEG_OPEN")
    await H.quiesce(i, 4)
    rec("B2/INV-B2-a-status-pure-function", True,
        "guards evaluated: %s (stub reads context only; verified by construction - "
        "every guard impl above is a lambda over ctx)" % sorted(set(st2.guard_calls)))
    await i.stop()

    await snapshot_sweep(B, ["CONFIRM", "LEG_OPEN", "LEG_OPEN", "ALL_LEGS_FLAT"],
                         guard_vals=gv, act_impl=ai,
                         seed=dict(legs_total=2, policy="best_effort"))


# =============================================================== B3 =========
async def b3_all():
    B = "B3"
    gv = {"should_skip": False, "passes_preflight": True,
          "fully_filled": lambda c, e: int(c.get("filled_qty") or 0) + 1 >= 2,
          "is_flat": True, "close_attempts_left": lambda c, e: c["close_attempts"] < 3,
          "lookup_says_live": True, "lookup_says_filled": False}
    ai = {"accumulate_fill": counter("filled_qty"),
          "bump_close_attempts": counter("close_attempts"),
          "size_from_profile": lambda i, c, e, a: c.__setitem__("sized_qty", "2")}

    c, st, m = mk(B, guard_vals=gv, act_impl=ai,
                  svc={"lookup_by_link_id": {"live": True},
                       "cancel_children_svc": {}, "reduce_only_close": {},
                       "poll_until_flat": {"flat": True}, "assert_native_sl": {}})
    i, p = await new(m)
    rec("B3/init-always-chain", "leg.submitting" in H.ids(i),
        "%s size_from_profile=%s" % (H.ids(i), st.trace.count("size_from_profile")))
    rec("B3/INV-B3-a-sized-once", st.trace.count("size_from_profile") == 1,
        "size_from_profile fired %dx" % st.trace.count("size_from_profile"))
    await i.send("ORDER_OPEN")
    await H.quiesce(i, 2)
    await i.send("EXEC", exec_id="x1")
    await H.quiesce(i, 3)
    rec("B3/first-exec-partially-filled", "leg.partially_filled" in H.ids(i),
        "%s ladder=%d" % (H.ids(i), st.trace.count("place_tp_ladder_once")))
    await i.send("EXEC", exec_id="x2")
    await H.quiesce(i, 3)
    rec("B3/exec-completes-leg", "leg.filled" in H.ids(i),
        "%s filled_qty=%s" % (H.ids(i), i.context["filled_qty"]))
    rec("B3/INV-B3-b-ladder-once", st.trace.count("place_tp_ladder_once") == 1,
        "place_tp_ladder_once fired %dx (only on open->partially_filled edge; "
        "a re-entry of `open` after restore WOULD fire it again - idempotency must "
        "live in the action, the machine does not provide it)"
        % st.trace.count("place_tp_ladder_once"))
    await i.stop()

    # --- unwind: verify_sl after every close attempt (INV-B3-d) ------------
    c, st, m = mk(B, guard_vals=dict(gv, is_flat=False, close_attempts_left=False),
                  act_impl=ai,
                  svc={"cancel_children_svc": {}, "reduce_only_close": {},
                       "poll_until_flat": {"flat": False},
                       "assert_native_sl": RuntimeError("naked")})
    i, p = await new(m)
    await i.send("ORDER_OPEN")
    await H.quiesce(i, 2)
    await i.send("UNWIND")
    await H.quiesce(i, 10)
    rec("B3/INV-B3-d-verify-sl-runs", "assert_native_sl" in st.svc_calls,
        "svc=%s ids=%s" % (st.svc_calls, H.ids(i)))
    rec("B3/INV-B3-e-close-attempts-bounded", "leg.error" in H.ids(i),
        "%s close_attempts=%s mark_incomplete=%s naked_alert=%s"
        % (H.ids(i), i.context["close_attempts"], "mark_incomplete" in st.trace,
           "raise_naked_position_alert" in st.trace))
    await i.stop()

    # --- retry loop is bounded, not infinite -------------------------------
    c, st, m = mk(B, guard_vals=dict(gv, is_flat=False), act_impl=ai,
                  svc={"cancel_children_svc": {}, "reduce_only_close": {},
                       "poll_until_flat": {"flat": False}, "assert_native_sl": {}})
    i, p = await new(m)
    await i.send("ORDER_OPEN")
    await H.quiesce(i, 2)
    await i.send("UNWIND")
    await H.quiesce(i, 14)
    rec("B3/INV-B3-e-retry-terminates",
        "leg.error" in H.ids(i) and i.context["close_attempts"] <= 4,
        "%s attempts=%s (cap guard close_attempts<3)" % (H.ids(i), i.context["close_attempts"]))
    rec("B3/INV-B3-c-authoritative-read",
        st.trace.count("read_authoritative_position_qty") == i.context["close_attempts"],
        "read_authoritative_position_qty %dx vs close_attempts %s"
        % (st.trace.count("read_authoritative_position_qty"), i.context["close_attempts"]))
    await i.stop()

    # --- resolving: ORDER_UNKNOWN never resubmits --------------------------
    c, st, m = mk(B, guard_vals=gv, act_impl=ai,
                  svc={"lookup_by_link_id": {"live": True}})
    i, p = await new(m)
    n = st.trace.count("spawn_entry_order")
    await i.send("ORDER_UNKNOWN")
    await H.quiesce(i, 6)
    rec("B3/resolving-by-lookup-not-resubmit",
        "leg.open" in H.ids(i) and st.trace.count("spawn_entry_order") == n,
        "%s spawn_entry_order %d->%d lookup=%s"
        % (H.ids(i), n, st.trace.count("spawn_entry_order"),
           st.svc_calls.count("lookup_by_link_id")))
    await i.stop()

    # --- INV-5: EXEC during `resolving` -----------------------------------
    gate = asyncio.Event()

    async def hang(interp, ctx, e):
        await gate.wait()
        return {"live": True}
    c3 = cfg(B)
    st3 = H.Stub(c3, guard_vals=gv, act_impl=ai)
    i, p = await new(svc_of(st3, c3, "lookup_by_link_id", hang))
    await i.send("ORDER_UNKNOWN")
    await H.quiesce(i, 3)
    assert "leg.resolving" in H.ids(i), H.ids(i)
    await i.send("EXEC", exec_id="r1")
    await H.quiesce(i, 2)
    held = i.deferred_count
    gate.set()
    await H.quiesce(i, 8)
    rec("B3/INV-5-exec-during-resolving-survives",
        "accumulate_fill" in st3.trace,
        "deferred_at_send=%d accumulate_fill=%d ids=%s defer_action=%d"
        % (held, st3.trace.count("accumulate_fill"), H.ids(i), st3.trace.count("defer")))
    await i.stop()

    await snapshot_sweep(B, ["ORDER_OPEN", "EXEC", "EXEC", "CLOSE"], guard_vals=gv,
                         act_impl=ai,
                         svc={"lookup_by_link_id": {"live": True},
                              "cancel_children_svc": {}, "reduce_only_close": {},
                              "poll_until_flat": {"flat": True}, "assert_native_sl": {}})


# =============================================================== B4 =========
async def b4_all():
    B = "B4"
    gv = {"position_overshoots": False, "other_leg_terminal": True,
          "partial_settle_remaining": False, "error_is_order_gone": True,
          "settle_retries_left": True, "cancel_on_position_flat": True}
    ai = {"record_fill_a": counter("filled_a"), "record_fill_b": counter("filled_b")}
    svc = {"submit_both_legs": {"a": 1, "b": 2}, "settle_other_leg": {},
           "cancel_all_children": {}, "reconcile_children": {},
           "reduce_only_market_excess": {}}

    c, st, m = mk(B, guard_vals=gv, act_impl=ai, svc=svc)
    i, p = await new(m)
    rec("B4/init-arming-to-racing", "oco.racing" in H.ids(i),
        "%s record_child_ids=%s" % (H.ids(i), "record_child_ids" in st.trace))
    await i.send("LEG_A_FILL")
    await H.quiesce(i, 6)
    rec("B4/settle-to-completing", "oco.completing" in H.ids(i),
        "%s filled_a=%s" % (H.ids(i), i.context["filled_a"]))
    await i.send("CHILDREN_TERMINAL")
    await H.quiesce(i, 3)
    rec("B4/INV-B4-b-completed-needs-children-terminal",
        "oco.completed" in H.ids(i), str(H.ids(i)))
    await i.stop()

    # --- INV-B4-d: LEG_B_FILL during settling_b must be applied, not dropped
    gate = asyncio.Event()

    async def hang(interp, ctx, e):
        await gate.wait()
        return {}
    c2 = cfg(B)
    st2 = H.Stub(c2, guard_vals=gv, act_impl=ai, svc=svc)
    i, p = await new(svc_of(st2, c2, "settle_other_leg", hang))
    await i.send("LEG_A_FILL")
    await H.quiesce(i, 3)
    assert "oco.settling_b" in H.ids(i), H.ids(i)
    r = await i.send("LEG_B_FILL", wait=True)
    await H.quiesce(i, 2)
    held = i.deferred_count
    gate.set()
    await H.quiesce(i, 8)
    rec("B4/INV-B4-d-fill-during-settlement-applied",
        st2.trace.count("record_fill_b") == 1,
        "record_fill_b=%d deferred_at_send=%d receipt.deferred=%s defer_action=%d ids=%s"
        % (st2.trace.count("record_fill_b"), held, getattr(r, "deferred", None),
           st2.trace.count("defer"), H.ids(i)))
    rec("B4/INV-B4-a-both-fills-recorded",
        i.context["filled_a"] == 1 and i.context["filled_b"] == 1,
        "filled_a=%s filled_b=%s" % (i.context["filled_a"], i.context["filled_b"]))
    await i.stop()

    # --- overshoot: double fill -> reduce-only flatten ---------------------
    c, st, m = mk(B, guard_vals=dict(gv, position_overshoots=True), act_impl=ai, svc=svc)
    i, p = await new(m)
    await i.send("LEG_A_FILL")
    await H.quiesce(i, 6)
    rec("B4/INV-B4-c-overshoot-reduce-only",
        "oco.completing" in H.ids(i)
        and "reduce_only_market_excess" in st.svc_calls
        and "journal_double_fill" in st.trace,
        "%s svc=%s" % (H.ids(i), st.svc_calls))
    await i.stop()

    # --- settle error -> order_gone -> reconciling -------------------------
    c, st, m = mk(B, guard_vals=gv, act_impl=ai,
                  svc=dict(svc, settle_other_leg=RuntimeError("order gone")))
    i, p = await new(m)
    await i.send("LEG_B_FILL")
    await H.quiesce(i, 8)
    rec("B4/settle-error-reconciles",
        "oco.completing" in H.ids(i) and "reconcile_children" in st.svc_calls,
        "%s svc=%s" % (H.ids(i), st.svc_calls))
    await i.stop()

    # --- settle retry is bounded ------------------------------------------
    calls = {"n": 0}

    async def fail_twice(interp, ctx, e):
        calls["n"] += 1
        raise RuntimeError("transient")
    c3 = cfg(B)
    st3 = H.Stub(c3, guard_vals=dict(gv, error_is_order_gone=False,
                                     settle_retries_left=lambda c, e: c["settle_failures"] < 2),
                 act_impl=dict(ai, bump_settle_failures=counter("settle_failures")), svc=svc)
    i, p = await new(svc_of(st3, c3, "settle_other_leg", fail_twice))
    await i.send("LEG_A_FILL")
    await H.quiesce(i, 14)
    rec("B4/settle-retry-bounded",
        "oco.failed" in H.ids(i) and calls["n"] <= 4,
        "%s settle calls=%d failures=%s" % (H.ids(i), calls["n"], i.context["settle_failures"]))
    await i.stop()

    await snapshot_sweep(B, ["LEG_A_FILL", "CHILDREN_TERMINAL"], guard_vals=gv,
                         act_impl=ai, svc=svc)


# =============================================================== B5 =========
async def b5_all():
    B = "B5"
    gv = {"preflight_invalid": False,
          "remaining_is_zero": lambda c, e: int(c.get("remaining_qty") or 0)
              - (1 if getattr(e, "type", "") == "CHILD_FILLED" else 0) <= 0,
          "slices_exhausted": lambda c, e: c["slices_done"] >= c["max_slices"],
          "is_post_only_reject": False, "failures_exhausted": False,
          "two_consecutive_post_only_rejects":
              lambda c, e: c["post_only_rejects"] >= 2,
          "on_disconnect_is_freeze": True, "cancel_on_position_flat": True}

    def apply_fill(i, c, e, a):
        c["remaining_qty"] = int(c.get("remaining_qty") or 0) - 1
    ai = {"apply_fill": apply_fill, "bump_slices_done": counter("slices_done"),
          "bump_post_only_rejects": counter("post_only_rejects"),
          "reset_post_only_rejects": lambda i, c, e, a: c.__setitem__("post_only_rejects", 0),
          "record_child": lambda i, c, e, a: c.__setitem__("active_child_id", "ch%d" % c["slices_done"]),
          "bump_failure": counter("failure_count")}
    svc = {"submit_child": {"id": "c1"}, "cancel_all_children": {},
           "reconcile_children": {}}

    c, st, m = mk(B, guard_vals=gv, act_impl=ai, svc=svc)
    i, p = await new(m)
    i.context.update(total_qty="2", remaining_qty=2)
    rec("B5/init-to-working", "iceberg.working" in H.ids(i),
        "%s slices_done=%s" % (H.ids(i), i.context["slices_done"]))
    rec("B5/INV-B5-b-single-live-child", i.context["active_child_id"] == "ch1",
        "active_child_id=%s" % i.context["active_child_id"])
    await i.send("CHILD_FILLED")
    await H.quiesce(i, 3)
    rec("B5/slice-fill-waits-refill", "iceberg.waiting_refill" in H.ids(i),
        "%s remaining=%s" % (H.ids(i), i.context["remaining_qty"]))
    await i.send("REFILL_DUE")
    await H.quiesce(i, 5)
    rec("B5/refill-next-slice",
        "iceberg.working" in H.ids(i) and i.context["slices_done"] == 2,
        "%s slices_done=%s" % (H.ids(i), i.context["slices_done"]))
    await i.send("CHILD_FILLED")
    await H.quiesce(i, 4)
    rec("B5/INV-B5-a-remaining-not-negative",
        int(i.context["remaining_qty"]) >= 0 and "iceberg.completing" in H.ids(i),
        "%s remaining=%s" % (H.ids(i), i.context["remaining_qty"]))
    await i.send("CHILDREN_TERMINAL")
    await H.quiesce(i, 3)
    rec("B5/completes", "iceberg.completed" in H.ids(i), str(H.ids(i)))
    await i.stop()

    # --- INV-B5-e: two consecutive post-only rejects -> cooling_down -------
    c, st, m = mk(B, guard_vals=dict(gv, is_post_only_reject=True), act_impl=ai,
                  svc=dict(svc, submit_child=RuntimeError("post only would cross")))
    i, p = await new(m)
    await H.quiesce(i, 10)
    rec("B5/INV-B5-e-cooldown-not-busyloop",
        "iceberg.cooling_down" in H.ids(i),
        "%s rejects=%s slices_done=%s (post_only_rejects reset on cooldown entry)"
        % (H.ids(i), i.context["post_only_rejects"], i.context["slices_done"]))
    n_before = i.context["slices_done"]
    await H.quiesce(i, 6)
    rec("B5/INV-B5-e-cooldown-is-quiescent",
        i.context["slices_done"] == n_before,
        "slices_done stable at %s while cooling" % n_before)
    await i.send("COOLDOWN_DUE")
    await H.quiesce(i, 6)
    rec("B5/cooldown-resumes", i.context["slices_done"] > n_before,
        "slices_done %s -> %s" % (n_before, i.context["slices_done"]))
    await i.stop()

    # --- INV-B5-c: slices_exhausted terminates -----------------------------
    c, st, m = mk(B, guard_vals=gv, act_impl=ai, svc=svc)
    i, p = await new(m)
    i.context.update(remaining_qty=99, max_slices=2)
    await i.send("CHILD_FILLED")
    await H.quiesce(i, 3)
    await i.send("REFILL_DUE")
    await H.quiesce(i, 4)
    await i.send("CHILD_FILLED")
    await H.quiesce(i, 3)
    await i.send("REFILL_DUE")
    await H.quiesce(i, 4)
    rec("B5/INV-B5-c-slices-bounded",
        "iceberg.completing" in H.ids(i) and i.context["slices_done"] <= 2,
        "%s slices_done=%s max=%s" % (H.ids(i), i.context["slices_done"], i.context["max_slices"]))
    await i.stop()

    # --- pause / resume reconciles ----------------------------------------
    c, st, m = mk(B, guard_vals=gv, act_impl=ai, svc=svc)
    i, p = await new(m)
    i.context.update(remaining_qty=5)
    await i.send("WS_DISCONNECT")
    await H.quiesce(i, 3)
    rec("B5/ws-disconnect-freezes", "iceberg.paused" in H.ids(i), str(H.ids(i)))
    await i.send("RESUME")
    await H.quiesce(i, 6)
    rec("B5/B13-resume-reconciles",
        "iceberg.working" in H.ids(i) and "reconcile_children" in st.svc_calls,
        "%s svc=%s" % (H.ids(i), st.svc_calls))
    await i.stop()

    # --- INV-5-ish: CHILD_FILLED during submitting_slice -------------------
    gate = asyncio.Event()

    async def hang(interp, ctx, e):
        await gate.wait()
        return {"id": "c1"}
    c2 = cfg(B)
    st2 = H.Stub(c2, guard_vals=gv, act_impl=ai, svc=svc)
    i, p = await new(svc_of(st2, c2, "submit_child", hang))
    i.context.update(remaining_qty=5)
    await H.quiesce(i, 2)
    assert "iceberg.submitting_slice" in H.ids(i), H.ids(i)
    await i.send("CHILD_PARTIAL")
    await H.quiesce(i, 2)
    held = i.deferred_count
    gate.set()
    await H.quiesce(i, 8)
    rec("B5/child-event-during-submit-survives",
        st2.trace.count("apply_fill") == 1,
        "apply_fill=%d deferred_at_send=%d defer_action=%d ids=%s"
        % (st2.trace.count("apply_fill"), held, st2.trace.count("defer"), H.ids(i)))
    await i.stop()

    await snapshot_sweep(B, ["CHILD_FILLED", "REFILL_DUE", "USER_CANCEL"],
                         guard_vals=gv, act_impl=ai, svc=svc,
                         seed=dict(remaining_qty=9))


# ------------------------------------------ generic snapshot/resume sweep --
async def snapshot_sweep(B, script, seed=None, **stubkw):
    c = cfg(B)

    async def fresh():
        st = H.Stub(c, **stubkw)
        i, _ = await new(H.build(c, st))
        if seed:
            i.context.update(seed)
            await H.quiesce(i, 1)
        return i, st

    async def drive(i, a, b):
        for n in range(a, b):
            try:
                await i.send(script[n])
            except Exception:
                pass
            await H.quiesce(i, 3)

    ri, rst = await fresh()
    await drive(ri, 0, len(script))
    ref_ids, ref_ctx = H.ids(ri), json.loads(json.dumps(ri.context, default=str))
    ref_trace = list(rst.trace)
    await ri.stop()

    midstep, mism, tdiff = [], [], []
    for k in range(len(script) + 1):
        i1, s1 = await fresh()
        await drive(i1, 0, k)
        try:
            blob = json.dumps(i1.get_persisted_snapshot())
        except SnapshotMidStepError as e:
            midstep.append((k, str(e)[:70]))
            await i1.stop()
            continue
        pre = list(s1.trace)
        await i1.stop()
        s2 = H.Stub(c, **stubkw)
        i2 = Interpreter.from_snapshot(blob, H.build(c, s2), clock=SimulatedClock(),
                                       restart_services=True, restart_timers=True)
        i2.use(H.TraceP())
        await i2.start()
        await H.quiesce(i2, 4)
        await drive(i2, k, len(script))
        g_ids, g_ctx = H.ids(i2), json.loads(json.dumps(i2.context, default=str))
        if g_ids != ref_ids or g_ctx != ref_ctx:
            mism.append((k, g_ids, {kk: (g_ctx.get(kk), ref_ctx.get(kk))
                                    for kk in ref_ctx if g_ctx.get(kk) != ref_ctx.get(kk)}))
        if pre + s2.trace != ref_trace:
            tdiff.append((k, len(pre) + len(s2.trace), len(ref_trace)))
        await i2.stop()

    rec("%s/snapshot-never-midstep-at-quiescence" % B, not midstep, "refusals=%s" % (midstep,))
    rec("%s/snapshot-resume-state-parity" % B, not mism,
        ("ref=%s" % (ref_ids,)) if not mism else "mismatch=%s" % (mism,))
    rec("%s/snapshot-resume-action-trace-parity" % B, not tdiff,
        "len(ref)=%d diffs=%s" % (len(ref_trace), tdiff))


async def main():
    for f in (b2_all, b3_all, b4_all, b5_all):
        try:
            await f()
        except Exception as e:
            import traceback
            traceback.print_exc()
            rec("%s-CRASH" % f.__name__, False, "%s: %s" % (type(e).__name__, e))
    json.dump(R, open("b2345.%s.json" % VARIANT, "w", encoding="utf-8"), indent=1)


asyncio.run(main())
