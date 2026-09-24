"""Re-run our carried restore-observability finding (on_invalid_event unreachable on restore path)
against de2da4e. STANDALONE: stdlib + xstate_statemachine only.
"""
import sys, json
sys.path.insert(0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter, PluginBase

cfg = {
    "id": "m", "initial": "w", "strict": True,
    "states": {"w": {"on": {"GO": "done_state"}}, "done_state": {"type": "final"}},
}
m = create_machine(cfg, logic=MachineLogic())
interp = SyncInterpreter(m).start()
snap = json.loads(interp.get_snapshot())
snap["pending_events"] = [{"type": "UNDECLARED", "payload": {}}]
snap = json.dumps(snap)


class Spy(PluginBase):
    def __init__(self):
        self.invalid = []

    def on_invalid_event(self, interpreter, exc, raw):
        self.invalid.append((exc, raw))


spy = Spy()
# The only place `use()` is reachable is on the returned interpreter --
# but _admit_restored runs INSIDE from_snapshot, before this line.
restored = SyncInterpreter.from_snapshot(snap, m)
restored.use(spy)
print("last_error after restore:", restored.last_error)
print("on_invalid_event fired during restore (spy.invalid):", spy.invalid)
reproduced = spy.invalid == [] and restored.last_error is not None
print("hook unreachable during restore (spy empty, last_error set):", reproduced)
print()
print("REPRODUCED:", reproduced)
sys.exit(1 if reproduced else 0)
