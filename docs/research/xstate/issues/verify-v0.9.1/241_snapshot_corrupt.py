"""Standalone verify #241: malformed chain_trips/last_chain_error fields in a
snapshot raise SnapshotCorruptError (via from_snapshot), not a bare
ValueError/TypeError. Numeric-string chain_trips is accepted."""
import json
from xstate_statemachine import create_machine, Interpreter
from xstate_statemachine.exceptions import SnapshotCorruptError

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


def bad_cases():
    return [
        ("chain_trips=NaN-string", {"chain_trips": "NaN"}),
        ("chain_trips=list", {"chain_trips": [1]}),
        ("chain_trips=dict", {"chain_trips": {}}),
        ("chain_trips=bool", {"chain_trips": True}),
        ("chain_trips=negative", {"chain_trips": -1}),
        ("last_chain_error=list", {"last_chain_error": [1, 2]}),
        ("last_chain_error=dict", {"last_chain_error": {}}),
        ("last_chain_error=bool", {"last_chain_error": True}),
    ]


def main():
    machine = create_machine(CFG)
    interp = Interpreter(machine)
    base_snap = json.loads(interp.get_snapshot())

    fails = []
    for label, patch in bad_cases():
        snap = dict(base_snap)
        snap.update(patch)
        try:
            Interpreter.from_snapshot(json.dumps(snap), machine)
        except SnapshotCorruptError:
            print(f"OK {label}: SnapshotCorruptError")
        except Exception as e:
            fails.append((label, type(e).__name__, str(e)))
            print(f"FAIL {label}: raised {type(e).__name__} not SnapshotCorruptError")
        else:
            fails.append((label, "no-exception", ""))
            print(f"FAIL {label}: no exception raised")

    # numeric string accepted
    snap = dict(base_snap)
    snap["chain_trips"] = "3"
    restored = Interpreter.from_snapshot(json.dumps(snap), machine)
    assert restored.chain_trips == 3, restored.chain_trips
    print("OK numeric-string chain_trips accepted -> 3")

    if fails:
        print("FAILURES:", fails)
        raise SystemExit(1)
    print("PASS #241")


if __name__ == "__main__":
    main()
