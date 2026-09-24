# -*- coding: utf-8 -*-
"""Two headline confirmations.

X1 (OUR-CONTRACT, B19): the inline `"*": {"actions": ["defer"]}` scaffolding
    that section 1.3b calls "dead but harmless" is NOT dead. It is a real
    transition and it SHADOWS `onUnhandled: "defer"`: the event is consumed,
    the runtime buffer never sees it, `deferred_count` stays 0, and the event
    is LOST. Compare `fetching` (has the inline `*`) with `backing_off`
    (does not).

X2 (LIBRARY+CONTRACT, B20/B17): under `actionErrorPolicy: "fail"` the
    configuration is left on the SOURCE state while `status` goes `error`.
    For a safety-invariant machine that means the machine reports the
    `trading_allowed` tag after a lockout that already ran `halt_new_orders`.
"""
import asyncio, json
from cdrv import mk, step, cfg_of
from charness import Stub, TraceP, build, SETTLE
from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

R = {}
G_CLEAN = {"failures_exhausted": False,
           "divergences_found_and_auto_remediate": False,
           "unresolved_divergences": False}


async def _slow_fetch(i, c, e):
    await asyncio.sleep(0.5)
    return {"orders": []}


async def x1_star_shadows_defer():
    """`fetching` has an inline `"*"` handler; `backing_off` does not."""
    cfg = cfg_of("B19")
    st = Stub(cfg, guard_vals=G_CLEAN)
    logic = st.logic()
    logic.services["fetch_exchange_state"] = _slow_fetch
    m = create_machine(cfg, logic=logic, strict_targets=True)
    interp = Interpreter(m, clock=SimulatedClock())
    tp = TraceP()
    interp.use(tp)
    await interp.start()
    await asyncio.sleep(SETTLE)
    out = {}

    # --- A: inside `fetching` (inline "*" present) ---------------------
    await interp.send("SWEEP_DUE", wait=False)
    await asyncio.sleep(0.1)
    assert "reconciliation.fetching" in interp.current_state_ids
    r = await interp.send("UNKNOWN_ORDER", wait=True)
    out["fetching"] = {
        "state": "reconciliation.fetching",
        "receipt": {"changed": r.changed, "deferred": getattr(r, "deferred", None)},
        "deferred_count": interp.deferred_count,
        "unhandled_hook": list(tp.unhandled),
        "trace": list(st.trace),
        "transitions": list(tp.transitions),
    }
    await asyncio.sleep(0.8)   # let the sweep finish
    out["fetching"]["after_sweep_ids"] = sorted(interp.current_state_ids)
    out["fetching"]["after_sweep_trace"] = list(st.trace)
    out["fetching"]["unknown_order_replayed"] = (
        "set_trigger_unknown" in st.trace)
    await interp.stop()

    # --- B: inside `backing_off` (no inline "*") -----------------------
    st2 = Stub(cfg, guard_vals=G_CLEAN,
               svc={"fetch_exchange_state": RuntimeError("503")})
    m2 = build(cfg, st2)
    i2 = Interpreter(m2, clock=SimulatedClock())
    tp2 = TraceP()
    i2.use(tp2)
    await i2.start()
    await asyncio.sleep(SETTLE)
    await i2.send("SWEEP_DUE", wait=False)
    await asyncio.sleep(0.2)
    out["backing_off_state"] = sorted(i2.current_state_ids)
    r2 = await i2.send("UNKNOWN_ORDER", wait=True)
    out["backing_off"] = {
        "receipt": {"changed": r2.changed, "deferred": getattr(r2, "deferred", None)},
        "deferred_count": i2.deferred_count,
        "unhandled_hook": list(tp2.unhandled),
        "trace": list(st2.trace),
    }
    # release it: RETRY_DUE -> fetching -> the deferred UNKNOWN_ORDER replays
    await i2.send("RETRY_DUE", wait=False)
    await asyncio.sleep(0.4)
    out["backing_off"]["after_retry_ids"] = sorted(i2.current_state_ids)
    out["backing_off"]["after_retry_trace"] = list(st2.trace)
    out["backing_off"]["unknown_order_replayed"] = (
        "set_trigger_unknown" in st2.trace)
    await i2.stop()
    return out


async def x2_fail_leaves_source_state():
    out = {}
    # B20: broadcast_lockout is LAST in the `locked` entry list, so every
    # earlier action (incl. halt_new_orders) already ran.
    for b, ev, bad, src, dst in [
            ("B20", "MANUAL_LOCK", "broadcast_lockout",
             "risk_lockout.clear", "risk_lockout.locked"),
            ("B17", "ENABLE_REQUESTED", "enable_live_visual_language",
             "live_gate.eligible", "live_gate.enabled")]:
        gv = {"all_evidence_present": True, "owner_and_elevated": True,
              "owner_and_elevated_and_evidence_still_valid": True,
              "breaches_daily_loss_cap": False, "within_warning_band": False,
              "outside_warning_band": False, "until_mode_is_time_based": True,
              "owner_and_elevated_and_override_permitted": True}
        interp, st, tp, clock, m = await mk(b, {"guard_vals": gv,
                                                "raising": {bad}})
        if b == "B17":
            await step(interp, clock, "EVIDENCE_RECORDED")
        r = await step(interp, clock, ev)
        ids = sorted(interp.current_state_ids)
        tags = set()
        for node in interp.current_state_nodes if hasattr(
                interp, "current_state_nodes") else []:
            tags |= set(getattr(node, "tags", []) or [])
        rec = {"raising_action": bad, "intended_target": dst,
               "ids_after": ids, "expected_source": src,
               "left_on_source": ids == [src],
               "status": interp.status,
               "tags": sorted(tags),
               "receipt_changed": r.changed,
               "receipt_error": type(r.error).__name__ if r.error else None,
               "side_effects_that_ran": list(st.trace)}
        try:
            snap = interp.get_persisted_snapshot()
            rec["snapshot_refused"] = False
            rec["snapshot_status"] = snap.get("status")
            rec["snapshot_state_ids"] = snap.get("state_ids")
        except Exception as e:  # noqa: BLE001
            rec["snapshot_refused"] = "%s: %s" % (type(e).__name__, str(e)[:120])
        # can it be driven again? (safety machine must still accept a kill)
        try:
            r2 = await step(interp, clock,
                            "OVERRIDE_REQUESTED" if b == "B20"
                            else "EMERGENCY_DISABLE")
            rec["subsequent_event"] = {"changed": r2.changed,
                                       "ids": sorted(interp.current_state_ids),
                                       "status": interp.status}
        except Exception as e:  # noqa: BLE001
            rec["subsequent_event"] = "%s: %s" % (type(e).__name__, str(e)[:140])
        out[b] = rec
        try:
            await interp.stop()
        except Exception:
            pass
    return out


async def main():
    R["x1_star_shadows_defer"] = await x1_star_shadows_defer()
    R["x2_fail_leaves_source_state"] = await x2_fail_leaves_source_state()


asyncio.run(main())
json.dump(R, open("results/c6_headline.json", "w", encoding="utf-8"),
          indent=2, default=str)
print(json.dumps(R, indent=2, default=str))
