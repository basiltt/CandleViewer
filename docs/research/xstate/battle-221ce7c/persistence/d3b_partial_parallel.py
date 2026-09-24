# -*- coding: utf-8 -*-
"""D-persistence-3b: PARTIAL configuration tear in a parallel state.

A snapshot taken during a macrostep that is entering/leaving one region of a
parallel state records only the regions that happen to be settled. The blob
restores WITHOUT error and the restored machine is missing a whole parallel
region: its `after` transitions, its invokes and its events are gone, and
`status` is "running".

This is the same tear as `d3_torn_snapshot.py` but it is worse operationally,
because the blob does NOT look obviously broken -- `state_ids` is non-empty
and points at real states.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

import order_machine
from harness import attach_clock


class SnapOn(PluginBase):
    """Snapshot the instant a named action runs."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.blob: str | None = None

    def on_action_execute(self, interp, action):  # noqa: ANN001
        if action.type == self.target and self.blob is None:
            self.blob = interp.get_snapshot()


async def main() -> None:
    plug = SnapOn("store_ack")  # runs on the exchange region's onDone
    i = Interpreter(order_machine.build(), clock=SimulatedClock())
    i.use(plug)
    await i.start()
    await asyncio.sleep(0.03)
    await i.send("SUBMIT", qty=7)
    await asyncio.sleep(0.08)
    print("uninterrupted at this point:", sorted(i.current_state_ids))
    await i.stop()

    d = json.loads(plug.blob)
    print("\nsnapshot taken during the exchange region's onDone:")
    print("   state_ids    =", d["state_ids"])
    print("   configuration=", d["configuration"])
    print("   value        =", d["value"])
    print("   -> the whole `exchange` region is ABSENT.")

    i2 = Interpreter.from_snapshot(plug.blob, order_machine.build())
    attach_clock(i2, SimulatedClock())
    await i2.start()
    await asyncio.sleep(0.05)
    print("\nrestored (no error raised):")
    print("   states  =", sorted(i2.current_state_ids))
    print("   status  =", i2.status)
    print("   error   =", i2.error)
    print("   dormant =", i2.has_dormant_invocations)

    # the exchange region is gone: FILL/DONE now match nothing
    r1 = await i2.send("RISK_OK", wait=True)
    r2 = await i2.send("FILL", wait=True, n=3)
    r3 = await i2.send("DONE", wait=True)
    await asyncio.sleep(0.05)
    print("\n   RISK_OK receipt:", r1.changed, "| FILL:", r2.changed,
          r2.deferred, "| DONE:", r3.changed, r3.deferred)
    print("   states  =", sorted(i2.current_state_ids))
    print("   filled  =", i2.context["filled"], "(uninterrupted run: 3)")
    print("\n   -> the order can never fill or complete. The machine reports"
          "\n      itself healthy and silently defers every exchange event.")
    await i2.stop()


if __name__ == "__main__":
    asyncio.run(main())
