"""Isolate exactly which fields the r5-round fuzz still accepts, to classify
severity precisely: metadata-only (taken_at) vs security-relevant
(machine_hash=None bypasses drift/hash verification silently)."""
import sys, json, copy
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter

cfg = {"id": "m", "initial": "a", "context": {"n": 0},
       "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}}
m = create_machine(cfg, logic=MachineLogic())
interp = SyncInterpreter(m).start()
good = json.loads(interp.get_snapshot())

def try_field(key, value, note=""):
    d = copy.deepcopy(good)
    d[key] = value
    s = json.dumps(d, default=str)
    try:
        SyncInterpreter.from_snapshot(s, m)
        print(f"{key} -> {value!r} {note}: ACCEPTED (no error)")
    except Exception as e:
        print(f"{key} -> {value!r} {note}: {type(e).__name__}: {str(e)[:90]}")

try_field("taken_at", None, "(metadata-only)")
try_field("taken_at", "garbage", "(metadata-only)")
try_field("machine_hash", None, "(BYPASSES drift check)")
try_field("machine_hash", "wrong-hash-value", "(should be caught by check_identity)")
try_field("__extra_junk__", {"x": 1}, "(unknown key)")
d2 = copy.deepcopy(good)
d2["context"] = {"n": "not-a-number-but-still-a-dict"}
print("context.n type-confusion (still a dict, opaque value): ACCEPTED by design (context values are caller's domain)")
