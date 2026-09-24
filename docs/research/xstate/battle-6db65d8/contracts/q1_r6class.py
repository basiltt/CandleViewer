# -*- coding: utf-8 -*-
"""R6-03 (rollback + invoke.onDone) and R6-01 (always-into-invoked-child)
shapes as they actually occur in B18/B19, on 221ce7c. Watchdog-bounded."""
import asyncio, json, time
from cdrv import mk, cfg_of
from charness import SETTLE, Stub, build, TraceP, ids
from xstate_statemachine import Interpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock

R = {}
CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)


async def drive(b, seq, stub_kw=None, budget=8.0, **ikw):
    """Send each event with wait=True under a watchdog; record svc-call counts."""
    interp, st, tp, clock, m = await mk(b, stub_kw, **ikw)
    out = {"events": [], "timeout": False}
    t0 = time.perf_counter()
    for e in seq:
        n0 = len(st.svc_calls)
        try:
            r = await asyncio.wait_for(interp.send(e, wait=True), budget)
            rec = {"ev": e, "changed": r.changed,
                   "error": type(r.error).__name__ if r.error else None}
        except asyncio.TimeoutError:
            out["timeout"] = True
            rec = {"ev": e, "TIMEOUT": True}
        try:
            await asyncio.wait_for(asyncio.sleep(SETTLE * 3), 3)
        except asyncio.TimeoutError:
            pass
        rec["svc_calls_delta"] = len(st.svc_calls) - n0
        rec["ids"] = ids(interp)
        rec["status"] = interp.status
        rec["last_error"] = type(getattr(interp, "last_error", None)).__name__ \
            if getattr(interp, "last_error", None) else None
        out["events"].append(rec)
        if out["timeout"]:
            break
    out["wall_s"] = round(time.perf_counter() - t0, 3)
    out["svc_calls_total"] = len(st.svc_calls)
    out["acts_total"] = len(st.trace)
    out["ids"] = ids(interp)
    out["status"] = interp.status
    try:
        await asyncio.wait_for(interp.stop(), 5)
    except Exception as ex:
        out["stop_error"] = type(ex).__name__
    return out


async def main():
    # --- R6-03 class in B18: flattening.onDone -> engaged_incomplete whose
    #     entry action raises under actionErrorPolicy "rollback".
    R["b18_rollback_ondone_page_owner"] = await drive(
        "B18", ["ENGAGE"],
        stub_kw={"guard_vals": {"cancel_working_requested": True,
                                "flatten_requested": True,
                                "all_accounts_flat": False},
                 "raising": ["page_owner"]}, **CTL)
    # same, but the *guarded-success* onDone target (engaged) has no entry;
    # raise in the onDone transition action instead (B19 diffing).
    R["b19_rollback_ondone_store_divergences"] = await drive(
        "B19", ["SWEEP_DUE"],
        stub_kw={"guard_vals": {"divergences_found_and_auto_remediate": True},
                 "raising": ["store_divergences"]}, **CTL)
    # --- R6-01 class: always into a sibling that invokes, with the always
    #     target's own chain re-entered. B19 reporting entry raises ->
    #     rollback into remediating (invoked) -> re-arm.
    R["b19_rollback_reporting_entry"] = await drive(
        "B19", ["SWEEP_DUE"],
        stub_kw={"guard_vals": {"divergences_found_and_auto_remediate": True,
                                "unresolved_divergences": True},
                 "raising": ["persist_report"]}, **CTL)
    # B18 engaging entry raises -> rollback at the always source
    R["b18_rollback_engaging_entry"] = await drive(
        "B18", ["ENGAGE"],
        stub_kw={"guard_vals": {"cancel_working_requested": True},
                 "raising": ["block_new_orders_immediately"]}, **CTL)
    # control: the same machines with no raise must terminate cleanly
    R["b18_control"] = await drive(
        "B18", ["ENGAGE"],
        stub_kw={"guard_vals": {"cancel_working_requested": True,
                                "flatten_requested": True,
                                "all_accounts_flat": True}}, **CTL)
    R["b19_control"] = await drive(
        "B19", ["SWEEP_DUE"],
        stub_kw={"guard_vals": {"divergences_found_and_auto_remediate": True}},
        **CTL)

asyncio.run(main())
json.dump(R, open("results/q1_r6class.json", "w", encoding="utf-8"),
          indent=2, default=str)
for k, v in R.items():
    print(k, "| timeout", v["timeout"], "| wall", v["wall_s"],
          "| svc", v["svc_calls_total"], "| acts", v["acts_total"],
          "|", v["status"], v["ids"])
