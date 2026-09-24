"""D5-semantics-4 repro: `from_snapshot()` leaks UNTYPED exceptions for some
corrupt blobs. #110 promises a typed `SnapshotCorruptError`; `check_shape()`
validates `configuration`/`state_ids`/`context` but not `status`, `history` or
`system`, so a wrong type in those slots escapes as a bare TypeError /
AttributeError from deep inside the restore.

An adopter writing `except XStateMachineError:` around a restore -- exactly
what the typed-error contract invites -- does not catch these.
"""
import json, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import (MachineLogic, SyncInterpreter,
                                 XStateMachineError, create_machine)

CFG = {"id": "f", "initial": "a", "context": {"n": 1},
       "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}}
mk = lambda: create_machine(CFG, logic=MachineLogic())
s = SyncInterpreter(mk()).start(); s.send("GO")
base = s.get_persisted_snapshot(); s.stop()

CASES = [("status", []), ("status", {}), ("status", 0),
         ("history", True), ("history", "x"), ("history", 5),
         ("system", "x"), ("system", 7), ("system", [])]

print(f"{'field':10} {'poison':10} {'outcome'}")
leaks = 0
for field, val in CASES:
    b = json.loads(json.dumps(base)); b[field] = val
    try:
        r = SyncInterpreter.from_snapshot(json.dumps(b), mk()); r.start(); r.stop()
        out = "ACCEPTED"
    except XStateMachineError as e:
        out = f"typed  {type(e).__name__}"
    except Exception as e:
        out = f"UNTYPED {type(e).__name__}: {str(e)[:50]}"
        leaks += 1
    print(f"{field:10} {str(val)[:9]:10} {out}")
print(f"\n{leaks}/{len(CASES)} corrupt blobs escaped the XStateMachineError hierarchy.")
