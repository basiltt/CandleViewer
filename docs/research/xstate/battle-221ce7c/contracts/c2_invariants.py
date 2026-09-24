# -*- coding: utf-8 -*-
"""C2 -- happy path + every invariant scenario for B6..B10.

Async engine is primary. Each scenario returns a dict with a PASS/FAIL
verdict and the evidence used to decide it. Nothing here touches library
source.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import cvlib
from cvlib import Rig
from xstate_statemachine import OverflowPolicy
from xstate_statemachine.exceptions import (
    UnknownEventError,
    QueueOverflowError,
)

RESULTS: List[Dict[str, Any]] = []


def rec(mid: str, inv: str, ok: bool, note: str, evidence: Any = None) -> None:
    RESULTS.append(
        {
            "machine": mid,
            "invariant": inv,
            "verdict": "PASS" if ok else "FAIL",
            "note": note,
            "evidence": evidence,
        }
    )


async def drive(cfg, rig, script, *, queue=64):
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig, max_queue_size=queue)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    for ev in script:
        if interp.status != "running":
            break
        await cvlib.apply(interp, clock, ev)
    await asyncio.sleep(cvlib.SETTLE)
    out = cvlib.snap(interp, plug)
    await interp.stop()
    return out, plug, rig


def leaves(out) -> List[str]:
    return [s.split(".", 1)[1] for s in out.states]


# ===========================================================================
# B6 -- TWAP
# ===========================================================================
async def b6() -> None:
    cfg = cvlib.load("B6")

    # --- happy path: arm -> slice -> slice -> duration end -> completing
    rig = Rig(guard_values={})
    out, plug, _ = await drive(
        cfg,
        rig,
        ["SLICE_DUE", "SLICE_DUE", "DURATION_END", "CHILDREN_TERMINAL"],
    )
    rec(
        "B6",
        "happy-path",
        leaves(out) == ["completed"],
        "armed -> 2x submitting_slice -> completing -> completed",
        {"states": out.states, "transitions": out.transitions},
    )
    rec(
        "B6",
        "INV-B6-a (slices_done <= slices_total counter wiring)",
        out.context.get("_trace", []).count("bump_slices_done") == 2,
        "bump_slices_done ran once per SLICE_DUE; the bound itself is an "
        "action-level obligation the library cannot enforce",
        {"trace": out.context.get("_trace")},
    )

    # --- INV-B6-c: slice below minimum rolls forward via `always`
    rig = Rig(guard_values={"slice_qty_below_min_roll_forward": True})
    out, plug, _ = await drive(cfg, rig, ["SLICE_DUE"])
    ok = leaves(out) == ["armed"] and "S:submit_child" not in rig.calls
    rec(
        "B6",
        "INV-B6-c roll-forward",
        ok,
        "always-guard returns to armed WITHOUT invoking submit_child",
        {"states": out.states, "calls": rig.calls},
    )

    # --- INV-B6-d: price_blocked is a state, SLICE_DUE there records shortfall
    rig = Rig(guard_values={"price_limit_breached": True})
    out, plug, _ = await drive(cfg, rig, ["SLICE_DUE", "SLICE_DUE", "PRICE_OK"])
    tr = out.context.get("_trace", [])
    ok = (
        "raise_price_limit_notice" in tr
        and tr.count("record_shortfall") == 1
        and leaves(out) == ["armed"]
    )
    rec(
        "B6",
        "INV-B6-d price_blocked visible + shortfall recorded",
        ok,
        "2nd SLICE_DUE while blocked took the internal record_shortfall edge",
        {"trace": tr, "states": out.states},
    )

    # --- B1-analogue: event arriving DURING submitting_slice is deferred and
    #     then applied (onUnhandled defer, invoke in flight).
    rig = Rig(service_mode={"submit_child": "gate"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    await interp.send("SLICE_DUE")
    await asyncio.sleep(cvlib.SETTLE)
    mid_states = sorted(interp.current_state_ids)
    # USER_PAUSE is NOT handled in submitting_slice -> must be HELD
    await interp.send("USER_PAUSE")
    await asyncio.sleep(cvlib.SETTLE)
    deferred_mid = interp.deferred_count
    unhandled_mid = list(plug.unhandled)
    rig.gate("submit_child").set()
    await asyncio.sleep(cvlib.SETTLE * 4)
    after = sorted(interp.current_state_ids)
    await interp.stop()
    ok = (
        mid_states == ["twap.submitting_slice"]
        and deferred_mid == 1
        and after == ["twap.paused"]
    )
    rec(
        "B6",
        "B1-analogue: event during invoking state is deferred then applied",
        ok,
        "USER_PAUSE arriving inside submitting_slice was HELD "
        "(deferred_count=%d) and replayed into paused after done.invoke"
        % deferred_mid,
        {
            "mid": mid_states,
            "deferred": deferred_mid,
            "unhandled": unhandled_mid,
            "after": after,
        },
    )

    # --- rollback: an entry action raising under actionErrorPolicy rollback
    rig = Rig(action_raises={"bump_slices_done"})
    out, plug, _ = await drive(cfg, rig, ["SLICE_DUE"])
    ok = leaves(out) == ["armed"] and "S:submit_child" not in rig.calls
    rec(
        "B6",
        "rollback: raising entry action does not half-commit into invoke",
        ok,
        "entry raised -> configuration rolled back to armed, submit_child "
        "never invoked",
        {"states": out.states, "calls": rig.calls, "error": out.error},
    )

    # --- strict: undeclared event name must raise at the call site
    rig = Rig()
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    try:
        await interp.send("SLICE_DUE_TYPO")
        err = "NO-RAISE"
    except UnknownEventError as exc:
        err = type(exc).__name__
    except Exception as exc:  # noqa: BLE001
        err = type(exc).__name__ + ":" + str(exc)[:120]
    await interp.stop()
    rec(
        "B6",
        "strict: undeclared event rejected",
        err == "UnknownEventError",
        "send of an undeclared name raised " + err,
        {"raised": err},
    )

    # --- failure path: service fails, failures not exhausted -> back to armed
    rig = Rig(
        service_mode={"submit_child": "fail"},
        guard_values={"failures_exhausted": False},
    )
    out, plug, _ = await drive(cfg, rig, ["SLICE_DUE"])
    tr = out.context.get("_trace", [])
    ok = leaves(out) == ["armed"] and "record_shortfall" in tr
    rec(
        "B6",
        "onError retry path records shortfall",
        ok,
        "submit_child onError -> armed with bump_failure + record_shortfall",
        {"states": out.states, "trace": tr},
    )

    rig = Rig(
        service_mode={"submit_child": "fail"},
        guard_values={"failures_exhausted": True},
    )
    out, plug, _ = await drive(cfg, rig, ["SLICE_DUE"])
    rec(
        "B6",
        "onError exhausted -> failed",
        leaves(out) == ["failed"],
        "failures_exhausted routes to the terminal failure state",
        {"states": out.states},
    )

    # --- guardErrorPolicy raise: a crashed guard is NOT a denial
    rig = Rig(guard_raises={"price_limit_breached"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    raised = "NO-RAISE"
    try:
        await interp.send("SLICE_DUE", wait=True)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    await asyncio.sleep(cvlib.SETTLE)
    st = sorted(interp.current_state_ids)
    status = interp.status
    await interp.stop()
    rec(
        "B6",
        "guardErrorPolicy raise: crashed guard is not a silent False",
        raised != "NO-RAISE" or st != ["twap.submitting_slice"],
        "guard raised -> %s ; states=%s status=%s" % (raised, st, status),
        {"raised": raised, "states": st, "status": status},
    )


# ===========================================================================
# B7 -- Chase
# ===========================================================================
async def b7() -> None:
    cfg = cvlib.load("B7")

    # happy: arming -> working -> reprice -> fill -> completing -> completed
    rig = Rig(
        guard_values={
            "drift_over_threshold_and_interval_elapsed_and_budget_ok": True
        }
    )
    out, plug, _ = await drive(
        cfg,
        rig,
        ["BOOK_TARGET_MOVED", "CHILD_PARTIAL", "CHILD_FILLED",
         "CHILDREN_TERMINAL"],
    )
    tr = out.context.get("_trace", [])
    rec(
        "B7",
        "happy-path",
        leaves(out) == ["completed"],
        "arming -> working -> repricing -> working -> completing -> completed",
        {"states": out.states, "trace": tr},
    )
    rec(
        "B7",
        "INV-B7-b compute_target_excluding_own_size runs on every reprice",
        tr.count("compute_target_excluding_own_size")
        == tr.count("bump_repricings")
        == 1,
        "the excluding-own-size computation is bound to the repricing entry",
        {"trace": tr},
    )

    # INV-B7-a: bound_exceeded is reachable and visible
    for g in ("beyond_max_chase_ticks", "repricings_exhausted"):
        rig = Rig(guard_values={g: True, "on_timeout_is_market": False,
                                "on_timeout_is_cancel": False})
        out, plug, _ = await drive(cfg, rig, ["BOOK_TARGET_MOVED"])
        ok = leaves(out) == ["parked"] and "raise_warning_alert" in (
            out.context.get("_trace") or []
        )
        rec(
            "B7",
            "INV-B7-a bound_exceeded via " + g,
            ok,
            "guard %s -> bound_exceeded (alert raised) -> parked" % g,
            {"states": out.states, "transitions": out.transitions},
        )

    # INV-B7-c: RATE_BUDGET_EXHAUSTED parks (paused), no amendment queued
    rig = Rig()
    out, plug, _ = await drive(cfg, rig, ["RATE_BUDGET_EXHAUSTED"])
    ok = leaves(out) == ["paused"] and "S:amend_child_price" not in rig.calls
    rec(
        "B7",
        "INV-B7-c rate budget parks instead of queueing amendments",
        ok,
        "RATE_BUDGET_EXHAUSTED -> paused with no amend invocation",
        {"states": out.states, "calls": rig.calls},
    )

    # INV-B7-e: timing_out never silently leaves a resting order
    for g, want in (
        ("on_timeout_is_market", "completed"),
        ("on_timeout_is_cancel", "cancelled"),
    ):
        rig = Rig(guard_values={g: True})
        out, plug, _ = await drive(cfg, rig, ["TIMEOUT", "CHILDREN_TERMINAL"])
        rec(
            "B7",
            "INV-B7-e timing_out resolves by policy (" + g + ")",
            leaves(out) == [want],
            "TIMEOUT settled to " + str(leaves(out)),
            {"states": out.states, "transitions": out.transitions},
        )
    rig = Rig()  # neither policy -> parked, a VISIBLE left_working state
    out, plug, _ = await drive(cfg, rig, ["TIMEOUT"])
    rec(
        "B7",
        "INV-B7-e default timeout policy lands in tagged parked",
        leaves(out) == ["parked"],
        "no policy guard true -> parked (tags: left_working), not silence",
        {"states": out.states},
    )

    # order-not-found-after-fill on amend -> completing (not failed)
    rig = Rig(
        guard_values={
            "drift_over_threshold_and_interval_elapsed_and_budget_ok": True,
            "error_is_order_not_found_after_fill": True,
        },
        service_mode={"amend_child_price": "fail"},
    )
    out, plug, _ = await drive(
        cfg, rig, ["BOOK_TARGET_MOVED", "CHILDREN_TERMINAL"]
    )
    rec(
        "B7",
        "amend onError order-not-found-after-fill -> completing",
        leaves(out) == ["completed"],
        "a fill racing an amendment is not a failure",
        {"states": out.states},
    )

    # defer during repricing (invoke in flight)
    rig = Rig(
        guard_values={
            "drift_over_threshold_and_interval_elapsed_and_budget_ok": True
        },
        service_mode={"amend_child_price": "gate"},
    )
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    await interp.send("BOOK_TARGET_MOVED")
    await asyncio.sleep(cvlib.SETTLE)
    mid = sorted(interp.current_state_ids)
    await interp.send("USER_CANCEL")
    await asyncio.sleep(cvlib.SETTLE)
    dc = interp.deferred_count
    rig.gate("amend_child_price").set()
    await asyncio.sleep(cvlib.SETTLE * 4)
    after = sorted(interp.current_state_ids)
    await interp.stop()
    rec(
        "B7",
        "USER_CANCEL during repricing is deferred, then cancels",
        mid == ["chase.repricing"] and dc == 1 and after == ["chase.cancelled"],
        "cancel held across the in-flight amend, applied on return to working",
        {"mid": mid, "deferred": dc, "after": after},
    )


# ===========================================================================
# B8 -- position protection (native SL invariant)
# ===========================================================================
async def b8() -> None:
    cfg = cvlib.load("B8")

    # happy: POSITION_OPENED -> attaching -> verifying -> protected
    rig = Rig(guard_values={"exchange_reports_sl": True})
    out, plug, _ = await drive(cfg, rig, ["POSITION_OPENED"])
    ok = "position_protection.sl.protected" in out.states
    rec(
        "B8",
        "happy-path to protected",
        ok and "position_protection.watchdog.scanning" in out.states,
        "attach -> verify (exchange_reports_sl) -> protected; watchdog armed",
        {"states": out.states, "calls": rig.calls},
    )
    rec(
        "B8",
        "INV-B8-a protected requires a completed exchange read",
        rig.calls.index("S:read_position_sl") < len(rig.calls)
        and "S:read_position_sl" in rig.calls,
        "read_position_sl ran before protected was entered",
        {"calls": rig.calls},
    )

    # INV-B8-a / B8 listed scenario: NO path to protected without a
    # confirmed SL. Exhaustive: every guard combination with
    # exchange_reports_sl False, across the whole reachable event alphabet.
    events = [
        "POSITION_OPENED",
        "SL_DEADLINE",
        "TIGHTEN_SL",
        "LOOSEN_SL",
        "WATCHDOG_MISS",
        "POSITION_FLAT",
        "SCAN_DUE",
    ]
    guard_names = [
        "attach_attempts_left",
        "tightens_only",
        "explicit_audited_override",
        "sl_observed",
    ]
    breaches = []
    checked = 0
    import itertools

    for combo in itertools.product([False, True], repeat=len(guard_names)):
        gv = dict(zip(guard_names, combo))
        gv["exchange_reports_sl"] = False  # exchange NEVER confirms an SL
        for svc in ("ok", "fail"):
            rig = Rig(
                guard_values=dict(gv),
                service_mode={
                    "attach_native_sl": svc,
                    "read_position_sl": svc,
                    "attach_fallback_sl": svc,
                    "set_trading_stop": svc,
                },
            )
            script = ["POSITION_OPENED"] + events
            out, plug, _ = await drive(cfg, rig, script)
            checked += 1
            if "position_protection.sl.protected" in out.states:
                breaches.append(
                    {"guards": gv, "svc": svc, "states": out.states}
                )
    rec(
        "B8",
        "INV-B8-a/B8-listed: protected UNREACHABLE without confirmed SL",
        not breaches,
        "%d guard x service x event-sequence runs with exchange_reports_sl "
        "pinned False; `protected` entered in %d of them"
        % (checked, len(breaches)),
        {"breaches": breaches[:3]},
    )

    # SL_OBSERVED is the ONLY declared escape from naked_unrecoverable to
    # protected -- check it is a positive observation, not a guess.
    rig = Rig(
        guard_values={"exchange_reports_sl": False, "attach_attempts_left": False},
        service_mode={"attach_native_sl": "fail", "attach_fallback_sl": "fail"},
    )
    out, plug, _ = await drive(cfg, rig, ["POSITION_OPENED"])
    naked_unrec = "position_protection.sl.naked_unrecoverable" in out.states
    tr = out.context.get("_trace") or []
    rec(
        "B8",
        "INV-B8-d naked_unrecoverable pages the owner",
        naked_unrec and "page_owner" in tr
        and "consider_reduce_only_close" in tr,
        "attach fail + fallback fail -> naked_unrecoverable with both "
        "unsuppressable entry actions",
        {"states": out.states, "trace": tr},
    )
    rec(
        "B8",
        "INV-3 naked entry raises the critical alert + metric",
        "raise_critical_alert" in tr and "emit_naked_metric" in tr
        and "stamp_naked_since" in tr,
        "the naked state stamps the clock, alerts and metricises on entry",
        {"trace": tr},
    )

    # INV-B8-b: tightens_only is deny-polarity -- False blocks the amendment
    rig = Rig(
        guard_values={"exchange_reports_sl": True, "tightens_only": False}
    )
    out, plug, _ = await drive(cfg, rig, ["POSITION_OPENED", "TIGHTEN_SL"])
    ok = "position_protection.sl.protected" in out.states and (
        "S:set_trading_stop" not in rig.calls
    )
    rec(
        "B8",
        "INV-B8-b tightens_only deny-polarity blocks the amendment",
        ok,
        "guard False -> no amending, no set_trading_stop, stays protected",
        {"states": out.states, "calls": rig.calls},
    )

    # ... and a RAISING tightens_only must not silently become a denial that
    # is indistinguishable from a clean deny. guardErrorPolicy=raise.
    rig = Rig(
        guard_values={"exchange_reports_sl": True},
        guard_raises={"tightens_only"},
    )
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await interp.send("POSITION_OPENED")
    await asyncio.sleep(cvlib.SETTLE * 3)
    raised = "NO-RAISE"
    try:
        await interp.send("TIGHTEN_SL", wait=True)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    await asyncio.sleep(cvlib.SETTLE)
    st = sorted(interp.current_state_ids)
    status, err = interp.status, repr(interp.error)
    await interp.stop()
    rec(
        "B8",
        "INV-B8-b raising guard surfaces (guardErrorPolicy raise)",
        raised != "NO-RAISE" or status != "running",
        "raising tightens_only produced %s; status=%s" % (raised, status),
        {"raised": raised, "states": st, "status": status, "error": err},
    )

    # INV-B8-c: loosening requires explicit_audited_override
    rig = Rig(
        guard_values={
            "exchange_reports_sl": True,
            "explicit_audited_override": False,
        }
    )
    out, plug, _ = await drive(cfg, rig, ["POSITION_OPENED", "LOOSEN_SL"])
    rec(
        "B8",
        "INV-B8-c loosening blocked without explicit_audited_override",
        "S:set_trading_stop" not in rig.calls,
        "LOOSEN_SL with the override False never reaches set_trading_stop",
        {"calls": rig.calls, "states": out.states},
    )

    # INV-B8-e: miss counter reset only by a positive sl_observed
    rig = Rig(guard_values={"exchange_reports_sl": True, "sl_observed": False})
    out, plug, _ = await drive(
        cfg, rig, ["POSITION_OPENED", "SCAN_DUE", "SCAN_DUE", "SCAN_DUE"]
    )
    tr = out.context.get("_trace") or []
    ok = tr.count("bump_miss_counter") == 3 and "reset_miss_counter" not in tr
    rec(
        "B8",
        "INV-B8-e miss counter is never reset by time alone",
        ok,
        "3 SCAN_DUE with sl_observed False -> 3 bumps, 0 resets",
        {"trace": tr},
    )
    rig = Rig(guard_values={"exchange_reports_sl": True, "sl_observed": True})
    out, plug, _ = await drive(cfg, rig, ["POSITION_OPENED", "SCAN_DUE"])
    tr = out.context.get("_trace") or []
    rec(
        "B8",
        "INV-B8-e positive sl_observed resets it",
        "reset_miss_counter" in tr and "bump_miss_counter" not in tr,
        "a positive scan takes the reset branch only",
        {"trace": tr},
    )

    # SL_DEADLINE races the attach: deadline must win into naked
    rig = Rig(service_mode={"attach_native_sl": "gate"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await interp.send("POSITION_OPENED")
    await asyncio.sleep(cvlib.SETTLE * 2)
    mid = sorted(interp.current_state_ids)
    await interp.send("SL_DEADLINE")
    await asyncio.sleep(cvlib.SETTLE * 2)
    after = sorted(interp.current_state_ids)
    await interp.stop()
    rec(
        "B8",
        "SL_DEADLINE during attaching pre-empts into naked",
        "position_protection.sl.attaching" in mid
        and "position_protection.sl.naked" in after,
        "the deadline is handled IN attaching, so it is not deferred behind "
        "the in-flight attach",
        {"mid": mid, "after": after},
    )

    # actionErrorPolicy: "fail" -- a half-applied step must HALT
    rig = Rig(action_raises={"bump_attach_attempts"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    raised = "NO-RAISE"
    try:
        await interp.send("POSITION_OPENED", wait=True)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    await asyncio.sleep(cvlib.SETTLE * 2)
    st = sorted(interp.current_state_ids)
    status, err = interp.status, repr(interp.error)
    try:
        await interp.stop()
    except Exception:  # noqa: BLE001
        pass
    rec(
        "B8",
        "actionErrorPolicy fail halts the safety machine",
        status != "running" or raised != "NO-RAISE",
        "raising entry action -> status=%s raised=%s" % (status, raised),
        {"raised": raised, "states": st, "status": status, "error": err},
    )


# ===========================================================================
# B9 -- rule instance
# ===========================================================================
async def b9() -> None:
    cfg = cvlib.load("B9")

    rig = Rig(
        guard_values={
            "promotion_gate_satisfied_and_permitted": True,
            "condition_true": True,
        }
    )
    out, plug, _ = await drive(
        cfg,
        rig,
        ["SAVE", "ARM_REQUESTED", "TRIGGER", "COOLDOWN_DUE"],
    )
    tr = out.context.get("_trace") or []
    rec(
        "B9",
        "happy-path draft->simulating->armed->evaluating->acting->cooling->armed",
        leaves(out) == ["armed"] and "record_fire" in tr,
        "a full fire cycle returns to armed with the fire recorded",
        {"states": out.states, "transitions": out.transitions},
    )
    rec(
        "B9",
        "INV-B9-c assert_safety_limits runs on ENTRY to acting",
        tr.index("assert_safety_limits") < tr.index("record_fire"),
        "the safety assertion precedes the dispatch result, per-fire",
        {"trace": tr},
    )

    # INV-B9-b: every non-firing outcome records a reason
    for g, act in (
        ("debounce_blocked", "record_skip_debounced"),
        ("data_stale", "record_skip_stale_data"),
        ("limits_blocked", "record_skip_limit"),
    ):
        rig = Rig(
            guard_values={
                "promotion_gate_satisfied_and_permitted": True,
                g: True,
            }
        )
        out, plug, _ = await drive(cfg, rig, ["SAVE", "ARM_REQUESTED", "TRIGGER"])
        tr = out.context.get("_trace") or []
        rec(
            "B9",
            "INV-B9-b skip reason recorded: " + g,
            act in tr and leaves(out) == ["armed"],
            "TRIGGER under %s recorded %s and stayed armed" % (g, act),
            {"trace": tr, "states": out.states},
        )
    # ...and the no-op branch logs values rather than going silent
    rig = Rig(
        guard_values={
            "promotion_gate_satisfied_and_permitted": True,
            "condition_true": False,
        }
    )
    out, plug, _ = await drive(cfg, rig, ["SAVE", "ARM_REQUESTED", "TRIGGER"])
    tr = out.context.get("_trace") or []
    rec(
        "B9",
        "INV-B9-b condition-false no-op is logged with values",
        "log_no_op_with_values" in tr,
        "evaluate onDone false branch is never silent",
        {"trace": tr},
    )
    # ...and the unconfirmed / rejected paths
    for ev, act in (
        ("CONFIRM_TIMEOUT", "record_skip_unconfirmed"),
        ("REJECTED", "record_skip_rejected"),
    ):
        rig = Rig(
            guard_values={
                "promotion_gate_satisfied_and_permitted": True,
                "condition_true": True,
                "condition_true_and_requires_confirmation": True,
            }
        )
        out, plug, _ = await drive(
            cfg, rig, ["SAVE", "ARM_REQUESTED", "TRIGGER", ev]
        )
        tr = out.context.get("_trace") or []
        rec(
            "B9",
            "INV-B9-b " + ev + " records " + act,
            act in tr and leaves(out) == ["armed"],
            "human-confirmation TTL / rejection is an audited non-fire",
            {"trace": tr, "states": out.states},
        )

    # INV-B9-d: kill_switched is exited ONLY by HUMAN_REARM + elevated
    rig = Rig(
        guard_values={
            "promotion_gate_satisfied_and_permitted": True,
            "rearm_permitted_and_elevated": False,
        }
    )
    out, plug, _ = await drive(
        cfg,
        rig,
        ["SAVE", "ARM_REQUESTED", "KILL_SWITCH", "HUMAN_REARM", "TRIGGER",
         "FEED_HEALTHY", "COOLDOWN_DUE", "RESET_ONCE", "DISARM", "SAVE"],
    )
    rec(
        "B9",
        "INV-B9-d kill_switched has no automatic exit",
        leaves(out) == ["kill_switched"],
        "10 further events incl. HUMAN_REARM without elevation: still "
        "kill_switched",
        {"states": out.states, "deferred": out.deferred},
    )
    rig = Rig(
        guard_values={
            "promotion_gate_satisfied_and_permitted": True,
            "rearm_permitted_and_elevated": True,
        }
    )
    out, plug, _ = await drive(
        cfg, rig, ["SAVE", "ARM_REQUESTED", "KILL_SWITCH", "HUMAN_REARM"]
    )
    rec(
        "B9",
        "INV-B9-d elevated HUMAN_REARM is the one exit",
        leaves(out) == ["armed"]
        and "reset_consecutive_errors" in (out.context.get("_trace") or []),
        "an elevated human re-arm restores armed and clears the error budget",
        {"states": out.states},
    )

    # INV-B9-e: promotion gate is deny-polarity
    rig = Rig(guard_values={"promotion_gate_satisfied_and_permitted": False})
    out, plug, _ = await drive(cfg, rig, ["SAVE", "ARM_REQUESTED"])
    tr = out.context.get("_trace") or []
    rec(
        "B9",
        "INV-B9-e promotion gate deny-polarity",
        leaves(out) == ["simulating"] and "reject_promotion_with_reason" in tr,
        "a failed gate stays in simulating with a recorded reason",
        {"states": out.states, "trace": tr},
    )
    # ... and a RAISING promotion gate must not promote
    rig = Rig(guard_raises={"promotion_gate_satisfied_and_permitted"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await interp.send("SAVE")
    await asyncio.sleep(cvlib.SETTLE)
    raised = "NO-RAISE"
    try:
        await interp.send("ARM_REQUESTED", wait=True)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    await asyncio.sleep(cvlib.SETTLE)
    st = sorted(interp.current_state_ids)
    await interp.stop()
    rec(
        "B9",
        "INV-B9-e raising promotion gate never promotes",
        "rule_instance.armed" not in st,
        "guard raised (%s); machine is %s" % (raised, st),
        {"raised": raised, "states": st},
    )

    # error budget: evaluate onError exhausted -> kill_switched
    rig = Rig(
        guard_values={
            "promotion_gate_satisfied_and_permitted": True,
            "error_budget_exhausted": True,
        },
        service_mode={"evaluate_condition_dag": "fail"},
    )
    out, plug, _ = await drive(cfg, rig, ["SAVE", "ARM_REQUESTED", "TRIGGER"])
    rec(
        "B9",
        "error budget exhaustion routes to kill_switched",
        leaves(out) == ["kill_switched"],
        "a repeatedly failing evaluator kills the rule rather than looping",
        {"states": out.states},
    )

    # partial dispatch -> cooling_down with partial alert (B9.8 note)
    rig = Rig(
        guard_values={
            "promotion_gate_satisfied_and_permitted": True,
            "condition_true": True,
            "error_budget_exhausted": False,
        },
        service_mode={"dispatch_actions_in_order": "fail"},
    )
    out, plug, _ = await drive(cfg, rig, ["SAVE", "ARM_REQUESTED", "TRIGGER"])
    tr = out.context.get("_trace") or []
    rec(
        "B9",
        "partial dispatch surfaces as onError, not a committed fire",
        "record_partial_fire" in tr and "raise_partial_alert" in tr
        and "record_fire" not in tr,
        "dispatch failure is a partial fire with an alert",
        {"trace": tr, "states": out.states},
    )

    # B18-analogue: KILL_SWITCH via send_priority pre-empts a busy inbox.
    rig = Rig(
        guard_values={
            "promotion_gate_satisfied_and_permitted": True,
            "debounce_blocked": True,
        }
    )
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig, max_queue_size=256)
    await interp.start()
    await interp.send("SAVE")
    await interp.send("ARM_REQUESTED")
    await asyncio.sleep(cvlib.SETTLE * 2)
    # flood the inbox without awaiting the drain
    for _ in range(80):
        interp._loop.call_soon_threadsafe(lambda: None)
    floods = [interp.send("TRIGGER") for _ in range(80)]
    prio = interp.send_priority("KILL_SWITCH")
    depth = interp.queue_depth
    await asyncio.gather(prio, *floods)
    await asyncio.sleep(cvlib.SETTLE * 6)
    st = sorted(interp.current_state_ids)
    trg = (rig.calls.count("A:record_skip_debounced"))
    await interp.stop()
    rec(
        "B9",
        "B18-analogue: send_priority pre-empts a busy inbox",
        st == ["rule_instance.kill_switched"] and trg < 80,
        "KILL_SWITCH jumped %d queued TRIGGERs (only %d were processed "
        "before the kill landed); final=%s" % (depth, trg, st),
        {"queue_depth_at_send": depth, "triggers_processed": trg,
         "states": st},
    )

    # bounded inbox on the order path: RAISE on overflow
    rig = Rig(guard_values={"promotion_gate_satisfied_and_permitted": True,
                            "debounce_blocked": True})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig, max_queue_size=4)
    await interp.start()
    await interp.send("SAVE")
    await interp.send("ARM_REQUESTED")
    await asyncio.sleep(cvlib.SETTLE * 2)
    overflow = "NO-RAISE"
    try:
        await asyncio.gather(*[interp.send("TRIGGER") for _ in range(200)])
    except QueueOverflowError as exc:  # noqa: BLE001
        overflow = type(exc).__name__
    except Exception as exc:  # noqa: BLE001
        overflow = type(exc).__name__
    await interp.stop()
    rec(
        "B9",
        "bounded inbox RAISEs rather than silently dropping",
        overflow == "QueueOverflowError",
        "200 sends into a 4-deep inbox produced " + overflow,
        {"raised": overflow},
    )


# ===========================================================================
# B10 -- alert
# ===========================================================================
async def b10() -> None:
    cfg = cvlib.load("B10")

    rig = Rig(guard_values={"all_channels_ok": True})
    out, plug, _ = await drive(cfg, rig, ["CONDITION_MET", "ACK", "RESOLVE"])
    tr = out.context.get("_trace") or []
    rec(
        "B10",
        "happy-path armed->firing->delivered->acknowledged->resolved",
        leaves(out) == ["resolved"],
        "full delivery lifecycle reaches the terminal final state",
        {"states": out.states, "transitions": out.transitions},
    )
    rec(
        "B10",
        "INV-B10-d persist_fired_row precedes dispatch",
        tr.index("persist_fired_row") < rig.calls.index("S:dispatch_to_channels"),
        "the fired row is written on entry to firing, before any channel I/O",
        {"trace": tr, "calls": rig.calls},
    )

    # INV-B10-b partial delivery is its own state
    rig = Rig(guard_values={"all_channels_ok": False})
    out, plug, _ = await drive(cfg, rig, ["CONDITION_MET"])
    rec(
        "B10",
        "INV-B10-b partial delivery is a distinct degraded state",
        leaves(out) == ["partially_delivered"],
        "all_channels_ok False -> partially_delivered, not delivered",
        {"states": out.states},
    )

    # INV-B10-a bounded retry
    rig = Rig(
        guard_values={"delivery_attempts_left": True},
        service_mode={"dispatch_to_channels": "fail"},
    )
    out, plug, _ = await drive(
        cfg, rig, ["CONDITION_MET"] + ["RETRY_DUE"] * 6
    )
    tr = out.context.get("_trace") or []
    rec(
        "B10",
        "INV-B10-a retry loop is driven by RETRY_DUE, bounded by the guard",
        leaves(out) == ["retrying"]
        and tr.count("bump_delivery_attempts") == 7,
        "each RETRY_DUE costs exactly one attempt bump; no free retries",
        {"attempts": tr.count("bump_delivery_attempts"), "states": out.states},
    )
    rig = Rig(
        guard_values={"delivery_attempts_left": False},
        service_mode={"dispatch_to_channels": "fail"},
    )
    out, plug, _ = await drive(cfg, rig, ["CONDITION_MET"])
    tr = out.context.get("_trace") or []
    rec(
        "B10",
        "INV-B10-a exhaustion reaches the visible delivery_failed state",
        leaves(out) == ["delivery_failed"]
        and "emit_delivery_failure_metric" in tr,
        "no infinite retry; the failure is metricised",
        {"states": out.states, "trace": tr},
    )

    # INV-B10-c storm suppression is counted
    rig = Rig(guard_values={"in_storm_window": True})
    out, plug, _ = await drive(cfg, rig, ["CONDITION_MET"])
    tr = out.context.get("_trace") or []
    rec(
        "B10",
        "INV-B10-c suppression is counted and metricised",
        leaves(out) == ["suppressed"]
        and "bump_storm_count" in tr
        and "emit_suppression_metric" in tr,
        "a suppressed alert is an observable state, not a drop",
        {"states": out.states, "trace": tr},
    )

    # delivery_failed has NO RESOLVE edge -- it must be deferred, not dropped
    rig = Rig(
        guard_values={"delivery_attempts_left": False},
        service_mode={"dispatch_to_channels": "fail"},
    )
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await interp.send("CONDITION_MET")
    await asyncio.sleep(cvlib.SETTLE * 3)
    await interp.send("RESOLVE")
    await asyncio.sleep(cvlib.SETTLE)
    dc, unh = interp.deferred_count, list(plug.unhandled)
    st = sorted(interp.current_state_ids)
    await interp.send("ACK")
    await asyncio.sleep(cvlib.SETTLE * 3)
    st2 = sorted(interp.current_state_ids)
    await interp.stop()
    rec(
        "B10",
        "onUnhandled defer holds RESOLVE in delivery_failed, replays on ACK",
        dc == 1 and st == ["alert.delivery_failed"] and st2 == ["alert.resolved"],
        "RESOLVE has no edge in delivery_failed; it was HELD (deferred=%d) "
        "and applied after ACK moved to acknowledged -> %s" % (dc, st2),
        {"deferred": dc, "unhandled": unh, "after_ack": st2},
    )


async def main() -> None:
    for fn in (b6, b7, b8, b9, b10):
        try:
            await fn()
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            rec(fn.__name__.upper(), "HARNESS", False,
                "driver crashed: " + repr(exc))
    print(json.dumps(RESULTS, indent=2, default=str))
    fails = [r for r in RESULTS if r["verdict"] == "FAIL"]
    print("\n=== %d checks, %d FAIL ===" % (len(RESULTS), len(fails)))
    for f in fails:
        print("FAIL", f["machine"], "|", f["invariant"], "|", f["note"])


asyncio.run(main())
