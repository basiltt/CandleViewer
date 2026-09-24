"""D7-semantics-1 repro: on the ASYNC engine a snapshot taken from inside an
entry action of the INITIAL configuration (during `await start()`) is ACCEPTED
and is torn. The sync engine refuses the same call.

Run: python d7s1_start_entry_window_torn.py
"""

from __future__ import annotations

import asyncio
import json
import logging

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SnapshotMidStepError,
    SyncInterpreter,
    create_machine,
)

logging.disable(logging.CRITICAL)

CFG = {
    "id": "oms",
    "initial": "filled",
    "context": {"filled_qty": 0, "avg_px": 0},
    "states": {"filled": {"entry": ["set_qty", "set_px"]}},
}


def logic() -> MachineLogic:
    def set_qty(i_, ctx, e, am):  # noqa: ANN001
        ctx["filled_qty"] = 100

    def set_px(i_, ctx, e, am):  # noqa: ANN001
        ctx["avg_px"] = 101.5

    return MachineLogic(actions={"set_qty": set_qty, "set_px": set_px})


class Snapper(PluginBase):
    def __init__(self) -> None:
        self.rows = []

    def on_action_execute(self, interp, action):  # noqa: ANN001
        try:
            blob = interp.get_persisted_snapshot()
            self.rows.append(("ACCEPTED", dict(blob.get("context", {})), blob))
        except SnapshotMidStepError:
            self.rows.append(("REFUSED", None, None))


async def amain() -> None:
    for name in ("sync", "async"):
        p = Snapper()
        m = create_machine(CFG, logic=logic())
        if name == "sync":
            i = SyncInterpreter(m).use(p).start()
            live = (sorted(i.current_state_ids), dict(i.context))
            i.stop()
        else:
            i = await Interpreter(m).use(p).start()
            live = (sorted(i.current_state_ids), dict(i.context))
            await i.stop()
        print(f"--- {name}")
        print(f"  live after start : {live[0]} ctx={live[1]}")
        for r, ctx, blob in p.rows:
            print(f"  snapshot in entry: {r} ctx={ctx}")
            if r == "ACCEPTED" and ctx and (ctx["filled_qty"] > 0) != (ctx["avg_px"] > 0):
                print("     >>> TORN: filled_qty set, avg_px not written yet")
                rb = await Interpreter.from_snapshot(json.dumps(blob), create_machine(CFG, logic=logic())).start()
                print(f"     restored: {sorted(rb.current_state_ids)} ctx={dict(rb.context)} "
                      f"last_error={rb.last_error}")
                await rb.stop()


if __name__ == "__main__":
    asyncio.run(amain())
