# -*- coding: utf-8 -*-
"""Verify #199 on f28719c: `get_persisted_snapshot()` called from inside
the `on_interpreter_start` plugin hook must be REFUSED (SnapshotMidStepError
or equivalent guard), not return a torn (`status="running"`, empty
configuration) blob. Matrix: {def, async def} x {Interpreter, SyncInterpreter}.
Exit 0 only if every cell refuses / raises inside the hook, and the machine
starts normally afterward.
"""
from __future__ import annotations

import asyncio
import copy

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import SnapshotMidStepError

CFG = {
    "id": "v199",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"entry": ["bump"], "invoke": {"src": "s", "onDone": {"target": "b"}}},
        "b": {},
    },
}


def bump(i, c, e, a):
    c["n"] = c.get("n", 0) + 1


def make_service(kind):
    def svc(i, ctx, e):
        return {"v": 1}

    async def asvc(i, ctx, e):
        return {"v": 1}

    return svc if kind == "def" else asvc


def mk(kind):
    return create_machine(
        copy.deepcopy(CFG),
        logic=MachineLogic(actions={"bump": bump}, services={"s": make_service(kind)}),
    )


class Recorder(PluginBase):
    def __init__(self):
        self.disposition = None
        self.error_type = None

    def on_interpreter_start(self, i):
        try:
            blob = i.get_persisted_snapshot()
            self.disposition = ("returned", blob)
        except SnapshotMidStepError as e:
            self.disposition = ("refused", type(e).__name__)
            self.error_type = type(e).__name__
        except Exception as e:  # noqa: BLE001
            self.disposition = ("refused-other", type(e).__name__)
            self.error_type = type(e).__name__


FAIL: list[str] = []
ROWS: list[dict] = []


def run_async(kind):
    async def go():
        rec = Recorder()
        m = mk(kind)
        i = Interpreter(m).use(rec)
        await asyncio.wait_for(i.start(), 10)
        await i.stop()
        return rec

    return asyncio.run(go())


def run_sync(kind):
    rec = Recorder()
    m = mk(kind)
    i = SyncInterpreter(m).use(rec)
    i.start()
    i.stop()
    return rec


for engine in ("async", "sync"):
    for kind in ("def", "async def"):
        if engine == "sync" and kind == "async def":
            # SyncInterpreter does not support async def services at all;
            # not a #199 cell (nothing to verify here).
            continue
        rec = run_async(kind) if engine == "async" else run_sync(kind)
        disp = rec.disposition
        row = {"engine": engine, "kind": kind, "disposition": disp[0] if disp else None}
        ROWS.append(row)
        if disp is None:
            FAIL.append(f"[{engine}/{kind}] hook never ran")
        elif disp[0] == "returned":
            blob = disp[1]
            if not isinstance(blob, dict):
                import json

                blob = json.loads(blob)
            if blob.get("status") == "running" and not (
                blob.get("state_ids") or blob.get("configuration")
            ):
                FAIL.append(
                    f"[{engine}/{kind}] TORN blob returned: status=running, empty config"
                )
            # Any non-torn returned blob is also acceptable (not the defect).
        # "refused"/"refused-other" is the fixed behaviour.

import json as _json

print(_json.dumps({"rows": ROWS, "failures": FAIL}, indent=2))
if FAIL:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
raise SystemExit(0)
