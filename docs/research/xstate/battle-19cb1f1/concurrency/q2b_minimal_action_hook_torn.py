"""Q2b - MINIMAL: `get_persisted_snapshot()` from `on_action_execute`
returns a TORN blob (`status: "running"`, `state_ids: []`) on the async
engine. The sync engine REFUSES the same call.

#169 closed the entry/exit-action window by refusing "in flight" at the
root. The refusal is evidently not armed for every action the async
engine executes: an action running during the exit->actions->enter
transaction is observed with the configuration already emptied, which is
exactly the state #142/#143/#169 were meant to make unobservable. The
blob restores into a live `running` machine with no configuration.

Deterministic; no randomness.
"""

from __future__ import annotations

import asyncio
import json

from common import emit
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
            self.rows.append(
                {
                    "action": str(name),
                    "disposition": "RETURNED",
                    "status": b.get("status"),
                    "state_ids": b.get("state_ids"),
                    "blob": b,
                }
            )
        except XStateMachineError as exc:
            self.rows.append(
                {
                    "action": str(name),
                    "disposition": "refused:" + type(exc).__name__,
                }
            )


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

    torn = [
        r
        for r in ag.rows
        if r["disposition"] == "RETURNED"
        and r["status"] == "running"
        and not r["state_ids"]
    ]
    restored_report = None
    if torn:
        try:
            r = Interpreter.from_snapshot(json.dumps(torn[0]["blob"]), mk())
        except XStateMachineError as exc:
            restored_report = {
                "restore": "REFUSED",
                "exc": type(exc).__name__,
                "msg": str(exc)[:160],
            }
        else:
            await r.start()
            try:
                await asyncio.wait_for(r.send("STEP", wait=True), 3)
                responds = True
            except asyncio.TimeoutError:
                responds = False
            except Exception:  # noqa: BLE001
                responds = True
            restored_report = {
                "restore": "ACCEPTED",
                "status": r.status,
                "state_ids": sorted(r.current_state_ids),
                "responds_to_STEP": responds,
            }
            await r.stop()

    emit(
        "q2b_minimal_action_hook_torn",
        {
            "async_rows": [
                {k: v for k, v in r.items() if k != "blob"} for r in ag.rows
            ],
            "sync_rows": [
                {k: v for k, v in r.items() if k != "blob"} for r in sg.rows
            ],
            "async_torn_blobs": len(torn),
            "sync_torn_blobs": sum(
                1
                for r in sg.rows
                if r["disposition"] == "RETURNED"
                and r["status"] == "running"
                and not r["state_ids"]
            ),
            "restored_from_torn_blob": restored_report,
            "result": "FAIL" if torn else "PASS",
        },
    )
    return 1 if torn else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
