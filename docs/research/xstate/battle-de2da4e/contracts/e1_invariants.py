# -*- coding: utf-8 -*-
"""Step 2 for B6..B10 on 6db65d8: happy path + every catalogue invariant,
run TWICE -- once with every service as `async def` (primary; the lane that
was blind before round 7) and once with every service as plain `def`.

Every scenario goes through cv6db.drive(), which snapshots and restores at
EVERY quiescence point and compares states+context.
"""
from __future__ import annotations
import asyncio, json, os, sys

# Must be set BEFORE cv6db is imported: it reads CV_SVC_STYLE at import.
os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
STYLE = os.environ["CV_SVC_STYLE"]

import cvde as H
from cvde import Stub

TAG = ""


def S(c, **kw):
    kw.setdefault("svc_style", STYLE)
    return Stub(c, **kw)


def leaves(out):
    return [s.split(".", 1)[1] for s in out["states"]]


def rec(name, ok, note=""):
    return H.rec(TAG + name, ok, note)


def mkgate(result=None):
    """Return (svc_value, release) that holds the service open until
    released, in whichever style this pass runs.

    async: a coroutine awaiting an asyncio.Event (the value returned by the
    stub's resolver is awaited by mk_s_async).
    def:   a plain call blocking on a threading.Event in the executor
    thread, which is exactly where 6db65d8 runs plain services.
    """
    res = {"ok": True} if result is None else result
    if STYLE == "async":
        ev = asyncio.Event()

        async def held():
            await ev.wait()
            if isinstance(res, BaseException):
                raise res
            return res

        return (lambda *_a: held()), (lambda: ev.set())
    import threading
    tev = threading.Event()

    def blocking(*_a):
        tev.wait(20)
        if isinstance(res, BaseException):
            raise res
        return res

    return blocking, (lambda: tev.set())


