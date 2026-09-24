"""
NEW attack (round-9-targeted): #205's `from_snapshot(minimum_version=,
expected_machine_hash=)` remedy for R9-05 (v0/absent-version downgrade
bypasses drift check). Confirm:
  (a) a version-0 (or absent-version) snapshot is refused when the caller
      passes `minimum_version=1` (SnapshotVersionError)
  (b) a snapshot whose `machine_hash` mismatches the caller's own
      `expected_machine_hash` is refused regardless of version
      (SnapshotDriftError), including when machine_hash is ABSENT

Both engines. Standalone.
"""
import json
import sys

from xstate_statemachine import create_machine, SyncInterpreter, Interpreter
from xstate_statemachine.machine_logic import MachineLogic
from xstate_statemachine.exceptions import (
    SnapshotVersionError,
    SnapshotDriftError,
)

CONFIG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}


def base_snapshot(machine):
    interp = SyncInterpreter(machine, MachineLogic()).start()
    interp.send("GO")
    snap = json.loads(interp.get_snapshot())
    interp.stop()
    return snap


def main():
    machine = create_machine(CONFIG)
    snap = base_snapshot(machine)
    real_hash = snap.get("machine_hash")

    results = {}

    # (a) version downgrade
    v0 = dict(snap)
    v0["version"] = 0
    try:
        SyncInterpreter.from_snapshot(json.dumps(v0), machine, minimum_version=1)
        results["v0_downgrade_refused"] = False
    except SnapshotVersionError:
        results["v0_downgrade_refused"] = True
    except Exception as e:
        results["v0_downgrade_refused"] = f"unexpected {type(e).__name__}"

    v_absent = dict(snap)
    v_absent.pop("version", None)
    try:
        SyncInterpreter.from_snapshot(json.dumps(v_absent), machine, minimum_version=1)
        results["v_absent_refused"] = False
    except SnapshotVersionError:
        results["v_absent_refused"] = True
    except Exception as e:
        results["v_absent_refused"] = f"unexpected {type(e).__name__}"

    # (b) hash mismatch / absent, regardless of version
    bad_hash = dict(snap)
    bad_hash["machine_hash"] = "not-the-real-hash"
    try:
        SyncInterpreter.from_snapshot(
            json.dumps(bad_hash), machine, expected_machine_hash=real_hash
        )
        results["bad_hash_refused"] = False
    except SnapshotDriftError:
        results["bad_hash_refused"] = True
    except Exception as e:
        results["bad_hash_refused"] = f"unexpected {type(e).__name__}"

    no_hash = dict(snap)
    no_hash.pop("machine_hash", None)
    try:
        SyncInterpreter.from_snapshot(
            json.dumps(no_hash), machine, expected_machine_hash=real_hash
        )
        results["absent_hash_refused_when_expected"] = False
    except SnapshotDriftError:
        results["absent_hash_refused_when_expected"] = True
    except Exception as e:
        results["absent_hash_refused_when_expected"] = f"unexpected {type(e).__name__}"

    # control: matching hash + version must be accepted
    try:
        i2 = SyncInterpreter.from_snapshot(
            json.dumps(snap), machine, minimum_version=1, expected_machine_hash=real_hash
        )
        results["legitimate_snapshot_accepted"] = True
        i2.stop()
    except Exception as e:
        results["legitimate_snapshot_accepted"] = f"unexpected refusal {type(e).__name__}"

    print(json.dumps(results, indent=2))
    ok = all(v is True for v in results.values())
    print("VERDICT:", "PASS" if ok else "FAIL/see-detail")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
