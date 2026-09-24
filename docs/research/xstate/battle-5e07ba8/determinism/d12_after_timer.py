"""D12 -- `after` timers and the sync engine: a `SimulatedClock` tick does not
deliver a due `after` unless something else pumps.

D6/S5 showed, for `10x (GO, advance 100ms)` on a `busy` state with a 50 ms
`after`:
    async: ok=2  late=8
    sync : ok=10 late=0
Two mechanisms are entangled there (D8's sync-invoke timing plus the timer).
This isolates the TIMER alone, with no invoke in the machine at all.

Questions
  Q1  On the sync engine, does `clock.increment(ms)` alone run the `after`
      transition, or must a `send()` / `tick()` follow?
  Q2  Same on the async engine.
  Q3  Does the timer fire at all if the machine never receives another event?
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

CFG = {
    "id": "t12",
    "initial": "idle",
    "context": {"late": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "armed"}}},
        "armed": {
            "after": {"50": {"target": "idle", "actions": ["late"]}},
            "on": {"NOOP": {"actions": []}},
        },
    },
}


def build():
    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={"late": lambda i, c, e, a: c.__setitem__("late", c["late"] + 1)}
        ),
    )


async def a_case(after_tick):
    clock = SimulatedClock()
    i = Interpreter(build(), clock=clock)
    await i.start()
    for _ in range(10):
        await i.send("GO")
        await clock.increment(100)
        if after_tick == "send":
            await i.send("NOOP")
        elif after_tick == "tick":
            for _ in range(50):
                await asyncio.sleep(0)
    for _ in range(3000):
        await asyncio.sleep(0)
    out = (dict(i.context), sorted(i.current_state_ids))
    await i.stop()
    return out


def s_case(after_tick):
    clock = SimulatedClock()
    i = SyncInterpreter(build(), clock=clock)
    i.start()
    for _ in range(10):
        i.send("GO")
        clock.increment(100)
        if after_tick == "send":
            i.send("NOOP")
        elif after_tick == "tick":
            i.tick()
    out = (dict(i.context), sorted(i.current_state_ids))
    i.stop()
    return out


if __name__ == "__main__":
    print("machine: idle --GO--> armed; armed has `after: {50: -> idle +late}`")
    print("script : 10x (GO, clock.increment(100), [optional pump])")
    print("expected for a correct SimulatedClock: late == 10 in every case\n")
    rows = {}
    for mode in ["none", "tick", "send"]:
        a = asyncio.run(a_case(mode))
        s = s_case(mode)
        rows[mode] = {"async": a, "sync": s, "agree": a == s}
        print(f"  pump={mode:5s}  async={a[0]} state={a[1]}")
        print(f"                sync ={s[0]} state={s[1]}   agree={a == s}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d12_after_timer.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)
    print("\nwrote out/d12_after_timer.json")
