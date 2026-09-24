# -*- coding: utf-8 -*-
"""s5: corrected #180 burst -- reach engaged_incomplete first, where
RETRY_FLATTEN IS declared, then fire N external priority sends."""
import asyncio, json, logging
logging.disable(logging.CRITICAL)
from d import CTL
from h import Stub, TraceP, build, cfg_of, ids, SETTLE
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock

R = {}
GV = {"cancel_working_requested": True, "flatten_requested": True,
      "all_accounts_flat": False, "owner_and_elevated": True,
      "owner_and_elevated_and_acknowledged_residual": True}
N = 50


async def burst(kind, priority):
    cfg = cfg_of("B18")
    st = Stub(cfg, kind=kind, guard_vals=GV)
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    await asyncio.wait_for(interp.send("ENGAGE", wait=True), 5)
    await asyncio.sleep(SETTLE)
    assert ids(interp) == ["kill_switch.engaged_incomplete"], ids(interp)
    base = len(st.svc_calls)
    futs = [interp.send("RETRY_FLATTEN", priority=priority) for _ in range(N)]
    res = await asyncio.gather(*futs, return_exceptions=True)
    await asyncio.sleep(0.6)
    errs = {}
    for r in res:
        if isinstance(r, BaseException):
            k = "EXC:" + type(r).__name__
        elif r is None:
            k = "none"
        elif getattr(r, "error", None) is not None:
            k = "ERR:" + type(r.error).__name__
        else:
            k = "ok_changed" if getattr(r, "changed", None) else "ok_nochange"
        errs[k] = errs.get(k, 0) + 1
    row = {"kind": kind, "priority": priority, "n": N, "results": errs,
           "n_dropped": len(tp.dropped), "dropped_reasons":
           sorted({d[1] for d in tp.dropped}),
           "svc_applied": len(st.svc_calls) - base,
           "ids": ids(interp), "status": interp.status,
           "last_error": type(getattr(interp, "last_error", None)).__name__}
    try:
        await asyncio.wait_for(interp.stop(), 5)
    except Exception:
        pass
    return row


async def main():
    for kind in ("async", "sync"):
        for pri in (True, False):
            k = f"{kind}_{'prio' if pri else 'plain'}"
            R[k] = await burst(kind, pri)
            print(k, json.dumps(R[k], default=str), flush=True)

asyncio.run(main())
json.dump(R, open("results/s5_prio.json", "w", encoding="utf-8"),
          indent=2, default=str)
