# -*- coding: utf-8 -*-
"""R7-10 -- `get_persisted_snapshot()` called from the `on_action_execute`
plugin hook returns a TORN blob (`status: "running"`, `state_ids: []`) on
the async `Interpreter`. The sync `SyncInterpreter` refuses the identical
call with `SnapshotMidStepError`.

#169 armed the root refusal on "in flight" alone for entry/exit actions, but
`on_action_execute` also fires for TRANSITION actions; for at least one of
those the async engine is not flagged in flight while `_active_state_nodes`
has already been emptied by `_exit_states` (refusal check at
`base_interpreter.py:1389`, `if self._step_in_flight():`, vs the
exit -> actions -> enter transaction in `interpreter.py`).

The blob is caught on restore by the read-side configuration-legality check
(`SnapshotCorruptError`), so this is an observability/engine-parity defect,
not silent corruption -- but the async engine hands back a lie where the
sync engine correctly refuses.

Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == the async engine returned >=1 torn blob (status="running",
state_ids=[]) from `on_action_execute` while the sync engine refused every
call. Exit code 0 == parity held.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import XStateMachineError

CFG = {
    "id": "ord",
    "initial": "top",
    "context": {"n": 0},
    "states": {
        "top": {
            "initial": "one",
            "states": {
                "one": {
                    "entry": ["act"],
                    "exit": ["act"],
                    "initial": "deep",
                    "states": {"deep": {"entry": ["act"]}},
                    "on": {"STEP": {"target": "#ord.top.two", "actions": ["act"]}},
                },
                "two": {"entry": ["act"], "on": {"STEP": "#ord.top.one"}},
            },
        }
    },
}


def act(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


def mk():
    return create_machine(CFG, logic=MachineLogic(actions={"act": act}))


class Grab(PluginBase):
    def __init__(self) -> None:
        self.rows: list = []

    def on_action_execute(self, i, action) -> None:  # noqa: ANN001
        name = getattr(action, "type", None) or getattr(action, "name", "?")
        try:
            b = i.get_persisted_snapshot()
            self.rows.append({
                "action": str(name), "disposition": "RETURNED",
                "status": b.get("status"), "state_ids": b.get("state_ids"),
                "blob": b,
            })
        except XStateMachineError as exc:
            self.rows.append({
                "action": str(name), "disposition": "refused:" + type(exc).__name__,
            })


async def main() -> int:
    ai = Interpreter(mk())
    ag = Grab()
    ai.use(ag)
    await ai.start()
    await asyncio.wait_for(ai.send("STEP", wait=True), 5)
    await ai.stop()

    si = SyncInterpreter(mk())
    sg = Grab()
    si.use(sg)
    si.start()
    si.send("STEP")
    si.stop()

    torn = [r for r in ag.rows if r["disposition"] == "RETURNED"
            and r["status"] == "running" and not r["state_ids"]]
    sync_torn = [r for r in sg.rows if r["disposition"] == "RETURNED"
                 and r["status"] == "running" and not r["state_ids"]]

    print("async rows:", [
        {k: v for k, v in r.items() if k != "blob"} for r in ag.rows])
    print("sync  rows:", sg.rows)
    print("async_torn_blobs=%d sync_torn_blobs=%d" % (len(torn), len(sync_torn)))

    if torn:
        try:
            r = Interpreter.from_snapshot(json.dumps(torn[0]["blob"]), mk())
            restored = {"restore": "ACCEPTED"}
            await r.stop()
        except XStateMachineError as exc:
            restored = {"restore": "REFUSED", "exc": type(exc).__name__}
        print("restored_from_torn_blob:", restored)

    if torn and not sync_torn:
        print("REPRODUCED: async on_action_execute returned %d torn blob(s) "
              "(status='running', state_ids=[]) while sync refused all %d "
              "calls with SnapshotMidStepError." % (len(torn), len(sg.rows)))
        print("EXPECTED  : engine parity -- the in-flight flag must cover the "
              "whole exit->actions->enter transaction on the async engine too, "
              "so on_action_execute is inside the refusal window on both engines.")
        return 1
    print("NOT reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
