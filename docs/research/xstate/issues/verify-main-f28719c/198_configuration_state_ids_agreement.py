# -*- coding: utf-8 -*-
"""Verify #198 on f28719c: versioned (`version>=1`) running snapshots must
carry BOTH `configuration` and `state_ids`, non-empty, agreeing. Acceptance
criteria (from gh issue #198):
  1. version>=1 running snapshot with `state_ids` emptied but `configuration`
     present/legal -> refused (SnapshotCorruptError), not silently accepted.
  2. version>=1 running snapshot with `configuration` dropped (absent) but
     `state_ids` present/legal -> refused.
  3. A genuine, untampered version>=1 snapshot round-trips normally (no
     false positive).
  4. A v0 (no `version` key) snapshot carrying `state_ids` alone (no
     `configuration`) is still accepted (legacy shape unaffected).
Matrix: {def, async def} x {Interpreter, SyncInterpreter}.
Exit 0 only if ALL cells pass in ALL 4 criteria.
"""
from __future__ import annotations

import asyncio
import copy
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import SnapshotCorruptError

CFG = {
    "id": "v198",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"S": {"target": "b"}}},
        "b": {},
    },
}


def make_service(kind):
    def svc(i, ctx, e):
        return {"v": 1}

    async def asvc(i, ctx, e):
        return {"v": 1}

    return svc if kind == "def" else asvc


def mk(kind):
    return create_machine(
        copy.deepcopy(CFG), logic=MachineLogic(services={"s": make_service(kind)})
    )


FAIL: list[str] = []
ROWS: list[dict] = []


def get_snapshot_async(kind):
    async def run():
        i = Interpreter(mk(kind))
        await asyncio.wait_for(i.start(), 10)
        b = i.get_persisted_snapshot()
        await i.stop()
        return b if isinstance(b, dict) else json.loads(b)

    return asyncio.run(run())


def get_snapshot_sync(kind):
    i = SyncInterpreter(mk(kind))
    i.start()
    b = i.get_persisted_snapshot()
    i.stop()
    return b if isinstance(b, dict) else json.loads(b)


def try_restore(engine, kind, blob):
    cls = Interpreter if engine == "async" else SyncInterpreter
    payload = json.dumps(blob)
    try:
        if engine == "async":
            r = asyncio.run(_restore_async(cls, payload, mk(kind)))
        else:
            r = cls.from_snapshot(payload, mk(kind))
        return "ACCEPTED", sorted(getattr(r, "current_state_ids", []) or [])
    except SnapshotCorruptError as e:
        return "refused:SnapshotCorruptError", str(e)
    except Exception as e:  # noqa: BLE001
        return f"refused:{type(e).__name__}", str(e)


async def _restore_async(cls, payload, machine):
    r = cls.from_snapshot(payload, machine)
    return r


for engine in ("async", "sync"):
    for kind in ("def", "async def"):
        base = get_snapshot_async(kind) if engine == "async" else get_snapshot_sync(kind)
        assert base.get("state_ids") and base.get("configuration"), "genuine snapshot missing fields"
        version = base.get("version", 0)

        # Criterion 3: genuine round-trip must be ACCEPTED.
        disp, info = try_restore(engine, kind, base)
        ROWS.append({"crit": 3, "engine": engine, "kind": kind, "case": "genuine", "disp": disp})
        if disp != "ACCEPTED":
            FAIL.append(f"[{engine}/{kind}] genuine snapshot wrongly refused: {disp}")

        # Criterion 1: state_ids emptied, configuration intact -> refused.
        b1 = copy.deepcopy(base)
        b1["state_ids"] = []
        disp, info = try_restore(engine, kind, b1)
        ROWS.append({"crit": 1, "engine": engine, "kind": kind, "case": "state_ids emptied", "disp": disp})
        if disp == "ACCEPTED":
            FAIL.append(f"[{engine}/{kind}] state_ids emptied wrongly ACCEPTED")

        # Criterion 2: configuration dropped, state_ids intact -> refused.
        b2 = copy.deepcopy(base)
        b2.pop("configuration", None)
        disp, info = try_restore(engine, kind, b2)
        ROWS.append({"crit": 2, "engine": engine, "kind": kind, "case": "configuration dropped", "disp": disp})
        if disp == "ACCEPTED":
            FAIL.append(f"[{engine}/{kind}] configuration dropped wrongly ACCEPTED")

        # Criterion 4: legacy v0 state_ids-only payload still accepted.
        b3 = copy.deepcopy(base)
        b3.pop("configuration", None)
        b3.pop("version", None)
        disp, info = try_restore(engine, kind, b3)
        ROWS.append({"crit": 4, "engine": engine, "kind": kind, "case": "v0 state_ids-only", "disp": disp})
        if disp != "ACCEPTED":
            FAIL.append(f"[{engine}/{kind}] legacy v0 state_ids-only wrongly refused: {disp}")


print(json.dumps({"rows": ROWS, "failures": FAIL}, indent=2))
if FAIL:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
raise SystemExit(0)
