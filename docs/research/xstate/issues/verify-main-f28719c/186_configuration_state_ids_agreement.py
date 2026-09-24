# -*- coding: utf-8 -*-
"""Verify #186 on f28719c: configuration<->state_ids agreement is enforced
both ways (SnapshotCorruptError on mismatch), for both engines.
Standalone (stdlib + xstate_statemachine only).
"""
import asyncio
import json
import sys

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    create_machine,
    SnapshotCorruptError,
)

CFG = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"NEXT": "b"}}, "b": {}},
}


def legal_snapshot():
    s = SyncInterpreter(create_machine(CFG)).start()
    return json.loads(s.get_snapshot())


def check_engine(engine_name: str) -> dict:
    base = legal_snapshot()
    results = {}

    # Case 1: configuration=[] with non-empty state_ids -> refused
    snap1 = dict(base)
    snap1["configuration"] = []
    results["empty_configuration_refused"] = _expect_refused(engine_name, snap1)

    # Case 2: configuration names a disjoint leaf vs state_ids -> refused
    snap2 = dict(base)
    snap2["configuration"] = ["m", "m.b"]
    # state_ids stays ['m', 'm.a']
    results["contradicting_configuration_refused"] = _expect_refused(engine_name, snap2)

    # Case 3: legal blob (regression guard) -> accepted
    snap3 = dict(base)
    results["legal_blob_accepted"] = _expect_accepted(engine_name, snap3)

    return results


def _expect_refused(engine_name: str, snap: dict) -> bool:
    snap_str = json.dumps(snap)
    try:
        if engine_name == "sync":
            SyncInterpreter.from_snapshot(snap_str, create_machine(CFG))
        else:
            asyncio.run(_async_from_snapshot(snap_str))
        return False
    except SnapshotCorruptError:
        return True
    except Exception:
        return False


def _expect_accepted(engine_name: str, snap: dict) -> bool:
    snap_str = json.dumps(snap)
    try:
        if engine_name == "sync":
            SyncInterpreter.from_snapshot(snap_str, create_machine(CFG))
        else:
            asyncio.run(_async_from_snapshot(snap_str))
        return True
    except Exception:
        return False


async def _async_from_snapshot(snap_str: str):
    it = Interpreter.from_snapshot(snap_str, create_machine(CFG))
    return it


def main() -> int:
    all_ok = True
    for engine_name in ("sync", "async"):
        r = check_engine(engine_name)
        print(engine_name, r)
        if not all(r.values()):
            all_ok = False
    print("VERDICT:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