# ===================================================================== B6 ==
async def b6():
    c = H.cfg("B6")
    G = {"slice_qty_below_min_roll_forward": False, "price_limit_breached": False,
         "failures_exhausted": False, "preflight_invalid": False,
         "abort_on_price_limit": False, "final_market_sweep_and_remaining": False,
         "on_disconnect_is_freeze": True}

    # happy: 2 slices then DURATION_END -> completing -> completed
    st = S(c, guard_vals=dict(G))
    o = await H.drive(c, st, ["SLICE_DUE", "SLICE_DUE", "DURATION_END",
                              "CHILDREN_TERMINAL"])
    rec("B6/happy", leaves(o)[:1] == ["completed"] and o["snapshot_ok"],
        json.dumps({"states": o["states"], "svc": o["svc_calls"],
                    "snap": o["snapshot_ok"], "notes": o["notes"]}))

    # INV-B6-a: exactly one bump_slices_done per SLICE_DUE
    rec("B6/INV-a slice counter 1:1",
        o["actions"].count("bump_slices_done") == 2,
        "bumps=%d" % o["actions"].count("bump_slices_done"))

    # INV-B6-c: sub-minimum slice rolls forward WITHOUT invoking submit_child
    st = S(c, guard_vals=dict(G, slice_qty_below_min_roll_forward=True))
    o2 = await H.drive(c, st, ["SLICE_DUE"])
    rec("B6/INV-c sub-min rolls forward, no child",
        leaves(o2) == ["armed"] and "submit_child" not in o2["svc_calls"],
        json.dumps({"states": o2["states"], "svc": o2["svc_calls"]}))

    # INV-B6-d: price_blocked is a visible state; shortfall recorded
    st = S(c, guard_vals=dict(G, price_limit_breached=True))
    o3 = await H.drive(c, st, ["SLICE_DUE", "SLICE_DUE", "PRICE_OK"])
    rec("B6/INV-d price_blocked visible + shortfall",
        "raise_price_limit_notice" in o3["actions"]
        and "record_shortfall" in o3["actions"] and leaves(o3) == ["armed"],
        json.dumps({"acts": o3["actions"], "states": o3["states"]}))

    # defer: event during in-flight invoke is deferred, then applied
    gate, release = mkgate()
    st = S(c, guard_vals=dict(G), svc={"submit_child": gate})
    m, i, p = await H.new_async(c, st)
    await H.send(i, "SLICE_DUE", timeout=3)
    r = await H.send(i, "USER_PAUSE", timeout=3, wait=True)
    dc = i.deferred_count
    release()
    await H.quiesce(i, 10)
    # NOTE: in the `def` lane a plain service runs INLINE inside the
    # macrostep (#116), so the machine is never observably parked in
    # `submitting_slice` and there is nothing to defer. The obligation is
    # the same in both lanes: USER_PAUSE is applied, never lost.
    rec("B6/defer USER_PAUSE across invoke",
        H.ids(i) == ["twap.paused"]
        and (STYLE == "def"
             or (dc == 1
                 and any(d == "deferred" for _e, d in p.unhandled))),
        json.dumps({"deferred": dc, "states": H.ids(i), "unh": p.unhandled,
                    "send": {k: v for k, v in r.items() if k != "receipt"}}))
    await asyncio.wait_for(i.stop(), 5)

    # rollback: raising entry action must NOT half-commit into the invoke
    st = S(c, guard_vals=dict(G), raising=["bump_slices_done"])
    o4 = await H.drive(c, st, ["SLICE_DUE"])
    rec("B6/rollback entry-raise -> no invoke",
        leaves(o4) == ["armed"] and "submit_child" not in o4["svc_calls"],
        json.dumps({"states": o4["states"], "svc": o4["svc_calls"],
                    "aerr": o4["action_errors"]}))

    # strict: undeclared event rejected at the call site
    st = S(c, guard_vals=dict(G))
    m, i, p = await H.new_async(c, st)
    r = await H.send(i, "NOT_A_REAL_EVENT")
    rec("B6/strict unknown event refused",
        (not r["ok"]) and "Unknown" in str(r.get("exc", "")),
        json.dumps({k: v for k, v in r.items() if k != "receipt"}))
    await asyncio.wait_for(i.stop(), 5)

    # onError retry then exhaustion
    st = S(c, guard_vals=dict(G), svc={"submit_child": RuntimeError("rej")})
    o5 = await H.drive(c, st, ["SLICE_DUE"])
    rec("B6/onError retry records shortfall",
        leaves(o5) == ["armed"] and "bump_failure" in o5["actions"],
        json.dumps({"states": o5["states"], "acts": o5["actions"]}))
    st = S(c, guard_vals=dict(G, failures_exhausted=True),
           svc={"submit_child": RuntimeError("rej")})
    o6 = await H.drive(c, st, ["SLICE_DUE"])
    rec("B6/onError exhausted -> failed", leaves(o6) == ["failed"],
        json.dumps(o6["states"]))

    # guardErrorPolicy raise
    st = S(c, guard_vals=dict(G), guard_raise=["price_limit_breached"])
    m, i, p = await H.new_async(c, st)
    r = await H.send(i, "SLICE_DUE", wait=True)
    rcp = r.get("receipt")
    rec("B6/guardErrorPolicy raise surfaces",
        bool(p.guard_errors) and getattr(rcp, "error", None) is not None,
        json.dumps({"send": {k: v for k, v in r.items() if k != "receipt"},
                    "states": H.ids(i), "gerr": p.guard_errors}))
    await asyncio.wait_for(i.stop(), 5)

    # always -> failed at preflight (always chain at initial descent)
    st = S(c, guard_vals=dict(G, preflight_invalid=True))
    m, i, p = await H.new_async(c, st)
    rec("B6/preflight always -> failed", H.ids(i) == ["twap.failed"],
        json.dumps(H.ids(i)))
    await asyncio.wait_for(i.stop(), 5)


