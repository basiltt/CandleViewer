# -*- coding: utf-8 -*-
"""s1: CV-221-01 retest @6db65d8 -- rollback + invoke.onDone re-arm, both kinds.

B18 (page_owner raises on engaged_incomplete entry) and B19 (store_divergences /
persist_report), plus the minimal repro. Watchdog-bounded observation windows.
"""
import asyncio, json, time
from d import mk, CTL
from h import ids, SETTLE
from xstate_statemachine import Interpreter, OverflowPolicy, create_machine
from xstate_statemachine.clock import SimulatedClock
from h import Stub, TraceP

R = {}
WIN = 1.0

GB18 = {"cancel_working_requested": True, "flatten_requested": True,
        "all_accounts_flat": False, "owner_and_elevated": True,
        "owner_and_elevated_and_acknowledged_residual": True}


async def watch(interp, st, secs=WIN):
    t0 = time.monotonic(); trail = []
    while time.monotonic() - t0 < secs:
        await asyncio.sleep(0.1)
        trail.append((round(time.monotonic() - t0, 2), len(st.svc_calls)))
    return trail


async def cell(name, b, kind, gv, raising, ev, max_iter=None, svc=None):
    from h import cfg_of, build
    import copy
    cfg = cfg_of(b)
    if max_iter is not None:
        cfg["maxIterations"] = max_iter
    st = Stub(cfg, kind=kind, guard_vals=gv, raising=raising, svc=svc or {})
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    r = None; err = None
    try:
        r = await asyncio.wait_for(interp.send(ev, wait=True), 5)
    except Exception as e:                                       # noqa: BLE001
        err = f"{type(e).__name__}: {str(e)[:120]}"
    trail = await watch(interp, st)
    row = {"kind": kind, "max_iterations": max_iter,
           "svc_calls": len(st.svc_calls), "actions": len(st.trace),
           "trail": trail, "ids": ids(interp), "status": interp.status,
           "send_err": err,
           "receipt": None if r is None else
           {"changed": r.changed,
            "error": type(r.error).__name__ if r.error else None},
           "last_error": type(getattr(interp, "last_error", None)).__name__,
           "declared_max": getattr(m, "max_iterations", None)}
    try:
        await asyncio.wait_for(interp.stop(), 5)
    except Exception as e:                                       # noqa: BLE001
        row["stop_err"] = f"{type(e).__name__}"
    R[name] = row
    print(name, row["kind"], "svc=", row["svc_calls"], row["ids"],
          row["status"], row["last_error"], flush=True)


async def main():
    for kind in ("async", "sync"):
        await cell(f"b18_r6class_{kind}", "B18", kind, GB18, ["page_owner"], "ENGAGE")
        await cell(f"b18_control_{kind}", "B18", kind,
                   dict(GB18, all_accounts_flat=True), [], "ENGAGE")
        for mi in (2, 5, 100):
            await cell(f"b18_mi{mi}_{kind}", "B18", kind, GB18, ["page_owner"],
                       "ENGAGE", max_iter=mi)
        GV19 = {"auto_remediate_allowed": True, "should_backoff": True,
                "too_many_failures": False}
        await cell(f"b19_store_{kind}", "B19", kind, GV19,
                   ["store_divergences"], "SWEEP_DUE")
        await cell(f"b19_persist_{kind}", "B19", kind, GV19,
                   ["persist_report"], "SWEEP_DUE")
        await cell(f"b19_control_{kind}", "B19", kind, GV19, [], "SWEEP_DUE")

asyncio.run(main())
json.dump(R, open("results/s1_livelock.json", "w", encoding="utf-8"),
          indent=2, default=str)
