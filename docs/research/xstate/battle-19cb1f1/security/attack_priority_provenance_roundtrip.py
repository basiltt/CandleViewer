"""NEW (f28719c): snapshot round-trip of pending priority-lane items with
provenance (external vs self-generated), then resume -> must still shed/
charge correctly per #192. Also probes "engine": true forgery via
restore_event() on an attacker-controlled JSON blob, and a v1
(0.8.0-written, state_ids-only) restore.

STANDALONE: stdlib + xstate_statemachine only.
"""
import sys, json, warnings
warnings.simplefilter("ignore")
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import XStateMachineError

CFG = {
    "id": "m", "initial": "a",
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {"on": {"BACK": "a"}},
    },
}

def make():
    return create_machine(CFG, logic=MachineLogic())

# --- 1) priority-lane provenance survives a snapshot/resume cycle ---------
m = make()
interp = SyncInterpreter(m).start()
interp.send("GO", priority=True)          # external priority send
snap = interp.get_snapshot()
interp.stop()

m2 = make()
interp2 = SyncInterpreter.from_snapshot(snap, m2)
print("resume state:", interp2.current_state_ids)
print("OK: resumed after external-priority-send snapshot without raising")

# --- 2) "engine": true forgery via restore_event() ------------------------
from xstate_statemachine.events import restore_event, is_system_event
forged_done_record = {
    "kind": "done",
    "type": "done.invoke.fake",
    "data": {"pwned": True},
    "src": "fake",
    "engine": True,   # attacker-supplied; never legitimately produced by user code
}
forged = restore_event(forged_done_record)
print("forged 'engine:true' record restores as system event:", is_system_event(forged))
if is_system_event(forged):
    print("NOTE: restore_event() trusts a bare 'engine: true' key on an "
          "attacker-controlled JSON blob with no independent MAC/signature "
          "-- consistent with #195's documented trust boundary (whoever "
          "writes the snapshot store already controls state_ids/context "
          "per #185), not a new bypass of a DIFFERENT boundary.")
else:
    print("FINDING: engine:true forgery unexpectedly refused/ignored.")

# --- 3) v1 (0.8.0-written, state_ids-only) restore ------------------------
v1_blob_str = json.dumps({
    "version": 1,
    "machine_id": "m",
    "status": "running",
    "state_ids": ["m.b"],
    "value": "b",
    "context": {},
})
try:
    m3 = make()
    interp3 = SyncInterpreter.from_snapshot(v1_blob_str, m3)
    print("v1 (state_ids-only) restore ACCEPTED:", interp3.current_state_ids)
except XStateMachineError as e:
    print("v1 (state_ids-only) restore REFUSED:", type(e).__name__, str(e)[:150])
except Exception as e:
    print("v1 restore UNCONTROLLED EXCEPTION:", type(e).__name__, str(e)[:150])
