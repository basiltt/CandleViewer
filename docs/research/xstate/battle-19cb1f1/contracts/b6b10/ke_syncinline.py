# -*- coding: utf-8 -*-
"""LD-INLINE on SyncInterpreter, where every service is a plain callable.

Same two cases as kc_inline_svc.py.  The sync engine is the reference the
#116 inline path was built to match, so its answer decides whether the
async `def` lane is a divergence or the intended shared behaviour.
"""
from __future__ import annotations
import json, sys
from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

STYLE = "sync"
CALLS = []

def chart(case):
    sub = {"entry": ["bump"],
           "invoke": {"id": "kid", "src": "submit_child",
                      "onDone": {"target": "#m.armed"},
                      "onError": {"target": "#m.armed"}}}
    if case == "A":
        sub["always"] = [{"target": "#m.armed", "guard": "roll_forward"}]
    return {"id": "m", "initial": "armed",
            "actionErrorPolicy": "rollback", "onUnhandled": "defer",
            "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
            "context": {"n": 0},
            "states": {"armed": {"on": {"GO": {"target": "#m.submitting"}}},
                       "submitting": sub}}


def logic(case):
    def bump(i, ctx, e, ad):
        if case == "B":
            raise RuntimeError("entry action failed")
        ctx["n"] = ctx.get("n", 0) + 1

    def svc_sync(i, ctx, e):
        CALLS.append("submit_child")
        return {"ok": True}

    return MachineLogic(
        actions={"bump": bump},
        guards={"roll_forward": lambda ctx, e: True},
        services={"submit_child": svc_sync},
        strict=True)



def run(case):
    CALLS.clear()
    m = create_machine(chart(case), logic=logic(case))
    i = SyncInterpreter(m, clock=SimulatedClock())
    i.start()
    try:
        i.send("GO")
    except Exception as e:
        print("  send raised:", repr(e))
    out = {"case": case, "engine": "sync",
           "states": sorted(i.current_state_ids),
           "context": dict(i.context), "service_calls": list(CALLS)}
    try:
        i.stop()
    except Exception:
        pass
    return out


rows = []
for case in ("A", "B"):
    r = run(case)
    rows.append(r)
    ok = r["service_calls"] == []
    print(("PASS " if ok else "FAIL ")
          + "LD-INLINE/case %s [sync engine] submit_child never invoked" % case
          + "  | " + json.dumps(r), flush=True)
import pathlib
pathlib.Path("ke_syncinline.json").write_text(json.dumps(rows, indent=1),
                                              encoding="utf-8")
