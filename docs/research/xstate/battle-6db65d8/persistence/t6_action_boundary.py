# -*- coding: utf-8 -*-
"""T6 - how often is a snapshot torn? Sample at every action boundary.

Uses `on_action_execute` (a documented plugin hook) to take a snapshot
before each action of a realistic run, and classifies each one:

  * OK      -- restores to the same configuration it recorded
  * TORN    -- records an EMPTY or non-atomic configuration
  * REFUSED -- `from_snapshot()` raised

This measures D-persistence-3's exposure without any monkeypatching: a
plugin hook is exactly where a production audit/persistence plugin lives.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

import order_machine
from harness import attach_clock


class SnapAtEveryAction(PluginBase):
    def __init__(self) -> None:
        self.snaps: list[tuple[str, str]] = []
        self.interp = None

    def on_action_execute(self, interp, action):  # noqa: ANN001
        self.interp = interp
        try:
            self.snaps.append((action.type, interp.get_snapshot()))
        except Exception as e:  # noqa: BLE001
            self.snaps.append((action.type, f"__ERR__{e}"))


SEQ = [
    ("SUBMIT", {"qty": 7}),
    ("RISK_OK", {}),
    ("FILL", {"n": 2}),
    ("DONE", {}),
]


async def main() -> None:
    plug = SnapAtEveryAction()
    i = Interpreter(order_machine.build(), clock=SimulatedClock())
    i.use(plug)
    await i.start()
    await asyncio.sleep(0.03)
    for name, payload in SEQ:
        await i.send(name, **payload)
        await asyncio.sleep(0.03)
    final = sorted(i.current_state_ids)
    await i.stop()

    ok = torn = refused = 0
    rows = []
    for action, blob in plug.snaps:
        if blob.startswith("__ERR__"):
            refused += 1
            rows.append((action, "SNAPSHOT-RAISED", blob[:60]))
            continue
        d = json.loads(blob)
        ids = d["state_ids"]
        cfg = d["configuration"]
        if not ids:
            torn += 1
            rows.append((action, "TORN", f"state_ids={ids} configuration={cfg}"))
            continue
        try:
            i2 = Interpreter.from_snapshot(blob, order_machine.build())
            attach_clock(i2, SimulatedClock())
            await i2.start()
            await asyncio.sleep(0.03)
            got = sorted(i2.current_state_ids)
            await i2.stop()
            if got == sorted(ids):
                ok += 1
                rows.append((action, "OK", str(got)))
            else:
                torn += 1
                rows.append((action, "DRIFT", f"recorded={ids} restored={got}"))
        except Exception as e:  # noqa: BLE001
            refused += 1
            rows.append((action, "REFUSED", f"{type(e).__name__}: {e}"))

    print(f"final (uninterrupted) = {final}\n")
    for a, verdict, detail in rows:
        print(f"  {verdict:15} at action {a:14} {detail}")
    n = len(rows)
    print(f"\n{ok}/{n} OK, {torn}/{n} torn/drifted, {refused}/{n} refused")


if __name__ == "__main__":
    asyncio.run(main())