# ===================================================================== B7 ==
async def b7():
    c = H.cfg("B7")
    G = {"beyond_max_chase_ticks": False, "repricings_exhausted": False,
         "drift_over_threshold_and_interval_elapsed_and_budget_ok": True,
         "error_is_order_not_found_after_fill": False,
         "failures_exhausted": False, "on_timeout_is_market": False,
         "on_timeout_is_cancel": False, "on_disconnect_is_freeze": True}

    st = S(c, guard_vals=dict(G))
    o = await H.drive(c, st, ["BOOK_TARGET_MOVED", "CHILD_FILLED",
                              "CHILDREN_TERMINAL"])
    rec("B7/happy arming->working->repricing->completed",
        leaves(o) == ["completed"] and o["snapshot_ok"],
        json.dumps({"states": o["states"], "svc": o["svc_calls"],
                    "snap": o["snapshot_ok"], "notes": o["notes"]}))

    # INV-B7-b: cannot reprice without recomputing target excluding own size
    a = o["actions"]
    rec("B7/INV-b recompute bound 1:1 to reprice",
        a.count("compute_target_excluding_own_size") == a.count("bump_repricings")
        == 1, json.dumps(a))

    # INV-B7-a: bound exceeded is a VISIBLE state (both bounds)
    for g in ("beyond_max_chase_ticks", "repricings_exhausted"):
        st = S(c, guard_vals=dict(G, **{g: True}))
        ob = await H.drive(c, st, ["BOOK_TARGET_MOVED"])
        rec("B7/INV-a %s -> bound_exceeded->parked" % g,
            leaves(ob) == ["parked"] and "raise_warning_alert" in ob["actions"],
            json.dumps({"states": ob["states"], "acts": ob["actions"]}))

    # INV-B7-c: rate budget parks, does NOT queue amendments
    st = S(c, guard_vals=dict(G))
    oc = await H.drive(c, st, ["RATE_BUDGET_EXHAUSTED"])
    rec("B7/INV-c rate budget parks, no amend",
        leaves(oc) == ["paused"] and "amend_child_price" not in oc["svc_calls"],
        json.dumps({"states": oc["states"], "svc": oc["svc_calls"]}))

    # INV-B7-e: timing_out never silently leaves a resting order
    for pol, want in (({"on_timeout_is_market": True}, "completing"),
                      ({"on_timeout_is_cancel": True}, "cancelled"),
                      ({}, "parked")):
        st = S(c, guard_vals=dict(G, **pol))
        oe = await H.drive(c, st, ["TIMEOUT"])
        ok = leaves(oe) == [want]
        rec("B7/INV-e timeout policy %s -> %s" % (pol or "neither", want), ok,
            json.dumps({"states": oe["states"], "svc": oe["svc_calls"]}))

    # amend onError = order-not-found-after-fill -> completing (not a failure)
    st = S(c, guard_vals=dict(G, error_is_order_not_found_after_fill=True),
           svc={"amend_child_price": RuntimeError("order not found")})
    of = await H.drive(c, st, ["BOOK_TARGET_MOVED"])
    rec("B7/amend onError fill-race -> completing",
        leaves(of) == ["completing"], json.dumps(of["states"]))

    # USER_CANCEL deferred across an in-flight amend, then cancels
    gate, release = mkgate()
    st = S(c, guard_vals=dict(G), svc={"amend_child_price": gate})
    m, i, p = await H.new_async(c, st)
    await H.send(i, "BOOK_TARGET_MOVED", timeout=3)
    await H.send(i, "USER_CANCEL", timeout=3, wait=True)
    dc = i.deferred_count
    release()
    await H.quiesce(i, 10)
    rec("B7/defer USER_CANCEL across amend",
        H.ids(i) == ["chase.cancelled"]
        and (STYLE == "def" or dc == 1),
        json.dumps({"deferred": dc, "states": H.ids(i), "unh": p.unhandled}))
    await asyncio.wait_for(i.stop(), 5)

    # rollback across the repricing entry: a raise must not arm the amend
    st = S(c, guard_vals=dict(G), raising=["bump_repricings"])
    orb = await H.drive(c, st, ["BOOK_TARGET_MOVED"])
    rec("B7/rollback repricing entry -> no amend",
        leaves(orb) == ["working"]
        and "amend_child_price" not in orb["svc_calls"],
        json.dumps({"states": orb["states"], "svc": orb["svc_calls"],
                    "aerr": orb["action_errors"]}))

    # arming onError -> failed
    st = S(c, guard_vals=dict(G), svc={"submit_initial_limit": RuntimeError("x")})
    oa = await H.drive(c, st, [])
    rec("B7/arming onError -> failed", leaves(oa) == ["failed"],
        json.dumps({"states": oa["states"], "acts": oa["actions"]}))


