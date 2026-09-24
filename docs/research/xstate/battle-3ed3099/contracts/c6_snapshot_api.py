# -*- coding: utf-8 -*-
"""C6 -- get_snapshot() vs get_persisted_snapshot() in the #102 window.

CHANGELOG #102 puts the `SnapshotMidStepError` guard on
`get_persisted_snapshot()`. C3/C4/C5 exercised `get_snapshot()`. This probe
calls BOTH from inside an exit action (the exit-set/entry-set window) and
from quiescence, on B8 -- the safety machine -- to establish which API
`cv.statechart.persistence` must use.
"""
from __future__ import annotations

import asyncio
import json

import cvlib
from cvlib import Rig
from xstate_statemachine.exceptions import SnapshotMidStepError


def call(interp, name):
    try:
        getattr(interp, name)()
        return "ALLOWED"
    except SnapshotMidStepError:
        return "SnapshotMidStepError"
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__ + ": " + str(exc)[:100]


async def main():
    cfg = cvlib.load("B9")
    seen = {}

    def mk(where):
        def hook(interp, ctx, event):
            seen[where] = {
                "get_snapshot": call(interp, "get_snapshot"),
                "get_persisted_snapshot": call(
                    interp, "get_persisted_snapshot"
                ),
            }
        return hook

    rig = Rig(
        guard_values={"promotion_gate_satisfied_and_permitted": True,
                      "condition_true": True},
        action_hooks={
            "subscribe_triggers": mk("entry-action"),
            "unsubscribe_triggers": mk("exit-action"),
            "assert_safety_limits": mk("entry-action(acting)"),
        },
    )
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    for ev in ("SAVE", "ARM_REQUESTED", "TRIGGER"):
        await interp.send(ev)
        await asyncio.sleep(cvlib.SETTLE * 2)
    await asyncio.sleep(cvlib.SETTLE * 3)
    seen["quiescent(caller)"] = {
        "get_snapshot": call(interp, "get_snapshot"),
        "get_persisted_snapshot": call(interp, "get_persisted_snapshot"),
    }
    await interp.stop()
    print(json.dumps(seen, indent=2))


asyncio.run(main())
