# -*- coding: utf-8 -*-
"""Round-5 fix probes mapped onto the B11-B15 contract machines (cec108b)."""
import asyncio, copy, json, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
import xstate_statemachine as X
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock


def mk(b, guard_vals=None, svc=None, act_impl=None, cfg_mut=None, **kw):
    cfg = H.load(b)
    if cfg_mut:
        cfg_mut(cfg)
    st = H.Stub(cfg, guard_vals=guard_vals or {}, svc=svc or {},
                act_impl=act_impl or {}, **kw)
    m = H.build(cfg, st)
    tp = H.TraceP()
    return cfg, st, m, tp


def ainterp(m, **kw):
    return Interpreter(m, clock=SimulatedClock(), **kw)



@scenario("R5-RB1", "rollback", "B11 rollback + raising entry: does the onDone retry loop terminate?")
async def s_rb1():
    """recording.entry=[cancel_linger, emit_recording_metric]. emit raises.
    actionErrorPolicy=rollback => transition undone, back in `starting`.
    Question: is the invoke completion re-delivered / re-attempted for ever?"""
    cfg, st, m, tp = mk("B11", raising=("emit_recording_metric",))
    it = ainterp(m); it.use(tp)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True)
    counts = []
    for _ in range(8):
        await asyncio.sleep(0.25)
        counts.append(st.trace.count("emit_recording_metric"))
    out = {"emit_attempts_over_2s": counts, "states": ids(it), "status": it.status,
           "svc_calls": len(st.svc_calls),
           "still_growing": counts[-1] > counts[-3],
           "queue_depth": getattr(it, "queue_depth", "?"),
           "deferred": it.deferred_count,
           "transitions": tp.transitions[-4:]}
    await it.stop()
    out["ok"] = not out["still_growing"]
    out["note"] = ("if still_growing, a single failing entry action under the "
                   "MANDATED rollback policy is a hot spin, not a contained failure")
    return out


@scenario("R5-RB2", "rollback", "B15 rollback + raising entry on an `always` target")
async def s_rb2():
    """liquidating.entry raises; liquidating has always->liquidated.
    Rollback + a transient transition is the classic spin shape."""
    cfg, st, m, tp = mk("B15", guard_vals={"mark_crossed_liq_price": True},
                        raising=("write_liquidation_journal",))
    it = ainterp(m); it.use(tp)
    await it.start()
    try:
        await it.send("MARK_UPDATE", mark="1", wait=True)
    except Exception as exc:
        pass
    counts = []
    for _ in range(6):
        await asyncio.sleep(0.2)
        counts.append(st.trace.count("write_liquidation_journal"))
    out = {"journal_attempts": counts, "states": ids(it), "status": it.status,
           "still_growing": counts[-1] > counts[-3],
           "last_error": str(getattr(it, "last_error", None))[:80]}
    await it.stop()
    out["ok"] = not out["still_growing"]
    return out


@scenario("R5-RB3", "rollback", "B14 rollback + raising entry on `desynced` (always -> snapshot_pending)")
async def s_rb3():
    cfg, st, m, tp = mk("B14", raising=("emit_resync_metric",))
    it = ainterp(m); it.use(tp)
    await it.start()
    await it.send("SUBSCRIBE", wait=True)
    await it.send("SNAPSHOT", seq=5, wait=True)
    await quiesce(it, 6)
    try:
        await it.send("SEQUENCE_GAP", wait=True)
    except Exception:
        pass
    counts = []
    for _ in range(6):
        await asyncio.sleep(0.2)
        counts.append(st.trace.count("emit_resync_metric"))
    out = {"attempts": counts, "states": ids(it), "status": it.status,
           "still_growing": counts[-1] > counts[-3]}
    await it.stop()
    out["ok"] = not out["still_growing"]
    return out


@scenario("R5-RB4", "rollback", "B11 rollback spin: is it bounded by RunawayChainError?")
async def s_rb4():
    """Same as RB1 but check whether ANY budget/limit ever trips, and whether
    an unrelated event can still be served while the spin runs."""
    cfg, st, m, tp = mk("B11", raising=("emit_recording_metric",),
                        act_impl={"add_reason": lambda i, c, e, a:
                                  c.__setitem__("reasons", sorted(set(c["reasons"]) | {e.payload["reason"]}))})
    it = ainterp(m); it.use(tp)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True)
    await asyncio.sleep(1.0)
    n1 = len(st.trace)
    t0 = time.monotonic()
    served = None
    try:
        r = await asyncio.wait_for(it.send("REASON_ADDED", reason="alerts", wait=True), 3)
        served = "OK in %.2fs %s" % (time.monotonic() - t0, r)
    except asyncio.TimeoutError:
        served = "TIMEOUT after 3s -- inbox starved by the spin"
    except Exception as exc:
        served = "%s: %s" % (type(exc).__name__, str(exc)[:80])
    await asyncio.sleep(0.5)
    out = {"actions_in_1s": n1, "actions_total": len(st.trace),
           "second_event": served, "reasons": list(it.context["reasons"]),
           "status": it.status, "states": ids(it),
           "interp_error": str(getattr(it, "error", None))[:100]}
    await it.stop()
    out["ok"] = "TIMEOUT" not in served and out["status"] != "running"
    return out


if __name__ == "__main__":
    sys.exit(run_all("r5_rollback"))
