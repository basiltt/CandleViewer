# -*- coding: utf-8 -*-
"""The sync engine STOPS the naked<->verifying cycle at ~500 laps where the
async engine runs for ever. Is the trip observable, and is the resulting
configuration legal? (#112 says a settle trip must be both.)"""
import json, cvlib
from cvlib import Rig
from xstate_statemachine import SyncInterpreter
from xstate_statemachine.clock import SimulatedClock
from c11_sync_parity import sync_logic

rig = Rig(guard_values={"exchange_reports_sl": False})
cfg = cvlib.load("B8")
m = cvlib.create_machine(json.loads(json.dumps(cfg)), logic=sync_logic(cfg, rig),
                         strict_targets=True)
plug = cvlib.TraceP()
it = SyncInterpreter(m, clock=SimulatedClock()); it.use(plug)
it.start()
r = it.send("POSITION_OPENED", wait=True)
out = {"laps": rig.calls.count("S:attach_fallback_sl"),
       "receipt": {"changed": r.changed, "deferred": r.deferred,
                   "denied": r.denied,
                   "error": type(r.error).__name__ if r.error else None,
                   "error_msg": str(r.error)[:180] if r.error else None},
       "status": it.status,
       "last_transition_ok": getattr(it, "last_transition_ok", None),
       "last_error": repr(getattr(it, "last_error", None))[:160],
       "interp_error": repr(getattr(it, "error", None))[:160],
       "states": sorted(it.current_state_ids),
       "dropped": plug.dropped[:4],
       "critical_alerts": (it.context.get("_trace") or []).count("raise_critical_alert")}
# legality: exactly one leaf per region
ids = sorted(it.current_state_ids)
out["leaves_sl"] = len([i for i in ids if ".sl." in i])
out["leaves_watchdog"] = len([i for i in ids if ".watchdog." in i])
# still responsive?
r2 = it.send("POSITION_FLAT", wait=True)
out["after_POSITION_FLAT"] = sorted(it.current_state_ids)
it.stop()
print(json.dumps(out, indent=1))
json.dump(out, open("repro/f9_sync_budget_signal.json", "w"), indent=1)
