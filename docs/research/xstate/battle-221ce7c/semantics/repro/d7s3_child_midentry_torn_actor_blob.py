"""D7-semantics-3 repro: a snapshot taken at the ROOT while a CHILD actor is
mid-entry-action is ACCEPTED and embeds the child's HALF-APPLIED context.

#169 refuses at the root when the ROOT's own step is in flight, but the root is
quiescent here - only the child is mid-step. The child's blob is harvested
without consulting the child's own in-flight flag, so the persisted hierarchy
records `kid.y` (the state whose entry sets q=100, p=101) paired with
`{q: 100, p: 0}`. Restores clean, no error.

Run: python d7s3_child_midentry_torn_actor_blob.py
"""

from __future__ import annotations

import asyncio
import json
import logging

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

logging.disable(logging.CRITICAL)

PARENT = {
    "id": "par", "initial": "run",
    "states": {"run": {"invoke": {"src": "child", "id": "kid"}}},
}
CHILD = {
    "id": "kid", "initial": "x",
    "context": {"q": 0, "p": 0},
    "states": {
        "x": {"on": {"STEP": "y"}},
        "y": {"entry": ["set_q", "set_p"]},
    },
}


def set_q(i_, ctx, e, am):  # noqa: ANN001
    ctx["q"] = 100


def set_p(i_, ctx, e, am):  # noqa: ANN001
    ctx["p"] = 101


class RootSnapper(PluginBase):
    """Installed on the CHILD; snapshots the ROOT from the child's entry."""

    def __init__(self, root) -> None:  # noqa: ANN001
        self.root = root
        self.rows = []

    def on_action_execute(self, interp, action):  # noqa: ANN001
        try:
            blob = self.root.get_persisted_snapshot()
            self.rows.append(("ACCEPTED", blob))
        except Exception as exc:  # noqa: BLE001
            self.rows.append((f"REFUSED:{type(exc).__name__}", None))


async def amain() -> None:
    logic_c = MachineLogic(actions={"set_q": set_q, "set_p": set_p})
    child_m = create_machine(CHILD, logic=logic_c)
    root = await Interpreter(
        create_machine(PARENT, logic=MachineLogic(services={"child": child_m}))
    ).start()
    kid = next(a for k, a in root._actors.items() if k.endswith("kid"))
    snap = RootSnapper(root)
    kid.use(snap)
    await kid.send("STEP", wait=True)

    print(f"root in flight during child entry : {root._step_in_flight()}")
    print(f"live child after settle           : "
          f"{sorted(kid.current_state_ids)} ctx={dict(kid.context)}")
    for r, blob in snap.rows:
        if blob is None:
            print(f"root snapshot during child entry  : {r}")
            continue
        sub = list((blob.get("actors") or {}).values())[0]["snapshot"]
        ctx = sub["context"]
        torn = (ctx["q"] > 0) != (ctx["p"] > 0)
        print(f"root snapshot during child entry  : {r} "
              f"child={sub['state_ids']} ctx={ctx}"
              f"{'   >>> TORN' if torn else ''}")
    await root.stop()


if __name__ == "__main__":
    asyncio.run(amain())