# ===================================================================== B8 ==
async def b8():
    c = H.cfg("B8")
    G = {"attach_attempts_left": True, "exchange_reports_sl": True,
         "tightens_only": True, "explicit_audited_override": False,
         "sl_observed": True}

    st = S(c, guard_vals=dict(G))
    o = await H.drive(c, st, ["POSITION_OPENED", "SCAN_DUE"])
    rec("B8/happy flat->attaching->verifying->protected",
        o["states"] == ["position_protection.sl.protected",
                        "position_protection.watchdog.scanning"]
        and o["snapshot_ok"],
        json.dumps({"states": o["states"], "svc": o["svc_calls"],
                    "snap": o["snapshot_ok"], "notes": o["notes"]}))

    # INV-B8-a: verification is mandatory -- attach onDone lands in verifying,
    # and an exchange that does NOT report the SL goes naked, never protected.
    st = S(c, guard_vals=dict(G, exchange_reports_sl=False))
    o2 = await H.drive(c, st, ["POSITION_OPENED"])
    naked = "position_protection.sl.naked" in o2["states"]
    rec("B8/INV-a unverified -> naked, never protected",
        ("position_protection.sl.protected" not in o2["states"])
        and ("stamp_naked_since" in o2["actions"]),
        json.dumps({"states": o2["states"], "acts": o2["actions"][:12]}))

    # INV-B8-b: naked is loud (critical alert + metric) and self-heals
    rec("B8/INV-b naked raises critical + metric",
        "raise_critical_alert" in o2["actions"]
        and "emit_naked_metric" in o2["actions"],
        json.dumps(o2["actions"]))

    # naked fallback fails -> naked_unrecoverable pages the owner
    st = S(c, guard_vals=dict(G, exchange_reports_sl=False),
           svc={"attach_fallback_sl": RuntimeError("no")})
    o3 = await H.drive(c, st, ["POSITION_OPENED"])
    rec("B8/naked fallback fails -> unrecoverable + page",
        "position_protection.sl.naked_unrecoverable" in o3["states"]
        and "page_owner" in o3["actions"],
        json.dumps({"states": o3["states"], "acts": o3["actions"][-6:]}))

    # INV-B8-c: LOOSEN_SL is refused without an explicit audited override
    st = S(c, guard_vals=dict(G))
    o4 = await H.drive(c, st, ["POSITION_OPENED", "LOOSEN_SL"])
    rec("B8/INV-c loosen refused without override",
        "position_protection.sl.protected" in o4["states"]
        and "set_trading_stop" not in o4["svc_calls"],
        json.dumps({"states": o4["states"], "svc": o4["svc_calls"]}))
    st = S(c, guard_vals=dict(G, explicit_audited_override=True))
    o5 = await H.drive(c, st, ["POSITION_OPENED", "LOOSEN_SL"])
    rec("B8/INV-c loosen allowed WITH override, re-verified",
        "set_trading_stop" in o5["svc_calls"]
        and o5["svc_calls"].count("read_position_sl") == 2,
        json.dumps({"states": o5["states"], "svc": o5["svc_calls"]}))

    # INV-B8-d: watchdog miss drives sl -> naked; regions are independent
    st = S(c, guard_vals=dict(G, sl_observed=False))
    o6 = await H.drive(c, st, ["POSITION_OPENED", "SCAN_DUE", "WATCHDOG_MISS"])
    rec("B8/INV-d watchdog miss -> naked (visited, then self-heals)",
        "bump_miss_counter" in o6["actions"]
        and "stamp_naked_since" in o6["actions"]
        and "raise_critical_alert" in o6["actions"]
        and "position_protection.watchdog.scanning" in o6["states"],
        json.dumps({"states": o6["states"], "acts": o6["actions"][-8:]}))

    # attach retry: reenter:true on onError must re-run the entry actions
    st = S(c, guard_vals=dict(G), svc={"attach_native_sl": RuntimeError("rej")})
    o7 = await H.drive(c, st, ["POSITION_OPENED"])
    rec("B8/attach reenter retry re-runs entry (bounded by guard)",
        o7["actions"].count("bump_attach_attempts") >= 2,
        json.dumps({"n": o7["actions"].count("bump_attach_attempts"),
                    "states": o7["states"], "err": o7["error"],
                    "notes": o7["notes"]}))

    # actionErrorPolicy is `fail` on B8 (as catalogued): a raising entry
    # action must NOT be swallowed.
    st = S(c, guard_vals=dict(G), raising=["arm_sl_deadline"])
    m, i, p = await H.new_async(c, st)
    r = await H.send(i, "POSITION_OPENED", timeout=4)
    await H.quiesce(i, 4)
    rec("B8/actionErrorPolicy=fail surfaces entry raise",
        bool(p.action_errors) or (not r["ok"]) or i.status != "running",
        json.dumps({"aerr": p.action_errors, "status": i.status,
                    "send": {k: v for k, v in r.items() if k != "receipt"}}))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


