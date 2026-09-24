# -*- coding: utf-8 -*-
"""#180 on contract machines: external send(priority=True) must NEVER be charged
to the chain budget -- the B18 kill-switch lane. 0 dropped, both service lanes.
Plus: does the R6-01 bound land at the SAME lap count on both engines?"""
import asyncio, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter, SyncInterpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock

N_PRIO = 60

async def prio(style, machine, ev, kw, setup=None, gv=None, impl=None, slow=0.05):
    cfg = H.load(machine)
    if setup: setup(cfg)
    st = H.Stub(cfg, guard_vals=gv, act_impl=impl, svc_style=style)
    # make the invoked services slow so the sends land MID-macrostep (#180 window)
    if style == "async":
        async def _slow(i, c, e):
            await asyncio.sleep(slow); return {"ok": True}
        st.svc = {n: _slow for n in st.svcs}
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(tp)
    t0 = time.time(); await it.start()
    rcs = []
    for i in range(N_PRIO):
        rcs.append(await it.send_priority(ev, wait=True, **kw))
        if i % 7 == 0: await asyncio.sleep(0)
    await quiesce(it, 6)
    errs = [type(r.error).__name__ for r in rcs if r.error]
    r = {"style": style, "machine": machine, "event": ev, "sent": N_PRIO,
         "receipt_errors": errs[:5], "n_receipt_errors": len(errs),
         "plugin_dropped": tp.dropped[:5], "n_dropped": len(tp.dropped),
         "chain_budget_drops": sum(1 for _, why in tp.dropped if why == "chain_budget"),
         "states": ids(it), "status": it.status,
         "last_error": type(it.last_error).__name__ if it.last_error else None,
         "elapsed_s": round(time.time()-t0, 3)}
    await asyncio.wait_for(it.stop(), 8)
    r["ok"] = (r["n_dropped"] == 0 and r["n_receipt_errors"] == 0
               and r["last_error"] != "RunawayChainError")
    return r

def _b13(cfg):
    cfg["context"]["kind"] = "public"; cfg["context"]["pending_topics"] = ["trade"]

CASES = [
    ("B11", "GAP_DETECTED", {"stream": "trade"}, None, None, "b11"),
    ("B14", "DELTA", {"seq": 1}, None, None, None),
    ("B15", "MARK_UPDATE", {"px": "100"}, None,
     {"mark_crossed_liq_price": False, "below_maintenance_margin": False,
      "above_maintenance_margin": True}, None),
    ("B13", "PONG", {}, _b13,
     {"is_private": False, "connection_budget_exhausted": False}, "b13"),
]

for _m, _ev, _kw, _su, _gv, _imp in CASES:
    for _s in ("async", "def"):
        def _f(_m=_m, _ev=_ev, _kw=_kw, _su=_su, _gv=_gv, _imp=_imp, _s=_s):
            async def go():
                impl = None
                if _imp == "b11":
                    from g3_b11 import IMPL, GV
                    impl = IMPL; g = _gv or GV
                elif _imp == "b13":
                    from g3_b13 import IMPL
                    impl = IMPL; g = _gv
                else:
                    g = _gv
                return await prio(_s, _m, _ev, _kw, _su, g, impl)
            return go
        scenario("PRIO-%s-%s" % (_m, _s), "#180",
                 "%s: %d external send_priority, 0 charged (%s services)"
                 % (_m, N_PRIO, _s))(_f())

# ---- same-lap-count parity for the R6-01 bound -------------------------
@scenario("LAP-B11", "#179", "R6-01 bound lands at the same lap count, def vs async")
async def lap():
    import h1_r601 as R
    out = {}
    for s in ("async", "def"):
        rs = [await R._async_case(R.B11, s, maxit=25) for _ in range(3)]
        out[s] = [x["svc_n"] for x in rs]
    a, d = out["async"], out["def"]
    return {"svc_counts": out, "async_stable": len(set(a)) == 1,
            "def_stable": len(set(d)) == 1, "same": set(a) == set(d),
            "ok": len(set(a)) == 1 and len(set(d)) == 1 and set(a) == set(d)}

if __name__ == "__main__":
    sys.exit(run_all("h3_prio"))
