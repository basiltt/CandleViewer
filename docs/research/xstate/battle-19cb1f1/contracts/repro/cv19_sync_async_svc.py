# -*- coding: utf-8 -*-
"""STANDALONE. SyncInterpreter + an `async def` service: the invoking state is
entered and the machine parks there forever with no error, no hook, no warning.

stdlib + xstate_statemachine only.  Run from any cwd:
    python cv19_sync_async_svc.py
"""
from __future__ import annotations
import json
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.plugins import PluginBase

CFG = {
    "id": "ks", "initial": "clear",
    "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {},
    "states": {
        "clear": {"on": {"ENGAGE": {"target": "#ks.cancelling"}}},
        "cancelling": {"invoke": {"id": "cx", "src": "cancel_all",
                                  "onDone": {"target": "#ks.engaged"},
                                  "onError": {"target": "#ks.engaged"}}},
        "engaged": {"entry": ["mark"]},
    },
}


class Hooks(PluginBase):
    def __init__(self):
        self.seen = []
    def on_service_error(self, i, *a): self.seen.append(("service_error", repr(a[-1])))
    def on_error(self, i, e): self.seen.append(("error", repr(e)))
    def on_event_dropped(self, i, e, r): self.seen.append(("dropped", r))
    def on_transition_failed(self, i, *a): self.seen.append(("tfail", repr(a[-1])))


def run(kind):
    calls = []
    if kind == "async def":
        async def cancel_all(interp, ctx, evt):
            calls.append(1); return {"ok": True}
    else:
        def cancel_all(interp, ctx, evt):
            calls.append(1); return {"ok": True}

    def mark(i, c, e, a): pass

    m = create_machine(json.loads(json.dumps(CFG)),
                       logic=MachineLogic(actions={"mark": mark},
                                          services={"cancel_all": cancel_all},
                                          strict=True),
                       strict_targets=True)
    i = SyncInterpreter(m)
    h = Hooks(); i.use(h)
    i.start()
    exc = None
    try:
        i.send("ENGAGE")
    except Exception as e:
        exc = repr(e)
    for _ in range(5):
        try:
            i.tick()
        except AttributeError:
            break
        except Exception as e:
            exc = exc or repr(e)
    out = {"kind": kind, "states": sorted(i.current_state_ids),
           "status": i.status, "svc_calls": len(calls),
           "error": None if i.error is None else repr(i.error),
           "send_exc": exc, "hooks": h.seen}
    try:
        i.stop()
    except Exception:
        pass
    return out


if __name__ == "__main__":
    rows = [run("def"), run("async def")]
    for r in rows:
        print(json.dumps(r))
    bad = [r for r in rows
           if r["states"] == ["ks.cancelling"] and r["svc_calls"] == 0
           and r["error"] is None and r["send_exc"] is None and not r["hooks"]]
    print("\nREPRODUCED" if bad else "\nNOT REPRODUCED",
          "- silent park lanes:", [r["kind"] for r in bad])