# ===================================================================== B9 ==
async def b9():
    c = H.cfg("B9")
    G = {"promotion_gate_satisfied_and_permitted": True, "debounce_blocked": False,
         "data_stale": False, "limits_blocked": False,
         "condition_true_and_requires_confirmation": False, "condition_true": True,
         "error_budget_exhausted": False, "once_satisfied": False,
         "rearm_permitted_and_elevated": True}

    st = S(c, guard_vals=dict(G))
    o = await H.drive(c, st, ["SAVE", "ARM_REQUESTED", "TRIGGER", "COOLDOWN_DUE"])
    rec("B9/happy draft->sim->armed->evaluating->acting->cooling->armed",
        leaves(o) == ["armed"] and "record_fire" in o["actions"]
        and o["snapshot_ok"],
        json.dumps({"states": o["states"], "svc": o["svc_calls"],
                    "snap": o["snapshot_ok"], "notes": o["notes"]}))

    # INV-B9-a: simulation is mandatory -- SAVE can only reach `simulating`,
    # and promotion is gated.
    st = S(c, guard_vals=dict(G, promotion_gate_satisfied_and_permitted=False))
    o2 = await H.drive(c, st, ["SAVE", "ARM_REQUESTED"])
    rec("B9/INV-a promotion gate refuses with a reason",
        leaves(o2) == ["simulating"]
        and "reject_promotion_with_reason" in o2["actions"],
        json.dumps({"states": o2["states"], "acts": o2["actions"]}))

    # INV-B9-b: every skip reason is recorded, never a silent drop
    for g, act in (("debounce_blocked", "record_skip_debounced"),
                   ("data_stale", "record_skip_stale_data"),
                   ("limits_blocked", "record_skip_limit")):
        st = S(c, guard_vals=dict(G, **{g: True}))
        o3 = await H.drive(c, st, ["SAVE", "ARM_REQUESTED", "TRIGGER"])
        rec("B9/INV-b skip %s recorded, stays armed" % g,
            leaves(o3) == ["armed"] and act in o3["actions"]
            and "evaluate_condition_dag" not in o3["svc_calls"],
            json.dumps({"states": o3["states"], "acts": o3["actions"][-4:],
                        "svc": o3["svc_calls"]}))

    # INV-B9-c: confirmation path cannot be bypassed
    st = S(c, guard_vals=dict(G, condition_true_and_requires_confirmation=True))
    o4 = await H.drive(c, st, ["SAVE", "ARM_REQUESTED", "TRIGGER"])
    rec("B9/INV-c requires-confirmation parks in pending_confirmation",
        leaves(o4) == ["pending_confirmation"]
        and "dispatch_actions_in_order" not in o4["svc_calls"]
        and "arm_confirmation_ttl" in o4["actions"],
        json.dumps({"states": o4["states"], "svc": o4["svc_calls"]}))
    st = S(c, guard_vals=dict(G, condition_true_and_requires_confirmation=True))
    o5 = await H.drive(c, st, ["SAVE", "ARM_REQUESTED", "TRIGGER", "REJECTED"])
    rec("B9/INV-c rejection records a skip, no dispatch",
        leaves(o5) == ["armed"] and "record_skip_rejected" in o5["actions"]
        and "dispatch_actions_in_order" not in o5["svc_calls"],
        json.dumps({"states": o5["states"], "svc": o5["svc_calls"]}))

    # INV-B9-d: a partial fire is recorded AND alerted, never silent
    st = S(c, guard_vals=dict(G),
           svc={"dispatch_actions_in_order": RuntimeError("partial")})
    o6 = await H.drive(c, st, ["SAVE", "ARM_REQUESTED", "TRIGGER"])
    rec("B9/INV-d partial fire recorded + alerted",
        leaves(o6) == ["cooling_down"]
        and "record_partial_fire" in o6["actions"]
        and "raise_partial_alert" in o6["actions"],
        json.dumps({"states": o6["states"], "acts": o6["actions"][-5:]}))

    # INV-B9-e: kill_switched needs a HUMAN re-arm, and is gated
    st = S(c, guard_vals=dict(G, error_budget_exhausted=True),
           svc={"evaluate_condition_dag": RuntimeError("boom")})
    o7 = await H.drive(c, st, ["SAVE", "ARM_REQUESTED", "TRIGGER"])
    rec("B9/INV-e error budget -> kill_switched + critical",
        leaves(o7) == ["kill_switched"]
        and "raise_critical_alert" in o7["actions"],
        json.dumps({"states": o7["states"], "acts": o7["actions"][-4:]}))
    st = S(c, guard_vals=dict(G, error_budget_exhausted=True,
                              rearm_permitted_and_elevated=False),
           svc={"evaluate_condition_dag": RuntimeError("boom")})
    o8 = await H.drive(c, st, ["SAVE", "ARM_REQUESTED", "TRIGGER", "HUMAN_REARM"])
    rec("B9/INV-e un-elevated HUMAN_REARM refused",
        leaves(o8) == ["kill_switched"], json.dumps(o8["states"]))

    # `once` semantics: cooling_down always -> spent
    st = S(c, guard_vals=dict(G, once_satisfied=True))
    o9 = await H.drive(c, st, ["SAVE", "ARM_REQUESTED", "TRIGGER"])
    rec("B9/once_satisfied always -> spent", leaves(o9) == ["spent"],
        json.dumps(o9["states"]))

    # exit action must run on every way out of `armed`
    st = S(c, guard_vals=dict(G))
    o10 = await H.drive(c, st, ["SAVE", "ARM_REQUESTED", "KILL_SWITCH"])
    rec("B9/armed exit unsubscribes on kill switch",
        "unsubscribe_triggers" in o10["actions"]
        and leaves(o10) == ["kill_switched"],
        json.dumps({"acts": o10["actions"][-4:], "states": o10["states"]}))


