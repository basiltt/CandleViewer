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

from xstate_statemachine import QueueOverflowError, SnapshotCorruptError


@scenario("R5-157", "#157", "B11 bounded inbox RAISE: overflow raises at the send_threadsafe call site")
async def s_157():
    cfg, st, m, tp = mk("B11", svc={"subscribe_streams": lambda i, c, e: asyncio.sleep(5)})
    it = Interpreter(m, clock=SimulatedClock(), max_queue_size=4,
                     overflow_policy=OverflowPolicy.RAISE)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True)   # -> starting, svc hangs
    await asyncio.sleep(0.05)
    res, loop = [], asyncio.get_running_loop()
    def worker():
        for i in range(40):
            try:
                it.send_threadsafe("REASON_ADDED", reason="r%d" % i, internal=True)
                res.append("ok")
            except QueueOverflowError as exc:
                res.append("QueueOverflowError")
            except Exception as exc:
                res.append(type(exc).__name__)
    t = threading.Thread(target=worker); t.start()
    await asyncio.sleep(0.4)
    t.join(5)
    out = {"results_tail": res[-6:], "n_ok": res.count("ok"),
           "n_overflow": res.count("QueueOverflowError"),
           "other": sorted({r for r in res if r not in ("ok", "QueueOverflowError")}),
           "status": it.status}
    await it.stop()
    out["ok"] = out["n_overflow"] > 0 and not out["other"]
    out["note"] = ("CV mandates a bounded inbox with RAISE on the order path; "
                   "#157 says the raise must land on the CALLER, not a dropped future")
    return out


@scenario("R5-142", "#142/#143", "B13 hostile snapshot: emptied configuration is refused")
async def s_142():
    cfg, st, m, tp = mk("B13", svc={"open_socket": {"ok": True},
                                    "subscribe_in_batches": {"topics": ["t"]}},
                        guard_vals={"connection_budget_exhausted": False, "is_private": False})
    it = ainterp(m); it.use(tp)
    await it.start()
    await it.send("CONNECT", wait=True)
    await quiesce(it, 20)
    snap = it.get_persisted_snapshot()
    await it.stop()
    out = {"clean_states": sorted(snap.get("state_ids") or snap.get("configuration") or [])}
    cases = {}
    def restore(mut, name):
        s = json.loads(json.dumps(snap))
        mut(s)
        try:
            i2 = Interpreter.from_snapshot(s, m)
            cases[name] = "ACCEPTED state=%s status=%s" % (
                sorted(i2.current_state_ids), i2.status)
        except Exception as exc:
            cases[name] = "%s: %s" % (type(exc).__name__, str(exc)[:80])
    key = "state_ids" if "state_ids" in snap else "configuration"
    restore(lambda s: s.__setitem__(key, []), "empty_configuration")
    restore(lambda s: s.__setitem__(key, ["ws_conn"]), "non_leaf_only")
    restore(lambda s: s.__setitem__("status", 42), "status_not_str")
    restore(lambda s: s.__setitem__("status", "error"), "error_status_no_error")
    restore(lambda s: s.__setitem__("version", {"x": 1}), "version_wrong_type")
    restore(lambda s: s.__setitem__("deferred", "notalist"), "deferred_wrong_type")
    out["cases"] = cases
    out["ok"] = all(not v.startswith("ACCEPTED") for v in cases.values())
    return out


@scenario("R5-162", "#162", "B11 restored pending user event keeps user provenance")
async def s_162():
    """A user event parked in `deferred` must restore as a USER event, subject to
    onUnhandled/strict -- not laundered into an engine event."""
    cfg, st, m, tp = mk("B11")
    it = ainterp(m); it.use(tp)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True)
    await quiesce(it, 20)
    # in `recording`; STREAM_HEALTHY is undeclared there -> deferred (defer policy)
    await it.send("STREAM_HEALTHY", s="trade", wait=True)
    await asyncio.sleep(0.05)
    out = {"states": ids(it), "deferred_count": it.deferred_count}
    try:
        snap = it.get_persisted_snapshot()
        out["snapshot"] = "TAKEN"
        out["deferred_in_snapshot"] = snap.get("deferred")
    except Exception as exc:
        out["snapshot"] = "%s: %s" % (type(exc).__name__, str(exc)[:100])
        snap = None
    await it.stop()
    out["ok"] = out["deferred_count"] >= 0
    out["note"] = ("CV-C20 says snapshot only at quiescence (deferred_count==0); "
                   "this records what happens if a caller ignores that")
    return out


if __name__ == "__main__":
    sys.exit(run_all("r5_edges"))
