# -*- coding: utf-8 -*-
"""Verify #110 on 3ed3099: from_snapshot() validates shape and raises a
typed SnapshotCorruptError for every malformed shape, instead of accepting
garbage or leaking a bare KeyError/AttributeError/TypeError.

Criteria (from issue body + CHANGELOG #110):
  1. Empty configuration with status="running" is REFUSED (not silently
     accepted as a healthy inert interpreter).
  2. status="zzz" (garbage) -> typed SnapshotCorruptError.
  3. status=5 (wrong type) -> typed SnapshotCorruptError.
  4. context=42 (wrong type, not a mapping) -> typed SnapshotCorruptError.
  5. pending_events=[{}] (event record missing 'type') -> typed error.
  6. pending_events=[None] (non-dict record) -> typed error.
  7. state_ids=[["m.a"]] (non-str element) -> typed error.
  8. missing required key (e.g. no 'status') -> typed error.
  9. configuration as a string instead of a list -> typed error.
 10. All of the above are subclasses of XStateMachineError (catchable by
     the documented `except XStateMachineError` contract).

Exits 0 iff all pass.
"""
from __future__ import annotations

import copy
import json

from xstate_statemachine import (
    SnapshotCorruptError,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)

CFG = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}},
}


def check(name: str, mutate) -> bool:
    machine = create_machine(CFG)
    i = SyncInterpreter(machine)
    i.start()
    snap = json.loads(i.get_snapshot())
    mutate(snap)
    try:
        SyncInterpreter.from_snapshot(
            json.dumps(snap, default=str), machine, verify_machine_hash=False
        )
        print(f"[{name}] FAIL: accepted with no error")
        return False
    except SnapshotCorruptError as exc:
        assert isinstance(exc, XStateMachineError)
        print(f"[{name}] OK: SnapshotCorruptError: {exc}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[{name}] FAIL: untyped {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    results = []

    def mut_empty(s):
        s.update({"configuration": [], "state_ids": []})

    results.append(check("empty_configuration_running", mut_empty))

    def mut_status_garbage(s):
        s["status"] = "zzz"

    results.append(check("status_garbage_str", mut_status_garbage))

    def mut_status_wrong_type(s):
        s["status"] = 5

    results.append(check("status_wrong_type", mut_status_wrong_type))

    def mut_context_wrong_type(s):
        s["context"] = 42

    results.append(check("context_wrong_type", mut_context_wrong_type))

    def mut_pending_events_missing_type(s):
        s["pending_events"] = [{}]

    results.append(check("pending_events_missing_type", mut_pending_events_missing_type))

    def mut_pending_events_none(s):
        s["pending_events"] = [None]

    results.append(check("pending_events_none_record", mut_pending_events_none))

    def mut_state_ids_nonstr(s):
        s["configuration"] = None
        s["state_ids"] = [["m.a"]]

    results.append(check("state_ids_non_str_element", mut_state_ids_nonstr))

    def mut_missing_status(s):
        del s["status"]

    results.append(check("missing_status_key", mut_missing_status))

    def mut_configuration_str(s):
        s["configuration"] = "m.a"

    results.append(check("configuration_as_string", mut_configuration_str))

    n_ok = sum(results)
    n_total = len(results)
    print(f"\n{n_ok}/{n_total} criteria passed")
    return 0 if n_ok == n_total else 1


if __name__ == "__main__":
    raise SystemExit(main())
