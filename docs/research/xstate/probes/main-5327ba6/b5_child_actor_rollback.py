"""B5 — rollback in the PARENT must not touch a CHILD ACTOR's queue.

A spawned child actor has its own internal queue and its own action-error
policy. When the parent's action list raises and the parent rolls back, the
`_discard_raised_since` bookkeeping must be scoped to the parent's own
`_internal_queue` -- a child's self-raised events are not the parent's to
withdraw.

B5a: child raises into its own queue while the parent's LATER action fails.
B5b: the parent's rollback withdraws only its own raise, not the child's.
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _h  # noqa: E402

from xstate_statemachine import Interpreter, MachineLogic, create_machine  # noqa: E402

warnings.simplefilter("ignore", DeprecationWarning)

SEEN: list = []

CHILD = {
    "id": "child",
    "initial": "idle",
    "context": {},
    "actionErrorPolicy": "rollback",
    "states": {
        "idle": {
            "on": {
                "WORK": {
                    "target": "busy",
                    "actions": [{"type": "raise", "params": {"event": "SELF"}}],
                }
            }
        },
        "busy": {"on": {"SELF": {"target": "done_", "actions": ["noteSelf"]}}},
        "done_": {},
    },
}


def note_self(i, c, e, a):
    SEEN.append("CHILD_SELF")


def parent_boom(i, c, e, a):
    raise RuntimeError("parent boom")


@_h.probe(
    "B5",
    "parent rollback leaves a child actor's self-raised event intact",
    {"child_seen": ["CHILD_SELF"], "parent_state": ["parent.idle"], "parent_seen": []},
)
async def b5():
    SEEN.clear()
    child_machine = create_machine(
        CHILD, logic=MachineLogic(actions={"noteSelf": note_self})
    )

    async def kick_child(interp, ctx, evt, act):
        # Spawn + drive a child actor, then let the PARENT's next action fail.
        child = Interpreter(child_machine)
        await child.start()
        ctx["child"] = child
        await child.send("WORK")
        await asyncio.sleep(0.05)

    cfg = {
        "id": "parent",
        "initial": "idle",
        "context": {},
        "actionErrorPolicy": "rollback",
        "states": {
            "idle": {
                "on": {
                    "GO": {
                        "target": "next",
                        "actions": [
                            "kickChild",
                            {"type": "raise", "params": {"event": "PPING"}},
                            "parentBoom",
                        ],
                    },
                    "PPING": {"actions": ["noteParent"]},
                }
            },
            "next": {"on": {"PPING": {"actions": ["noteParent"]}}},
        },
    }
    parent_seen: list = []

    def note_parent(i, c, e, a):
        parent_seen.append("PARENT_PING")

    m = create_machine(
        cfg,
        logic=MachineLogic(
            actions={
                "kickChild": kick_child,
                "parentBoom": parent_boom,
                "noteParent": note_parent,
            }
        ),
    )
    p = Interpreter(m)
    await p.start()
    await p.send("GO")
    await asyncio.sleep(0.3)
    child = p.context.get("child")
    out = {
        "child_seen": list(SEEN),
        "parent_state": sorted(p.current_state_ids),
        "parent_seen": parent_seen,
    }
    if child is not None:
        out["child_state"] = sorted(child.current_state_ids)
        await child.stop()
    await p.stop()
    return out


if __name__ == "__main__":
    _h.main("b5_child_actor_rollback")
