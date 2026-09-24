# -*- coding: utf-8 -*-
"""Sync-engine parity for this round's two findings (informational)."""
import json, cvlib
from cvlib import Rig
from xstate_statemachine import SyncInterpreter
from xstate_statemachine.clock import SimulatedClock

def sync_logic(cfg, rig):
    """SyncInterpreter rejects async services (NotSupportedError), so this
    group's parity run needs PLAIN-def services -- itself a CV-C32 data
    point: the sync engine cannot honour CV-C32 at all."""
    lg = cvlib.make_logic(cfg, rig)
    def mk_s(n):
        def fn(interp, ctx, event):
            rig.calls.append("S:" + n)
            mode = rig.service_mode.get(n, "ok")
            if mode == "fail":
                raise RuntimeError("svc-fail:" + n)
            return rig.service_output.get(n, {"svc": n})
        fn.__name__ = n
        return fn
    lg.services = {n: mk_s(n) for n in lg.services}
    return lg


def mk(bid, rig, **kw):
    cfg = cvlib.load(bid)
    m = cvlib.create_machine(json.loads(json.dumps(cfg)),
                             logic=sync_logic(cfg, rig),
                             strict_targets=cfg.get("strictTargets", True))
    it = SyncInterpreter(m, clock=SimulatedClock(), **kw)
    return it, rig

def denied_receipt():
    """F-02 parity: does the sync receipt also read denied=True AND
    deferred=True for a guard-refused event?"""
    rig = Rig(guard_values={"exchange_reports_sl": True, "tightens_only": False})
    it, rig = mk("B8", rig)
    it.start(); it.send("POSITION_OPENED")
    r = it.send("TIGHTEN_SL", wait=True)
    out = {"changed": r.changed, "deferred": r.deferred, "denied": r.denied,
           "error": type(r.error).__name__ if r.error else None,
           "states": sorted(it.current_state_ids),
           "deferred_count": it.deferred_count}
    it.stop(); return out

def guard_raise():
    rig = Rig(guard_values={"exchange_reports_sl": True},
              guard_raises={"tightens_only"})
    it, rig = mk("B8", rig)
    it.start(); it.send("POSITION_OPENED")
    raised = "NO-RAISE"; rec = None
    try:
        r = it.send("TIGHTEN_SL", wait=True)
        rec = {"changed": r.changed, "deferred": r.deferred, "denied": r.denied,
               "error": type(r.error).__name__ if r.error else None}
    except Exception as e:
        raised = f"{type(e).__name__}: {str(e)[:80]}"
    out = {"call_raised": raised, "receipt": rec, "status": it.status,
           "states": sorted(it.current_state_ids)}
    it.stop(); return out

def livelock_budget():
    """F-01 parity: on the SYNC engine, does the naked<->verifying cycle
    (engine-driven done.invoke laps) trip a budget or hang start()/send()?"""
    rig = Rig(guard_values={"exchange_reports_sl": False})
    it, rig = mk("B8", rig)
    out = {}
    try:
        it.start()
        it.send("POSITION_OPENED")
        out["returned"] = True
        out["states"] = sorted(it.current_state_ids)
        out["laps"] = rig.calls.count("S:attach_fallback_sl")
        out["status"] = it.status
    except Exception as e:
        out["returned"] = True
        out["exception"] = f"{type(e).__name__}: {str(e)[:140]}"
        out["laps"] = rig.calls.count("S:attach_fallback_sl")
    try: it.stop()
    except Exception: pass
    return out

if __name__ == "__main__":
    res = {"denied_receipt": denied_receipt(),
           "guard_raise": guard_raise(),
           "livelock_budget": livelock_budget()}
    print(json.dumps(res, indent=1))
    json.dump(res, open("c11_sync_parity.json", "w"), indent=1)
