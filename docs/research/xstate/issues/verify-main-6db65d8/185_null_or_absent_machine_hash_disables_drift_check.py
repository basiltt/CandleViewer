# -*- coding: utf-8 -*-
"""Verify #185 on main @ 6db65d8.

versioned (>=1) snapshot with null or absent machine_hash must be REFUSED
under verify_machine_hash=True (default). Matrix: {Interpreter, SyncInterpreter}
x {null, absent}. Also controls: honest hash accepted, wrong hash refused.
"""
import json

from xstate_statemachine import Interpreter, SyncInterpreter, create_machine
from xstate_statemachine.exceptions import SnapshotDriftError

A = {"id": "m", "initial": "a", "context": {"n": 0}, "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
B = {"id": "m", "initial": "a", "context": {"n": 0}, "states": {"a": {}, "b": {}, "c": {}}}


def snap_sync():
    i = SyncInterpreter(create_machine(json.loads(json.dumps(A))))
    i.start()
    b = i.get_persisted_snapshot()
    i.stop()
    return b


async def snap_async():
    i = Interpreter(create_machine(json.loads(json.dumps(A))))
    await i.start()
    b = i.get_persisted_snapshot()
    await i.stop()
    return b


def attempt_sync(blob):
    try:
        SyncInterpreter.from_snapshot(json.dumps(blob), create_machine(json.loads(json.dumps(B))))
        return "ACCEPTED"
    except SnapshotDriftError:
        return "SnapshotDriftError"
    except Exception as e:
        return type(e).__name__


async def attempt_async(blob):
    try:
        Interpreter.from_snapshot(json.dumps(blob), create_machine(json.loads(json.dumps(B))))
        return "ACCEPTED"
    except SnapshotDriftError:
        return "SnapshotDriftError"
    except Exception as e:
        return type(e).__name__


import asyncio


def main() -> int:
    cells = {}

    base_sync = snap_sync()
    base_async = asyncio.run(snap_async())

    for engine_name, base, attempt in (
        ("SyncInterpreter", base_sync, attempt_sync),
        ("Interpreter", base_async, lambda b: asyncio.run(attempt_async(b))),
    ):
        honest = dict(base)
        cells[(engine_name, "honest_hash_vs_diff_machine")] = attempt(honest)

        wrong = dict(base)
        wrong["machine_hash"] = "deadbeefdeadbeef"
        cells[(engine_name, "wrong_hash")] = attempt(wrong)

        null_hash = dict(base)
        null_hash["machine_hash"] = None
        cells[(engine_name, "null_hash")] = attempt(null_hash)

        absent = dict(base)
        absent.pop("machine_hash", None)
        cells[(engine_name, "absent_hash")] = attempt(absent)

    print("cell table:")
    ok = True
    for k, v in cells.items():
        print("  %-45s %s" % (str(k), v))
        if k[1] in ("wrong_hash", "null_hash", "absent_hash") and v != "SnapshotDriftError":
            ok = False
        if k[1] == "honest_hash_vs_diff_machine" and v != "SnapshotDriftError":
            ok = False

    print()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
