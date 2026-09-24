# -*- coding: utf-8 -*-
"""Does the sync engine's 2-lap stop mean 'bounded' or 'parked mid-chain'?

Send an unrelated event afterwards: if the re-arm cycle resumes, the sync
engine merely defers the tail rather than cutting it.
"""
from __future__ import annotations
import json, logging
from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

logging.disable(logging.CRITICAL)

CFG = {
    "id": "m", "initial": "idle", "maxIterations": 20,
    "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "strictTargets": True, "strict": True, "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#m.arm"}}},
        "arm": {"invoke": {"id": "s", "src": "svc",
                           "onDone": {"target": "#m.done",
                                      "actions": ["boom"]},
                           "onError": {"target": "#m.err"}},
                "on": {"NUDGE": {"actions": []}}},
        "done": {"type": "final"}, "err": {"type": "final"},
    },
}

calls = []


def boom(i, c, e, a):
    raise RuntimeError("boom")


def svc(i, c, e):
    calls.append(1); return {"ok": True}


m = create_machine(CFG, logic=MachineLogic(
    actions={"boom": boom}, services={"svc": svc}, strict=True))
i = SyncInterpreter(m, clock=SimulatedClock())
i.start()
i.send("GO")
after_go = len(calls)
laps = [after_go]
for n in range(6):
    try:
        i.send("NUDGE")
    except Exception as e:
        laps.append(repr(e)); break
    laps.append(len(calls))
out = {"svc_after_GO": after_go, "svc_after_each_NUDGE": laps,
       "total_svc_calls": len(calls), "states": sorted(i.current_state_ids),
       "status": i.status, "last_error": repr(i.last_error)}
print(json.dumps(out), flush=True)
json.dump(out, open("y7_syncquiesce.json", "w"), indent=1)
i.stop()
