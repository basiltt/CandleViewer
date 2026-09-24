"""Verify #158 on cec108b: non-str event 'type' via the restore path.

Acceptance criteria (issue #158 + CHANGELOG "#158" bullet):
  A) A pending_events/deferred record with a non-str 'type' is rejected
     during from_snapshot() (check_shape) -- not silently accepted.
  B) restore_event() itself re-validates 'type' is a non-empty str
     (defense in depth per record, not just at check_shape time).
  C) A non-dict record in pending_events/deferred is rejected too.
  D) The rejection is a documented, typed exception (SnapshotCorruptError),
     not a bare TypeError/AttributeError/KeyError escaping the hierarchy.

Exits 0 only if all hold.
"""
from __future__ import annotations

import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import SnapshotCorruptError
from xstate_statemachine import events as events_mod

CFG = {
    "id": "rp",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}}, "b": {}},
}


def bump(interpreter, ctx, event, action_def):
    ctx["n"] += 1


def build():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


def base_blob(pending_record):
    return {
        "version": 2,
        "status": "running",
        "context": {"n": 0},
        "state_ids": ["rp.a"],
        "configuration": ["rp.a"],
        "history": {},
        "actors": {},
        "system": {},
        "pending_events": [pending_record],
        "deferred": [],
    }


def criterion_A_non_str_type() -> bool:
    blob = base_blob({"kind": "event", "type": 42})
    try:
        Interpreter.from_snapshot(json.dumps(blob), build(), clock=SimulatedClock())
        print("  [A] FAIL: non-str type accepted by from_snapshot")
        return False
    except SnapshotCorruptError:
        print("  [A] PASS: non-str type rejected by from_snapshot")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [A] FAIL: wrong exception type {type(e).__name__}: {e}")
        return False


def criterion_B_restore_event_direct() -> bool:
    try:
        events_mod.restore_event({"kind": "event", "type": 42})
        print("  [B] FAIL: restore_event() accepted a non-str type directly")
        return False
    except SnapshotCorruptError:
        print("  [B] PASS: restore_event() rejects non-str type directly")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [B] FAIL: wrong exception type {type(e).__name__}: {e}")
        return False


def criterion_C_non_dict_record() -> bool:
    blob = base_blob("not-a-dict")
    try:
        Interpreter.from_snapshot(json.dumps(blob), build(), clock=SimulatedClock())
        print("  [C] FAIL: non-dict pending record accepted")
        return False
    except SnapshotCorruptError:
        print("  [C] PASS: non-dict pending record rejected")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [C] FAIL: wrong exception type {type(e).__name__}: {e}")
        return False


def criterion_D_empty_str_type() -> bool:
    blob = base_blob({"kind": "event", "type": ""})
    try:
        Interpreter.from_snapshot(json.dumps(blob), build(), clock=SimulatedClock())
        print("  [D] FAIL: empty-string type accepted")
        return False
    except SnapshotCorruptError:
        print("  [D] PASS: empty-string type rejected")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [D] FAIL: wrong exception type {type(e).__name__}: {e}")
        return False


def main() -> int:
    results = [
        criterion_A_non_str_type(),
        criterion_B_restore_event_direct(),
        criterion_C_non_dict_record(),
        criterion_D_empty_str_type(),
    ]
    ok = all(results)
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


sys.exit(main())
