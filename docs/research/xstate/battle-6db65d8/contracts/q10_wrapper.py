# -*- coding: utf-8 -*-
"""Wrapper feasibility: does making B18's services plain `def` bound the
chain in the real contract machine? (The Stub's services are `async def`.)"""
import asyncio, json
from charness import SETTLE, Stub, build, TraceP, ids
from cdrv import cfg_of
from xstate_statemachine import Interpreter, MachineLogic, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.actions import is_builtin

CTL = dict(max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
KW = {"guard_vals": {"cancel_working_requested": True,
                     "flatten_requested": True,
                     "all_accounts_flat": False},
      "raising": ["page_owner"]}
R = {}


def sync_logic(st):
    """Same stub semantics, but every service is a plain `def`."""
    base = st.logic()

    def mk_s(n):
        def s(interp, ctx, evt):
            st.svc_calls.append(n)
            v = st.svc.get(n, {"ok": True})
            if isinstance(v, BaseException):
                raise v
            return v
        s.__name__ = n
        return s

    return MachineLogic(actions=base.actions, guards=base.guards,
                        services={n: mk_s(n) for n in st.svcs},
                        delays=base.delays, strict=True)


async def cell(service_kind, mi=None, watch=1.0):
    cfg = cfg_of("B18")
    if mi is not None:
        cfg["maxIterations"] = mi
    st = Stub(cfg, **KW)
    from xstate_statemachine import create_machine
    import copy as _c
    lg = st.logic() if service_kind == "async" else sync_logic(st)
    m = create_machine(_c.deepcopy(cfg), logic=lg, strict_targets=True)
    it = Interpreter(m, clock=SimulatedClock(), **CTL)
    tp = TraceP(); it.use(tp)
    await it.start(); await asyncio.sleep(SETTLE)
    await asyncio.wait_for(it.send("ENGAGE", wait=True), 15)
    await asyncio.sleep(watch)
    n1 = len(st.svc_calls)
    await asyncio.sleep(watch)
    o = {"service_kind": service_kind, "maxIterations": mi,
         "svc_at_t": n1, "svc_at_2t": len(st.svc_calls),
         "still_growing": len(st.svc_calls) > n1,
         "acts": len(st.trace), "ids": ids(it), "status": it.status,
         "last_error": type(getattr(it, "last_error", None)).__name__
         if getattr(it, "last_error", None) else None}
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception as ex:
        o["stop_error"] = type(ex).__name__
    return o


async def main():
    R["async_svc_default"] = await cell("async")
    R["def_svc_default"] = await cell("def")
    R["def_svc_mi5"] = await cell("def", mi=5)
    R["async_svc_mi5"] = await cell("async", mi=5)

asyncio.run(main())
json.dump(R, open("results/q10_wrapper.json", "w", encoding="utf-8"),
          indent=2, default=str)
for k, v in R.items():
    print(k, "| svc@t", v["svc_at_t"], "| svc@2t", v["svc_at_2t"],
          "| growing", v["still_growing"], "| lastErr", v["last_error"],
          "|", v["ids"])
