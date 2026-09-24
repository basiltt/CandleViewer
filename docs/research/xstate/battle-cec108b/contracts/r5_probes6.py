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


@scenario("R5-142b", "#142/#143", "B13 hostile snapshot (CORRECT json-string form)")
async def s_142b():
    cfg, st, m, tp = mk("B13", svc={"open_socket": {"ok": True},
                                    "subscribe_in_batches": {"topics": ["t"]}},
                        guard_vals={"connection_budget_exhausted": False, "is_private": False})
    it = ainterp(m)
    await it.start()
    await it.send("CONNECT", wait=True)
    await quiesce(it, 20)
    snap = it.get_persisted_snapshot()
    await it.stop()
    key = "state_ids" if "state_ids" in snap else "configuration"
    out = {"snapshot_keys": sorted(snap.keys()), "cfg_key": key,
           "clean": sorted(snap[key])}
    cases = {}
    def restore(mut, name):
        s = json.loads(json.dumps(snap))
        mut(s)
        try:
            i2 = Interpreter.from_snapshot(json.dumps(s), m, verify_machine_hash=False)
            cases[name] = "ACCEPTED state=%s status=%s" % (
                sorted(i2.current_state_ids), i2.status)
        except Exception as exc:
            cases[name] = "%s: %s" % (type(exc).__name__, str(exc)[:90])
    restore(lambda s: None, "unmodified_control")
    restore(lambda s: s.__setitem__(key, []), "empty_configuration")
    restore(lambda s: s.__setitem__(key, ["ws_conn"]), "non_leaf_only")
    restore(lambda s: s.__setitem__("status", 42), "status_not_str")
    restore(lambda s: s.__setitem__("status", "error"), "error_status_no_error")
    restore(lambda s: s.__setitem__("version", {"x": 1}), "version_wrong_type")
    restore(lambda s: s.__setitem__("deferred", "notalist"), "deferred_wrong_type")
    restore(lambda s: s.__setitem__("history", 7), "history_wrong_type")
    restore(lambda s: s.__setitem__("actors", "nope"), "actors_wrong_type")
    restore(lambda s: s.__setitem__("deferred", [{"kind": "event", "type": 5}]), "pending_type_not_str")
    out["cases"] = cases
    bad = {k: v for k, v in cases.items()
           if k != "unmodified_control" and v.startswith("ACCEPTED")}
    out["accepted_hostile"] = bad
    out["ok"] = cases["unmodified_control"].startswith("ACCEPTED") and not bad
    return out


@scenario("R5-157b", "#157", "B11 bounded inbox RAISE: overflow at send_threadsafe (loop genuinely busy)")
async def s_157b():
    """The first attempt never filled the queue: the loop drained faster than a
    Python thread could push. Block the loop for real, then push."""
    cfg = H.load("B11")
    st = H.Stub(cfg)
    def blocking(interp, ctx, evt):
        time.sleep(1.0)
        return {"ok": True}
    logic = st.logic()
    logic.services["subscribe_streams"] = blocking      # runs on the executor
    m = X.create_machine(copy.deepcopy(cfg), logic=logic)
    it = Interpreter(m, clock=SimulatedClock(), max_queue_size=4,
                     overflow_policy=OverflowPolicy.RAISE)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True)
    # hard-block the loop so the inbox cannot drain
    gate = threading.Event()
    res = []
    def worker():
        gate.wait()
        for i in range(200):
            try:
                it.send_threadsafe("REASON_ADDED", reason="r%d" % i, internal=True)
                res.append("ok")
            except QueueOverflowError:
                res.append("QueueOverflowError")
            except Exception as exc:
                res.append(type(exc).__name__ + ":" + str(exc)[:40])
    t = threading.Thread(target=worker); t.start()
    gate.set()
    time.sleep(0.35)                      # block the LOOP thread deliberately
    await asyncio.sleep(0.4)
    t.join(5)
    out = {"n_ok": res.count("ok"), "n_overflow": res.count("QueueOverflowError"),
           "other": sorted({r for r in res if r != "ok" and r != "QueueOverflowError"}),
           "tail": res[-4:], "status": it.status}
    await it.stop()
    out["ok"] = out["n_overflow"] > 0 and not out["other"]
    out["note"] = ("raise must land on the calling thread, not on an unread future; "
                   "n_ok<200 with n_overflow>0 is the #157 fix working")
    return out


@scenario("R5-157c", "#157", "B12/B15 order-path inbox: RAISE surfaces on the async send() too")
async def s_157c():
    cfg = H.load("B15")
    st = H.Stub(cfg, guard_vals={"mark_crossed_liq_price": False,
                                 "below_maintenance_margin": False})
    m = H.build(cfg, st)
    it = Interpreter(m, clock=SimulatedClock(), max_queue_size=3,
                     overflow_policy=OverflowPolicy.RAISE)
    await it.start()
    outs = []
    for i in range(50):                    # no awaits between -> queue builds
        try:
            it.send("MARK_UPDATE", mark=str(i))
            outs.append("ok")
        except QueueOverflowError:
            outs.append("QueueOverflowError")
        except Exception as exc:
            outs.append(type(exc).__name__)
    await quiesce(it, 15)
    out = {"n_ok": outs.count("ok"), "n_overflow": outs.count("QueueOverflowError"),
           "other": sorted({o for o in outs if o not in ("ok", "QueueOverflowError")}),
           "status": it.status, "states": ids(it)}
    await it.stop()
    out["ok"] = out["n_overflow"] > 0 and not out["other"]
    return out


if __name__ == "__main__":
    sys.exit(run_all("r5_edges2"))
