# -*- coding: utf-8 -*-
"""D-persistence-3 (Blocker) minimal repro.

`get_persisted_snapshot()` taken while a macrostep is in flight records an
EMPTY configuration. The transition algorithm exits the source states, runs
the transition's actions, then enters the targets; a snapshot taken between
the exit and the entry sees `_active_state_nodes == set()`.

The snapshot is accepted by `from_snapshot()` without complaint, restores to
a machine with `status == "running"` and NO active states, and that machine
is permanently inert: every subsequent event matches nothing.

Nothing reports this. `status` is "running", `error` is None,
`has_dormant_invocations` is False.

Run:
  PYTHONPATH=<lib>/src python d3_torn_snapshot.py
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

from harness import attach_clock

HANG = asyncio.Event()

CONFIG = {
    "id": "torn",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["slow"]}}},
        "b": {"on": {"PING": {"target": "c"}}},
        "c": {},
    },
}


async def slow(i, ctx, e, ad):  # noqa: ANN001
    await HANG.wait()


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"slow": slow}))


async def main() -> None:
    i = await Interpreter(build(), clock=SimulatedClock()).start()
    await asyncio.sleep(0.02)
    print("before GO :", sorted(i.current_state_ids))

    asyncio.ensure_future(i.send("GO"))
    await asyncio.sleep(0.05)  # parked inside `slow`, mid-macrostep

    blob = i.get_snapshot()
    d = json.loads(blob)
    print("MID-MACROSTEP snapshot:")
    print("   state_ids    =", d["state_ids"])
    print("   configuration=", d["configuration"])
    print("   status       =", d["status"])
    print("   value        =", d["value"])
    assert d["state_ids"] == [], "expected the torn, empty configuration"

    HANG.set()
    await i.stop()

    i2 = Interpreter.from_snapshot(blob, build())
    attach_clock(i2, SimulatedClock())
    await i2.start()
    await asyncio.sleep(0.05)
    print("\nRESTORED from the torn snapshot:")
    print("   states                 =", sorted(i2.current_state_ids))
    print("   status                 =", i2.status)
    print("   error                  =", i2.error)
    print("   has_dormant_invocations=", i2.has_dormant_invocations)

    r = await i2.send("PING", wait=True)
    await asyncio.sleep(0.05)
    print("   send('PING') receipt   =", r)
    print("   states after PING      =", sorted(i2.current_state_ids))
    print("\n   -> a 'running' machine with no configuration. Every event"
          "\n      matches nothing, forever. No error, no hook, no signal.")
    await i2.stop()


if __name__ == "__main__":
    asyncio.run(main())
