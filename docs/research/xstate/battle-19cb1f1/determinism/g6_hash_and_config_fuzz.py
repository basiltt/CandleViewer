"""G6 -- null/absent machine_hash + configuration/state_ids disagreement
fuzz (targets R7-06/#185 and R7-09/#186). Property-style sweep over many
mutated snapshot blobs at versions 1 and 2."""
from __future__ import annotations
import json, logging, random, sys
logging.disable(logging.CRITICAL)
LIB = "<workspace>/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine  # noqa: E402
from xstate_statemachine.exceptions import SnapshotDriftError, SnapshotCorruptError  # noqa: E402

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {}}}


def base_snapshot(machine):
    interp = SyncInterpreter(machine)
    interp.start()
    snap = interp.get_persisted_snapshot()
    interp.stop()
    return snap


def try_restore(machine, snap):
    try:
        SyncInterpreter.from_snapshot(json.dumps(snap), machine=machine)
        return "ACCEPTED"
    except SnapshotDriftError as e:
        return "DRIFT_REFUSED:" + str(e)[:80]
    except SnapshotCorruptError as e:
        return "CORRUPT_REFUSED:" + str(e)[:80]
    except Exception as e:
        return "OTHER:" + type(e).__name__ + ":" + str(e)[:80]


def main():
    machine = create_machine(CFG, logic=MachineLogic())
    snap = base_snapshot(machine)
    assert snap.get("version", 0) >= 1, snap.get("version")

    rnd = random.Random(1234)
    n = 300
    null_hash_refused = 0
    absent_hash_refused = 0
    config_mismatch_refused = 0
    other_unexpected = []

    for i in range(n):
        s = json.loads(json.dumps(snap))  # deep copy
        mode = i % 3
        if mode == 0:
            s["machine_hash"] = None
            r = try_restore(machine, s)
            if r.startswith("DRIFT_REFUSED") or r.startswith("CORRUPT_REFUSED"):
                null_hash_refused += 1
            else:
                other_unexpected.append(("null_hash", r))
        elif mode == 1:
            s.pop("machine_hash", None)
            r = try_restore(machine, s)
            if r.startswith("DRIFT_REFUSED") or r.startswith("CORRUPT_REFUSED"):
                absent_hash_refused += 1
            else:
                other_unexpected.append(("absent_hash", r))
        else:
            # contradict configuration vs state_ids
            if "configuration" in s:
                s["configuration"] = ["m.__bogus__"]
            elif "state_ids" in s:
                s["state_ids"] = ["m.__bogus__"]
            else:
                continue
            r = try_restore(machine, s)
            if r.startswith("CORRUPT_REFUSED") or r.startswith("DRIFT_REFUSED"):
                config_mismatch_refused += 1
            else:
                other_unexpected.append(("config_mismatch", r))

    print("keys in base snapshot:", sorted(snap.keys()))
    print(f"null machine_hash refused (drift): {null_hash_refused}/100")
    print(f"absent machine_hash refused (drift): {absent_hash_refused}/100")
    print(f"config/state_ids mismatch refused (corrupt): {config_mismatch_refused}/{sum(1 for i in range(n) if i%3==2)}")
    print("unexpected outcomes (should be empty):", other_unexpected[:10], "..." if len(other_unexpected) > 10 else "")


if __name__ == "__main__":
    main()
