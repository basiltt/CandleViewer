# -*- coding: utf-8 -*-
"""Verify #186 on main @ 6db65d8.

A `configuration` that contradicts `state_ids` must be refused
(SnapshotCorruptError). Matrix: {Interpreter, SyncInterpreter} x
{configuration=[], configuration names disjoint leaf}. Regression guard:
legal blob with matching configuration/state_ids still restores.
"""
import asyncio
import json

from xstate_statemachine import Interpreter, SyncInterpreter, create_machine
from xstate_statemachine.exceptions import SnapshotCorruptError

A = {"id": "m", "initial": "a", "context": {"n": 0}, "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


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
        SyncInterpreter.from_snapshot(json.dumps(blob), create_machine(json.loads(json.dumps(A))))
        return "ACCEPTED"
    except SnapshotCorruptError:
        return "SnapshotCorruptError"
    except Exception as e:
        return type(e).__name__


async def attempt_async(blob):
    try:
        Interpreter.from_snapshot(json.dumps(blob), create_machine(json.loads(json.dumps(A))))
        return "ACCEPTED"
    except SnapshotCorruptError:
        return "SnapshotCorruptError"
    except Exception as e:
        return type(e).__name__


def main() -> int:
    base_sync = snap_sync()
    base_async = asyncio.run(snap_async())

    cells = {}
    for engine_name, base, attempt in (
        ("SyncInterpreter", base_sync, attempt_sync),
        ("Interpreter", base_async, lambda b: asyncio.run(attempt_async(b))),
    ):
        c_empty = dict(base)
        c_empty["configuration"] = []
        cells[(engine_name, "configuration=[]")] = attempt(c_empty)

        c_disjoint = dict(base)
        c_disjoint["configuration"] = ["m", "m.b"]  # contradicts state_ids ['m','m.a']
        cells[(engine_name, "configuration=disjoint")] = attempt(c_disjoint)

        c_legal = dict(base)  # regression guard: unmodified, must still accept
        cells[(engine_name, "configuration=legal(regression)")] = attempt(c_legal)

    print("cell table:")
    ok = True
    for k, v in cells.items():
        print("  %-45s %s" % (str(k), v))
        if k[1] in ("configuration=[]", "configuration=disjoint") and v != "SnapshotCorruptError":
            ok = False
        if k[1] == "configuration=legal(regression)" and v != "ACCEPTED":
            ok = False

    print()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
