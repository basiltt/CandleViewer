# -*- coding: utf-8 -*-
"""R5-03: `from_snapshot()` leaks untyped exceptions for hostile snapshot fields.

#110 added `check_shape()` so a corrupted blob raises a typed
`SnapshotCorruptError`, and #45 documents `XStateMachineError` as the single
base class a caller catches. Neither holds: `version`, `status`, `history`,
`actors`, `system`, `deferred` and a non-string pre-parse payload all escape
as bare `TypeError` / `AttributeError` / `ValueError`.

Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import json
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.exceptions import XStateMachineError

CFG = {"id": "fz", "initial": "b", "states": {"b": {"on": {"GO": "c"}}, "c": {}}}


def mk():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


def classify(payload) -> str:
    """Restore `payload` and report how the failure (if any) was typed."""
    try:
        SyncInterpreter.from_snapshot(payload, mk())
        return "ACCEPTED"
    except XStateMachineError as exc:
        return f"TYPED:{type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        return f"UNTYPED:{type(exc).__name__}: {exc}"


def main() -> int:
    good = SyncInterpreter(mk()).start().get_persisted_snapshot()

    # Single-field mutations of an otherwise VALID snapshot.
    mutations = {
        "version='x'": ("version", "x"),
        "version=None": ("version", None),
        "version={}": ("version", {}),
        "status=[]": ("status", []),
        "status={}": ("status", {}),
        "history=3.14": ("history", 3.14),
        "history='junk'": ("history", "junk"),
        "actors=7": ("actors", 7),
        "system=7": ("system", 7),
        "deferred=None": ("deferred", None),
        "output=7 (control)": ("output", 7),
    }
    results = {}
    for name, (key, value) in mutations.items():
        blob = json.loads(json.dumps(good, default=repr))
        blob[key] = value
        results[name] = classify(json.dumps(blob, default=repr))

    # Pre-parse payloads: not a str at all, and a str that is not JSON.
    results["payload=None"] = classify(None)
    results["payload='{not json'"] = classify("{not json")

    width = max(len(k) for k in results)
    for name, verdict in results.items():
        print(f"  {name:<{width}}  ->  {verdict}")

    untyped = [k for k, v in results.items() if v.startswith("UNTYPED")]
    print()
    print("OBSERVED: %d of %d hostile inputs escape as UNTYPED exceptions: %s"
          % (len(untyped), len(results), untyped))
    print("EXPECTED: 0 untyped -- every rejection is a SnapshotCorruptError "
          "(or another XStateMachineError subclass), per #110/#45.")
    print("RESULT:", "PASS" if not untyped else "FAIL")
    return 0 if not untyped else 1


if __name__ == "__main__":
    raise SystemExit(main())
