# -*- coding: utf-8 -*-
"""D-persistence-2 minimal repro: `after` timers are NOT re-armed by a restore.

A state with `after` is snapshotted while its timer is armed. After
`from_snapshot()` + `start()` the deadline never fires -- neither with the
default static restore NOR with `restart_services=True`, and
`pending_invocations()` / `has_dormant_invocations` do not report it, so
there is no signal that a pending timeout was lost.

Run:
  PYTHONPATH=<lib>/src python d2_after_timer_lost.py
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

from harness import attach_clock

CONFIG = {
    "id": "timeout_demo",
    "initial": "waiting",
    "context": {"fired": False},
    "states": {
        "waiting": {
            "after": {"5000": {"target": "expired", "actions": ["mark"]}},
            "on": {"OK": {"target": "done_ok"}},
        },
        "expired": {"type": "final"},
        "done_ok": {"type": "final"},
    },
}


def mark(interp, ctx, event, ad):  # noqa: ANN001
    ctx["fired"] = True


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"mark": mark}))


async def main() -> None:
    # --- reference: no crash -------------------------------------------
    c1 = SimulatedClock()
    i1 = await Interpreter(build(), clock=c1).start()
    await asyncio.sleep(0.02)
    await c1.increment(6000)
    await asyncio.sleep(0.02)
    print("REFERENCE  after 6 s :", sorted(i1.current_state_ids),
          "fired =", i1.context["fired"])
    await i1.stop()

    # --- crash 1 s in, restore, advance the same virtual 6 s ------------
    for restart in (False, True):
        c2 = SimulatedClock()
        i2 = await Interpreter(build(), clock=c2).start()
        await asyncio.sleep(0.02)
        await c2.increment(1000)
        blob = i2.get_snapshot()
        now = c2.now()
        await i2.stop()

        c3 = SimulatedClock()
        c3._now = now  # virtual time survives the crash
        i3 = Interpreter.from_snapshot(
            blob, build(), restart_services=restart
        )
        attach_clock(i3, c3)
        await i3.start()
        await asyncio.sleep(0.02)
        print(f"  restart_services={restart}: "
              f"dormant={i3.has_dormant_invocations} "
              f"pending_invocations={i3.pending_invocations()} "
              f"clock.pending={c3.pending}")
        await c3.increment(10000)  # 11 s total -- well past the 5 s deadline
        await asyncio.sleep(0.02)
        print(f"  RESTORED after 11 s: {sorted(i3.current_state_ids)} "
              f"fired = {i3.context['fired']}  status={i3.status}")
        await i3.stop()


if __name__ == "__main__":
    asyncio.run(main())
