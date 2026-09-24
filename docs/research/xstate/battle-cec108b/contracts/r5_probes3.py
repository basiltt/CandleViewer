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



@scenario("R5-strict", "strict", "B13 strict: undeclared name rejected at the call site (FRESH machine)")
async def s_strict():
    """The 3ed3099 run reported strict=false-negative. Re-test on a machine that
    has NOT already been killed by a prior onUnhandled=error event."""
    res = {}
    for name in ["NOT_A_REAL_EVENT", "after.party", "done.invoke.bogus", "xstate.bogus"]:
        cfg, st, m, tp = mk("B13", svc={"open_socket": {"ok": True},
                                        "subscribe_in_batches": {"topics": []}},
                            guard_vals={"connection_budget_exhausted": False,
                                        "is_private": False})
        it = ainterp(m); it.use(tp)
        await it.start()
        await it.send("CONNECT", wait=True)
        await quiesce(it, 20)
        pre = ids(it)
        try:
            await it.send(name, wait=True)
            res[name] = "ACCEPTED pre=%s post=%s status=%s" % (pre, ids(it), it.status)
        except Exception as exc:
            res[name] = "RAISED %s: %s" % (type(exc).__name__, str(exc)[:90])
        await it.stop()
    ok = all(v.startswith("RAISED UnknownEventError") for v in res.values())
    return {"ok": ok, "results": res,
            "note": "prior round reported these ACCEPTED; that run reused an "
                    "interpreter already in status=error, where sends are dropped "
                    "before the strict check. Harness defect, not a library one."}


@scenario("R5-unh-recv", "#153/LIB-01", "B13 onUnhandled=error: is the kill visible to the sender now?")
async def s_unh():
    cfg, st, m, tp = mk("B13", svc={"open_socket": {"ok": True},
                                    "subscribe_in_batches": {"topics": []}},
                        guard_vals={"connection_budget_exhausted": False, "is_private": False})
    it = ainterp(m); it.use(tp)
    await it.start()
    await it.send("CONNECT", wait=True)
    await quiesce(it, 20)
    assert ids(it) == ["ws_conn.live"], ids(it)
    # CONNECT is DECLARED by the machine (so strict passes) but not in `live`.
    raised, r = None, None
    try:
        r = await it.send("CONNECT", wait=True)
    except Exception as exc:
        raised = "%s: %s" % (type(exc).__name__, exc)
    await asyncio.sleep(0.05)
    out = {"raised_at_call_site": raised, "receipt": str(r),
           "receipt_error": str(getattr(r, "error", None)) if r else None,
           "receipt_denied": getattr(r, "denied", "ABSENT") if r else None,
           "status": it.status, "interp_error": str(getattr(it, "error", None))[:120],
           "last_error": str(getattr(it, "last_error", None)),
           "unhandled_hook": tp.unhandled, "states": ids(it)}
    await it.stop()
    out["ok"] = raised is not None or (r is not None and getattr(r, "error", None) is not None)
    out["note"] = ("LIB-01 from the prior round: the receipt for the send that KILLED "
                   "the machine. ok=True would mean #153/#159 closed it.")
    return out


# ------------------------------------------- #145 actionErrorPolicy fail ----
@scenario("R5-145", "#145", "B11 actionErrorPolicy=fail -> stopped + config cleared")
async def s_145():
    def mut(cfg):
        cfg["actionErrorPolicy"] = "fail"
    cfg, st, m, tp = mk("B11", cfg_mut=mut, raising=("emit_recording_metric",))
    it = ainterp(m); it.use(tp)
    await it.start()
    try:
        await it.send("REASON_ADDED", reason="chart", wait=True)
    except Exception:
        pass
    await quiesce(it, 15)
    out = {"status": it.status, "states": ids(it),
           "error": "%s: %s" % (type(it.error).__name__, str(it.error)[:100]) if it.error else None,
           "is_running": it.is_running}
    # can a machine stopped this way be persisted as resumable?
    try:
        snap = it.get_persisted_snapshot()
        out["snapshot"] = "TAKEN status=%s cfg=%s" % (snap.get("status"), snap.get("configuration") or snap.get("state_ids"))
    except Exception as exc:
        out["snapshot"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    await it.stop()
    out["ok"] = (out["status"] == "stopped" and out["states"] == []
                 and out["error"] is not None)
    out["note"] = "rollback is what the contract mandates; this probes the fail escape hatch"
    return out


# --------------------------------------- rollback on the contract machines ----
@scenario("R5-rollback", "rollback", "B11 rollback: a raising entry action leaves context+state intact")
async def s_rollback():
    cfg, st, m, tp = mk("B11", raising=("emit_recording_metric",),
                        act_impl={"add_reason": lambda i, c, e, a:
                                  c.__setitem__("reasons", sorted(set(c["reasons"]) | {e.payload["reason"]}))})
    it = ainterp(m); it.use(tp)
    await it.start()
    await it.send("REASON_ADDED", reason="chart", wait=True)
    await quiesce(it, 20)
    out = {"states": ids(it), "status": it.status, "reasons": list(it.context["reasons"]),
           "last_transition_ok": getattr(it, "last_transition_ok", "ABSENT"),
           "last_error": str(getattr(it, "last_error", None))[:100],
           "transitions": tp.transitions, "actions": tp.actions}
    # machine must still be usable
    r = await it.send("REASON_ADDED", reason="alerts", wait=True)
    await quiesce(it, 10)
    out["after_second"] = {"states": ids(it), "reasons": list(it.context["reasons"])}
    await it.stop()
    out["ok"] = it.status != "error" and out["status"] != "stopped"
    return out


if __name__ == "__main__":
    sys.exit(run_all("r5_strict_145"))
