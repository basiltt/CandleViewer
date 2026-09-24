# -*- coding: utf-8 -*-
"""#180 on B13/B14, driven to a state where the priority event is LEGAL first."""
import asyncio, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock

N = 60

async def run(style, machine, drive, ev, kw, setup=None, gv=None, impl=None):
    cfg = H.load(machine)
    if setup: setup(cfg)
    st = H.Stub(cfg, guard_vals=gv, act_impl=impl, svc_style=style)
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(tp)
    await it.start()
    for d, dk in drive:
        await it.send(d, wait=True, **dk)
    await quiesce(it, 4)
    pre = ids(it)
    tp.dropped.clear()
    rcs = []
    t0 = time.time()
    for i in range(N):
        rcs.append(await it.send_priority(ev, wait=True, **(kw(i) if callable(kw) else kw)))
        if i % 7 == 0: await asyncio.sleep(0)
    await quiesce(it, 6)
    errs = [type(r.error).__name__ for r in rcs if r.error]
    r = {"style": style, "machine": machine, "pre_state": pre, "event": ev,
         "sent": N, "n_receipt_errors": len(errs), "receipt_errors": errs[:4],
         "n_dropped": len(tp.dropped),
         "chain_budget_drops": sum(1 for _, w in tp.dropped if w == "chain_budget"),
         "drop_reasons": sorted({w for _, w in tp.dropped}),
         "states": ids(it), "status": it.status,
         "last_error": type(it.last_error).__name__ if it.last_error else None,
         "elapsed_s": round(time.time()-t0, 3)}
    await asyncio.wait_for(it.stop(), 8)
    r["ok"] = (r["chain_budget_drops"] == 0 and r["n_receipt_errors"] == 0
               and r["last_error"] != "RunawayChainError" and r["status"] == "running")
    return r

def _b13cfg(cfg):
    cfg["context"]["kind"] = "public"; cfg["context"]["pending_topics"] = ["trade"]

def _b14impl():
    def buf(i,c,e,a): c["buffered_deltas"] = c["buffered_deltas"] + [e.payload.get("seq")]
    def clr(i,c,e,a): c["buffered_deltas"] = []
    def bump(i,c,e,a): c["resync_count"] = c["resync_count"] + 1
    return {"buffer_delta": buf, "clear_buffer": clr, "bump_resync_count": bump}

for _s in ("async", "def"):
    def _f13(_s=_s):
        async def go():
            from g3_b13 import IMPL
            return await run(_s, "B13", [("CONNECT", {})], "PONG", {},
                             _b13cfg, {"is_private": False,
                                       "connection_budget_exhausted": False}, IMPL)
        return go
    scenario("PRIO2-B13-%s" % _s, "#180",
             "B13 live: %d external send_priority PONG, 0 charged (%s)" % (N, _s))(_f13())

    def _f14(_s=_s):
        async def go():
            return await run(_s, "B14",
                             [("SUBSCRIBE", {"symbol": "BTC"}), ("SNAPSHOT", {"seq": 10})],
                             "DELTA", lambda i: {"seq": 11 + i}, None, None, _b14impl())
        return go
    scenario("PRIO2-B14-%s" % _s, "#180",
             "B14 live: %d external send_priority DELTA, 0 charged (%s)" % (N, _s))(_f14())

if __name__ == "__main__":
    sys.exit(run_all("h4_prio2"))
