# -*- coding: utf-8 -*-
"""s2: does the default budget plateau, and what is observable/recoverable after?"""
import asyncio, json, time, logging
logging.disable(logging.CRITICAL)
from d import CTL
from h import Stub, TraceP, build, cfg_of, ids, SETTLE
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock

R = {}
GB18 = {"cancel_working_requested": True, "flatten_requested": True,
        "all_accounts_flat": False, "owner_and_elevated": True,
        "owner_and_elevated_and_acknowledged_residual": True}


async def run(kind, mi=None, secs=4.0):
    cfg = cfg_of("B18")
    if mi is not None:
        cfg["maxIterations"] = mi
    st = Stub(cfg, kind=kind, guard_vals=GB18, raising=["page_owner"])
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    await asyncio.wait_for(interp.send("ENGAGE", wait=True), 5)
    t0 = time.monotonic(); trail = []
    while time.monotonic() - t0 < secs:
        await asyncio.sleep(0.5)
        trail.append((round(time.monotonic() - t0, 1), len(st.svc_calls)))
    row = {"kind": kind, "mi": mi, "trail": trail, "svc": len(st.svc_calls),
           "ids": ids(interp), "status": interp.status,
           "last_error": type(getattr(interp, "last_error", None)).__name__,
           "dropped": tp.dropped[:5], "unhandled": tp.unhandled[:5]}
    # post-trip: is the machine still usable? RETRY_FLATTEN is declared only in
    # engaged_incomplete; RELEASE only in engaged. Under onUnhandled:error the
    # control path kills on an undeclared event -- record exactly what happens.
    n0 = len(st.svc_calls)
    try:
        r = await asyncio.wait_for(interp.send("RELEASE", wait=True), 5)
        row["post_release"] = {"changed": r.changed,
                               "error": type(r.error).__name__ if r.error else None,
                               "denied": getattr(r, "denied", "ABSENT")}
    except Exception as e:                                       # noqa: BLE001
        row["post_release"] = f"{type(e).__name__}: {str(e)[:120]}"
    await asyncio.sleep(0.5)
    row["post_status"] = interp.status
    row["post_ids"] = ids(interp)
    row["svc_after_external"] = len(st.svc_calls) - n0
    try:
        blob = interp.get_persisted_snapshot()
        row["snapshot"] = {"ok": True, "status": blob.get("status")}
    except Exception as e:                                       # noqa: BLE001
        row["snapshot"] = f"{type(e).__name__}: {str(e)[:120]}"
    try:
        await asyncio.wait_for(interp.stop(), 5)
    except Exception as e:                                       # noqa: BLE001
        row["stop"] = type(e).__name__
    return row


async def main():
    for kind in ("async", "sync"):
        R[f"default_{kind}"] = await run(kind, None)
        print(kind, R[f"default_{kind}"]["trail"],
              R[f"default_{kind}"]["last_error"], flush=True)
        R[f"mi50_{kind}"] = await run(kind, 50, secs=1.0)

asyncio.run(main())
json.dump(R, open("results/s2_plateau.json", "w", encoding="utf-8"),
          indent=2, default=str)
for k, v in R.items():
    print(k, "svc=", v["svc"], v["ids"], v["status"], v["last_error"],
          "| post:", v["post_release"], v["post_status"], v["post_ids"],
          "| +svc:", v["svc_after_external"], "| snap:", v["snapshot"])
