# -*- coding: utf-8 -*-
"""s4: B18 external priority sends (#180) + explicit rollback/onDone and
always->invoked-child shapes: termination, boundedness, lap-count parity."""
import asyncio, json, logging
logging.disable(logging.CRITICAL)
from d import mk, CTL
from h import Stub, TraceP, build, cfg_of, ids, SETTLE
from xstate_statemachine import Interpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock

R = {}
GOK = {"cancel_working_requested": True, "flatten_requested": True,
       "all_accounts_flat": True, "owner_and_elevated": True,
       "owner_and_elevated_and_acknowledged_residual": True}

N = 40


async def hang(i, c, e):
    await asyncio.sleep(3600)


async def priority_burst(kind, mid_step=True):
    """Fire N external priority ENGAGE/RETRY_FLATTEN sends; none may be
    charged to the chain budget (#180) -> zero dropped."""
    cfg = cfg_of("B18")
    gv = dict(GOK, all_accounts_flat=False)
    svc = {"cancel_all_working_orders": hang} if mid_step else {}
    st = Stub(cfg, kind=kind, guard_vals=gv, svc=svc)
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    # open a macrostep first (cancelling hangs) so priority sends land mid-step
    first = await asyncio.wait_for(interp.send("ENGAGE", priority=True, wait=True), 5)
    futs = [interp.send("RETRY_FLATTEN", priority=True) for _ in range(N)]
    res = await asyncio.gather(*futs, return_exceptions=True)
    await asyncio.sleep(0.4)
    errs = {}
    for r in res:
        k = type(r).__name__ if isinstance(r, BaseException) else "ok"
        errs[k] = errs.get(k, 0) + 1
    row = {"kind": kind, "mid_step": mid_step, "n": N,
           "first_changed": first.changed,
           "results": errs, "dropped": tp.dropped, "n_dropped": len(tp.dropped),
           "ids": ids(interp), "status": interp.status,
           "last_error": type(getattr(interp, "last_error", None)).__name__,
           "svc_calls": len(st.svc_calls)}
    try:
        await asyncio.wait_for(interp.stop(), 5)
    except Exception:
        pass
    return row


async def lap_shape(kind, name, cfgmut, ev, gv, raising, mi=8):
    """Drive a hazardous shape explicitly; report lap count = service calls."""
    cfg = cfg_of("B18")
    cfg["maxIterations"] = mi
    cfgmut(cfg)
    st = Stub(cfg, kind=kind, guard_vals=gv, raising=raising)
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    to = False
    try:
        r = await asyncio.wait_for(interp.send(ev, wait=True), 8)
        rr = {"changed": r.changed,
              "error": type(r.error).__name__ if r.error else None}
    except asyncio.TimeoutError:
        to = True; rr = "TIMEOUT"
    except Exception as e:                                       # noqa: BLE001
        rr = f"{type(e).__name__}: {str(e)[:120]}"
    await asyncio.sleep(0.5)
    row = {"kind": kind, "name": name, "mi": mi, "timed_out": to,
           "laps_svc": len(st.svc_calls), "actions": len(st.trace),
           "ids": ids(interp), "status": interp.status, "receipt": rr,
           "last_error": type(getattr(interp, "last_error", None)).__name__,
           "transitions": len(tp.transitions)}
    try:
        await asyncio.wait_for(interp.stop(), 5)
    except Exception:
        pass
    return row


def mut_rollback_ondone(cfg):
    """flattening.onDone -> engaged_incomplete whose entry raises (rollback)."""
    return


def mut_always_into_invoke(cfg):
    """engaged_incomplete.always -> flattening: always into an invoking sibling."""
    cfg["states"]["engaged_incomplete"]["always"] = [
        {"target": "#kill_switch.flattening"}]


async def main():
    for kind in ("async", "sync"):
        R[f"prio_midstep_{kind}"] = await priority_burst(kind, True)
        R[f"prio_idle_{kind}"] = await priority_burst(kind, False)
        R[f"shape_rollback_ondone_{kind}"] = await lap_shape(
            kind, "rollback+onDone", mut_rollback_ondone, "ENGAGE",
            dict(GOK, all_accounts_flat=False), ["page_owner"])
        R[f"shape_always_invoke_{kind}"] = await lap_shape(
            kind, "always->invoked child", mut_always_into_invoke, "ENGAGE",
            dict(GOK, all_accounts_flat=False), [])
    for k, v in R.items():
        print(k, json.dumps({x: v[x] for x in v
                             if x not in ("dropped", "transitions")},
                            default=str), flush=True)

asyncio.run(main())
json.dump(R, open("results/s4_prio_shapes.json", "w", encoding="utf-8"),
          indent=2, default=str)
