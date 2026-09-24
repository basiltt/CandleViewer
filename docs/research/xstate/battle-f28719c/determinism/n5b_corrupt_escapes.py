"""N5b -- minimal repro for the N5/F1 untyped escapes.

#110 promises a malformed snapshot raises `SnapshotCorruptError`. The fuzz
pass found 339/5000 mutations that escape the `XStateMachineError` hierarchy
entirely. An OMS restoring a checkpoint from Redis writes

    try:
        interp = Interpreter.from_snapshot(blob, machine)
    except XStateMachineError:
        ...rebuild from the event log...

and these escapes bypass that handler.

Each case below is a SINGLE, named, hand-written mutation -- no RNG -- so the
defect is reproducible verbatim.
"""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    MachineLogic,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)

CFG = {
    "id": "fz",
    "initial": "x",
    "context": {"n": 0},
    "states": {"x": {"on": {"GO": "y"}}, "y": {"on": {"GO": "x"}}},
}


def mk():
    return create_machine(CFG, logic=MachineLogic())


def base():
    i = SyncInterpreter(mk())
    i.start()
    i.send("GO")
    s = i.get_persisted_snapshot()
    i.stop()
    return s


# name -> function(snapshot_dict) -> mutated dict
CASES = {
    "version_is_str": lambda o: {**o, "version": "x"},
    "version_is_dict": lambda o: {**o, "version": {}},
    "version_is_None": lambda o: {**o, "version": None},
    "version_is_list": lambda o: {**o, "version": []},
    "status_is_dict": lambda o: {**o, "status": {}},
    "status_is_list": lambda o: {**o, "status": []},
    "history_is_float": lambda o: {**o, "history": 1.5},
    "pending_events_type_is_int": lambda o: {
        **o,
        "pending_events": [{"kind": "event", "type": 5, "payload": {}}],
    },
    "deferred_type_is_int": lambda o: {
        **o,
        "deferred": [{"kind": "event", "type": 5, "payload": {}}],
    },
}


def main():
    b = base()
    rows = []
    for name, fn in CASES.items():
        blob = json.dumps(fn(dict(b)), default=str)
        try:
            r = SyncInterpreter.from_snapshot(blob, mk())
            r.get_persisted_snapshot()
            outcome, typed, msg = "RESTORED-OK", None, ""
        except XStateMachineError as e:
            outcome, typed, msg = type(e).__name__, True, str(e)[:90]
        except Exception as e:  # noqa: BLE001
            outcome, typed, msg = type(e).__name__, False, str(e)[:90]
        rows.append(
            {
                "case": name,
                "outcome": outcome,
                "caught_by_XStateMachineError": typed,
                "msg": msg,
            }
        )
        flag = (
            "ESCAPE"
            if typed is False
            else ("ok" if typed else "restored")
        )
        print(f"  {name:28s} -> {outcome:20s} [{flag}]  {msg}")

    escapes = [r for r in rows if r["caught_by_XStateMachineError"] is False]
    print(f"\nuntyped escapes: {len(escapes)}/{len(rows)}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "n5b_corrupt_escapes.json"), "w") as f:
        json.dump(
            {"rows": rows, "untyped_escapes": len(escapes)},
            f,
            indent=2,
            default=str,
        )
    print("wrote out/n5b_corrupt_escapes.json")


if __name__ == "__main__":
    main()
