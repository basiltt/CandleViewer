# -*- coding: utf-8 -*-
"""T7 - rollback and the snapshot boundary.

Q1: after `actionErrorPolicy: "rollback"` undoes a transition, does a
    snapshot record the ROLLED-BACK (correct) configuration?
Q2: is a snapshot taken DURING the rollback window torn?
Q3: events the failed action `raise`d are withdrawn (#27) -- are any of
    them left in the persisted inbox?
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

from harness import attach_clock

CONFIG = {
    "id": "rb",
    "initial": "a",
    "actionErrorPolicy": "rollback",
    "context": {"n": 0, "log": []},
    "states": {
        "a": {
            "on": {
                "GO": {
                    "target": "b",
                    "actions": ["bump", {"type": "raise", "params": {"event": "SELF"}},
                                "explode"],
                }
            }
        },
        "b": {"entry": ["mark_b"], "on": {"SELF": {"target": "c"}}},
        "c": {},
    },
}


def bump(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] += 1
    ctx["log"].append("bump")


def explode(i, ctx, e, ad):  # noqa: ANN001
    ctx["log"].append("explode")
    raise RuntimeError("action failed")


def mark_b(i, ctx, e, ad):  # noqa: ANN001
    ctx["log"].append("mark_b")


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={
        "bump": bump, "explode": explode, "mark_b": mark_b}))


class SnapEach(PluginBase):
    def __init__(self) -> None:
        self.blobs: list[tuple[str, str]] = []

    def on_action_execute(self, interp, action):  # noqa: ANN001
        self.blobs.append((action.type, interp.get_snapshot()))


async def main() -> None:
    plug = SnapEach()
    i = Interpreter(build(), clock=SimulatedClock())
    i.use(plug)
    await i.start()
    await asyncio.sleep(0.03)
    r = await i.send("GO", wait=True)
    await asyncio.sleep(0.08)
    print("after the rolled-back GO:")
    print("   receipt =", r)
    print("   states  =", sorted(i.current_state_ids))
    print("   context =", i.context)
    blob = i.get_snapshot()
    d = json.loads(blob)
    print("   SNAPSHOT state_ids =", d["state_ids"])
    print("   SNAPSHOT context   =", d["context"])
    print("   SNAPSHOT pending   =", [x["type"] for x in d["pending_events"]])
    await i.stop()

    i2 = Interpreter.from_snapshot(blob, build())
    attach_clock(i2, SimulatedClock())
    await i2.start()
    await asyncio.sleep(0.05)
    print("\nrestored after rollback:")
    print("   states =", sorted(i2.current_state_ids), "status =", i2.status)
    print("   context=", i2.context)
    print("   -> the withdrawn `SELF` must NOT be replayed; states must be "
          "['rb.a'].")
    await i2.stop()

    print("\nsnapshots taken DURING the failing macrostep:")
    for action, b in plug.blobs:
        dd = json.loads(b)
        tag = "TORN" if not dd["state_ids"] else "ok"
        print(f"   {tag:5} at {action:8} state_ids={dd['state_ids']} "
              f"n={dd['context']['n']} log={dd['context']['log']}")


if __name__ == "__main__":
    asyncio.run(main())
