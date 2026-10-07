"""#230 plugins= restore-hook reachability (closes D11-security-4) +
#227 strict/schemas on restored scheduled_sends (persistence-strict bypass
check) + #233 sync priority lane on restore.
STANDALONE: stdlib + xstate_statemachine only."""
import sys, json
sys.path.insert(0, "<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter, PluginBase

# --- Part A: #230 plugins= reaches on_invalid_event for a restore refusal ---
cfg = {
    "id": "m", "initial": "w", "strict": True,
    "states": {"w": {"on": {"GO": "done_state"}}, "done_state": {"type": "final"}},
}
m = create_machine(cfg, logic=MachineLogic())
interp = SyncInterpreter(m).start()
snap = interp.get_persisted_snapshot()
snap["pending_events"] = [{"type": "UNDECLARED", "payload": {}}]
snap_json = json.dumps(snap)


class Spy(PluginBase):
    def __init__(self):
        self.invalid = []

    def on_invalid_event(self, interpreter, exc, raw):
        self.invalid.append((type(exc).__name__, raw))


spy = Spy()
restored = SyncInterpreter.from_snapshot(snap_json, m, plugins=[spy])
print("A) last_error after restore:", restored.last_error)
print("A) on_invalid_event fired via plugins= (spy.invalid):", spy.invalid)
print("A) D11-security-4 FIXED (plugins= reaches hook before refusal happens):",
      spy.invalid != [])

# Old .use()-after-the-fact path: still structurally too late (documented gap,
# now with a documented workaround).
spy2 = Spy()
restored2 = SyncInterpreter.from_snapshot(snap_json, m)
restored2.use(spy2)
print("A) old .use()-after path still misses it (unchanged):", spy2.invalid == [])
