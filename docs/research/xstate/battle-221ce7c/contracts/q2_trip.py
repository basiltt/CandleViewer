# -*- coding: utf-8 -*-
"""After a bounded chain trip in B18/B19: is the trip observable, is the
machine still live, does maxIterations scale the side-effect count?"""
import asyncio, json, time
from cdrv import mk, cfg_of
from charness import SETTLE, ids
from xstate_statemachine import OverflowPolicy

R = {}
CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)


async def mk_mi(b, stub_kw, max_iterations, **ikw):
    """mk() but with `maxIterations` injected into the machine config."""
    import json as _j
    from charness import Stub, build, TraceP
    from xstate_statemachine import Interpreter
    from xstate_statemachine.clock import SimulatedClock
    cfg = cfg_of(b)
    cfg["maxIterations"] = max_iterations
    st = Stub(cfg, **(stub_kw or {}))
    m = build(cfg, st)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock, **ikw)
    tp = TraceP(); interp.use(tp)
    await interp.start(); await asyncio.sleep(SETTLE)
    return interp, st, tp, clock, m


async def probe(b, first, then, stub_kw, clear_raise=True,
                max_iterations=None, **ikw):
    if max_iterations is None:
        interp, st, tp, clock, m = await mk(b, stub_kw, **ikw)
    else:
        interp, st, tp, clock, m = await mk_mi(b, stub_kw, max_iterations, **ikw)
        assert getattr(m, "max_iterations", None) == max_iterations, \
            f"maxIterations not honoured: {getattr(m, 'max_iterations', None)}"
    o = {}
    t0 = time.perf_counter()
    r = await asyncio.wait_for(interp.send(first, wait=True), 10)
    await asyncio.sleep(SETTLE * 4)
    o["first"] = {"changed": r.changed,
                  "error": type(r.error).__name__ if r.error else None,
                  "svc": len(st.svc_calls), "ids": ids(interp),
                  "last_error": type(getattr(interp, "last_error", None)).__name__
                  if getattr(interp, "last_error", None) else None,
                  "last_transition_ok": getattr(interp, "last_transition_ok", "n/a"),
                  "wall": round(time.perf_counter() - t0, 3)}
    if clear_raise:
        st.raising = set()          # operator "fixes" the failing action
    o["dropped"] = list(tp.dropped)
    o["unhandled"] = list(tp.unhandled)
    n0 = len(st.svc_calls)
    for e in then:
        try:
            r2 = await asyncio.wait_for(interp.send(e, wait=True), 10)
            o.setdefault("then", []).append(
                {"ev": e, "changed": r2.changed,
                 "error": type(r2.error).__name__ if r2.error else None,
                 "ids": ids(interp)})
        except asyncio.TimeoutError:
            o.setdefault("then", []).append({"ev": e, "TIMEOUT": True})
        await asyncio.sleep(SETTLE * 3)
    o["svc_after"] = len(st.svc_calls) - n0
    o["final_ids"] = ids(interp)
    o["status"] = interp.status
    try:
        await asyncio.wait_for(interp.stop(), 5)
    except Exception as ex:
        o["stop_error"] = type(ex).__name__
    return o


async def main():
    KW18 = {"guard_vals": {"cancel_working_requested": True,
                           "flatten_requested": True,
                           "all_accounts_flat": False},
            "raising": ["page_owner"]}
    R["b18_after_trip"] = await probe("B18", "ENGAGE", ["RELEASE"], KW18, **CTL)
    R["b18_after_trip_noclear"] = await probe(
        "B18", "ENGAGE", ["RELEASE"], dict(KW18), clear_raise=False, **CTL)
    KW19 = {"guard_vals": {"divergences_found_and_auto_remediate": True},
            "raising": ["store_divergences"]}
    R["b19_after_trip"] = await probe("B19", "SWEEP_DUE", ["CANCEL", "SWEEP_DUE"],
                                      KW19, **CTL)
    # maxIterations scaling: does the settle budget control the blast radius?
    for n in (2, 5, 25):
        R[f"b18_maxiter_{n}"] = await probe("B18", "ENGAGE", [], KW18,
                                            max_iterations=n, **CTL)
    # service_pool_size interaction (new in 0.8.1) with the bounded chain
    R["b18_pool1"] = await probe("B18", "ENGAGE", [], KW18,
                                 service_pool_size=1, **CTL)

asyncio.run(main())
json.dump(R, open("results/q2_trip.json", "w", encoding="utf-8"), indent=2,
          default=str)
for k, v in R.items():
    f = v["first"]
    print(k, "| svc", f["svc"], "| lastErr", f["last_error"],
          "| ok", f["last_transition_ok"], "| recv_err", f["error"],
          "| ids", f["ids"], "| then", v.get("then"), "| svc_after",
          v["svc_after"], "| dropped", v["dropped"])
