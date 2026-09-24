# -*- coding: utf-8 -*-
"""Q1b -- MINIMAL: snapshot taken during the INITIAL entry pass of a
parallel machine is ACCEPTED by the write side and REFUSED by the read side.

`start()` enters region r0 then r1. A plugin's `on_action_execute` fires
inside r0's entry action, at which point r1 has no leaf yet. The write-side
guard (`_step_in_flight()` at the root, #169) does not consider `start()`
a step in flight, so `get_persisted_snapshot()` returns a blob whose
`configuration` covers only r0. The library's own `from_snapshot` then
raises `SnapshotCorruptError` on that blob: the writer produced a snapshot
its own reader calls malformed.

Both engines.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import (
    SnapshotMidStepError,
    XStateMachineError,
)
from xstate_statemachine.plugins import PluginBase

CFG = {
    "id": "pp",
    "type": "parallel",
    "context": {"n": 0},
    "states": {
        "r0": {
            "initial": "a",
            "states": {"a": {"entry": ["bump"], "on": {"GO": "b"}}, "b": {}},
        },
        "r1": {
            "initial": "a",
            "states": {"a": {"entry": ["bump"], "on": {"GO": "b"}}, "b": {}},
        },
    },
}


def build():
    def bump(interp, ctx, event, action_def=None):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return create_machine(
        json.loads(json.dumps(CFG)), logic=MachineLogic(actions={"bump": bump})
    )


class Snap(PluginBase):
    def __init__(self):
        self.results = []

    def on_action_execute(self, interp, action):  # noqa: ANN001
        try:
            blob = interp.get_persisted_snapshot()
        except SnapshotMidStepError:
            self.results.append(("REFUSED-write", None))
            return
        self.results.append(("ACCEPTED-write", blob))


def check(label, plug):
    print(f"--- {label}")
    bad = 0
    for kind, blob in plug.results:
        if blob is None:
            print(f"   {kind}")
            continue
        cfgids = blob.get("configuration")
        try:
            SyncInterpreter.from_snapshot(
                json.dumps(blob), build(), verify_machine_hash=False
            )
            print(f"   {kind} -> read side ACCEPTED  cfg={cfgids}")
        except XStateMachineError as e:
            bad += 1
            print(f"   {kind} -> read side {type(e).__name__}")
            print(f"        cfg={cfgids} ctx={blob.get('context')}")
            print(f"        {e}")
    return bad


async def main():
    p = Snap()
    i = Interpreter(build())
    i.use(p)
    await i.start()
    bad_async = check("ASYNC Interpreter.start()", p)
    await i.stop()

    p2 = Snap()
    s = SyncInterpreter(build())
    s.use(p2)
    s.start()
    bad_sync = check("SYNC SyncInterpreter.start()", p2)
    s.stop()

    print()
    print(f"write-accepted / read-refused blobs: async={bad_async} "
          f"sync={bad_sync}   <- must be 0")
    print("VERDICT:", "PASS" if bad_async == 0 and bad_sync == 0 else "FAIL")


asyncio.run(main())