# ==================================================================== B10 ==
async def b10():
    c = H.cfg("B10")
    G = {"in_storm_window": False, "all_channels_ok": True,
         "delivery_attempts_left": True}

    st = S(c, guard_vals=dict(G))
    o = await H.drive(c, st, ["CONDITION_MET", "ACK", "RESOLVE"])
    rec("B10/happy armed->firing->delivered->ack->resolved",
        leaves(o) == ["resolved"] and o["snapshot_ok"],
        json.dumps({"states": o["states"], "svc": o["svc_calls"],
                    "snap": o["snapshot_ok"], "notes": o["notes"]}))

    # INV-B10-a: storm window suppresses and COUNTS, never silently drops
    st = S(c, guard_vals=dict(G, in_storm_window=True))
    o2 = await H.drive(c, st, ["CONDITION_MET"])
    rec("B10/INV-a storm -> suppressed + counted + metric",
        leaves(o2) == ["suppressed"] and "bump_storm_count" in o2["actions"]
        and "emit_suppression_metric" in o2["actions"]
        and "dispatch_to_channels" not in o2["svc_calls"],
        json.dumps({"states": o2["states"], "acts": o2["actions"]}))

    # INV-B10-b: partial delivery is a distinct, degraded-tagged state
    st = S(c, guard_vals=dict(G, all_channels_ok=False))
    o3 = await H.drive(c, st, ["CONDITION_MET"])
    rec("B10/INV-b partial delivery is its own degraded state",
        leaves(o3) == ["partially_delivered"], json.dumps(o3["states"]))

    # INV-B10-c: retry is bounded and observable; exhaustion is loud
    st = S(c, guard_vals=dict(G),
           svc={"dispatch_to_channels": RuntimeError("smtp")})
    o4 = await H.drive(c, st, ["CONDITION_MET", "RETRY_DUE"])
    rec("B10/INV-c retry bounded, attempts bumped",
        leaves(o4) == ["retrying"]
        and o4["actions"].count("bump_delivery_attempts") == 2
        and o4["actions"].count("schedule_backoff_deadline") == 2,
        json.dumps({"states": o4["states"], "acts": o4["actions"]}))
    st = S(c, guard_vals=dict(G, delivery_attempts_left=False),
           svc={"dispatch_to_channels": RuntimeError("smtp")})
    o5 = await H.drive(c, st, ["CONDITION_MET"])
    rec("B10/INV-c exhaustion -> delivery_failed + metric",
        leaves(o5) == ["delivery_failed"]
        and "emit_delivery_failure_metric" in o5["actions"],
        json.dumps({"states": o5["states"], "acts": o5["actions"]}))

    # persist-before-dispatch ordering: the fired row is written BEFORE the
    # channel service is ever called (INV-B10-d, audit obligation).
    st = S(c, guard_vals=dict(G))
    order = []
    st.act_impl = {"persist_fired_row":
                   lambda i, ctx, e, ad: order.append("persist")}
    base_svc = st.svc

    def watch(*_a):
        order.append("dispatch")
        return {"ok": True}
    st.svc = dict(base_svc, dispatch_to_channels=watch)
    o6 = await H.drive(c, st, ["CONDITION_MET"], snapshots=False)
    rec("B10/INV-d persist_fired_row precedes dispatch",
        order[:2] == ["persist", "dispatch"], json.dumps(order))

    # ACK while retrying short-circuits to acknowledged (operator wins)
    st = S(c, guard_vals=dict(G),
           svc={"dispatch_to_channels": RuntimeError("smtp")})
    o7 = await H.drive(c, st, ["CONDITION_MET", "ACK", "RESOLVE"])
    rec("B10/ACK during retry -> acknowledged -> resolved",
        leaves(o7) == ["resolved"], json.dumps(o7["states"]))

    # DISABLE / ENABLE round trip; disabled ignores CONDITION_MET per contract
    st = S(c, guard_vals=dict(G))
    m, i, p = await H.new_async(c, st)
    await H.send(i, "DISABLE", timeout=3)
    r = await H.send(i, "CONDITION_MET", timeout=3)
    await H.quiesce(i, 3)
    st_mid = H.ids(i)
    dc = i.deferred_count
    await H.send(i, "ENABLE", timeout=3)
    await H.quiesce(i, 4)
    rec("B10/disabled defers CONDITION_MET, applied on ENABLE",
        st_mid == ["alert.disabled"] and dc == 1
        and H.ids(i) in (["alert.firing"], ["alert.delivered"]),
        json.dumps({"mid": st_mid, "deferred": dc, "after": H.ids(i),
                    "unh": p.unhandled}))
    await asyncio.wait_for(i.stop(), 5)


async def main():
    for fn in (b6, b7, b8, b9, b10):
        try:
            await fn()
        except Exception as e:
            import traceback
            H.rec(TAG + fn.__name__ + "/CRASH", False, repr(e))
            traceback.print_exc()
    H.dump("e1_invariants_%s.json" % STYLE)


asyncio.run(main())
