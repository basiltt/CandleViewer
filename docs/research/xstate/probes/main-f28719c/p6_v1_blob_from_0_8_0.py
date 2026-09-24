"""P6 (STANDALONE): does a v1 blob written by 0.8.0 still restore under #198?

0.8.0 shipped SNAPSHOT_VERSION = 1 and its writer DID record
`configuration` (base_interpreter.py:955 at tag v0.8.0), so the common case
survives. This probe pins the two shapes that matter:

  A) v1 + configuration + state_ids  -> must restore (0.8.0 writer output)
  B) v1 + state_ids only             -> now REFUSED (was accepted at 6db65d8)

Case B is the compatibility edge: any v1 blob whose `configuration` was
stripped (by a storage layer that drops unknown/duplicate keys, or a
hand-rolled writer) used to restore and no longer does. Exit 1 if A fails
or if B's change is present (report only).
"""
import json, sys
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic
from xstate_statemachine.exceptions import SnapshotCorruptError

CFG = {"id": "m", "initial": "a", "context": {"n": 1},
       "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


i = SyncInterpreter(build()).start()
blob = json.loads(json.dumps(i.get_persisted_snapshot()))
i.stop()

v1_full = dict(blob, version=1)
v1_ids_only = {k: v for k, v in v1_full.items() if k != "configuration"}

results = {}
for name, b in (("A: v1 + both fields", v1_full),
                ("B: v1 + state_ids only", v1_ids_only)):
    try:
        j = SyncInterpreter.from_snapshot(json.dumps(b), build())
        results[name] = f"restored {sorted(j.current_state_ids)}"
    except SnapshotCorruptError as exc:
        results[name] = f"REFUSED: {exc}"
    except Exception as exc:  # noqa: BLE001
        results[name] = f"{type(exc).__name__}: {exc}"

for k, v in results.items():
    print(f"{k} -> {v}")

a_ok = results["A: v1 + both fields"].startswith("restored")
b_refused = results["B: v1 + state_ids only"].startswith("REFUSED")
print("VERDICT:",
      ("A ok; " if a_ok else "A BROKEN; ") +
      ("B now refused (compat narrowing)" if b_refused else "B still restores"))
sys.exit(0 if (a_ok and not b_refused) else 1)
