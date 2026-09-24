"""D7 -- plugin hook parity at start(): the sync engine reports an init
transition that the async engine does not.

Every D6 trace diverges at index 0 for the same reason: `SyncInterpreter.start()`
fires `on_transition` for the synthetic init event
`___xstate_statemachine_init___`, and `Interpreter.start()` does not. An audit
log built from `on_transition` therefore has one extra leading record on the
sync engine -- the two engines' audit trails are not comparable byte-for-byte
even when the machine behaves identically.

Also checks `on_event_received` for the init event, and whether the init
transition is visible in `on_action_execute` ordering.
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
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

CFG = {
    "id": "h",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"entry": ["ea"], "on": {"GO": {"target": "b"}}},
        "b": {"entry": ["eb"]},
    },
}


class All(PluginBase):
    def __init__(self, t):
        self.t = t

    def on_interpreter_start(self, i):
        self.t.append(("start",))

    def on_event_received(self, i, e):
        self.t.append(("recv", e.type))

    def on_transition(self, i, f, to, tr):
        self.t.append(
            (
                "transition",
                tr.event,
                tuple(sorted(s.id for s in f)),
                tuple(sorted(s.id for s in to)),
            )
        )

    def on_action_execute(self, i, a):
        self.t.append(("action", a.type))

    def on_interpreter_stop(self, i):
        self.t.append(("stop",))


def mk():
    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={
                "ea": lambda i, c, e, a: None,
                "eb": lambda i, c, e, a: None,
            }
        ),
    )


async def a_trace():
    t = []
    i = Interpreter(mk(), clock=SimulatedClock())
    i.use(All(t))
    await i.start()
    await i.send("GO")
    for _ in range(200):
        await asyncio.sleep(0)
    await i.stop()
    return t


def s_trace():
    t = []
    i = SyncInterpreter(mk(), clock=SimulatedClock())
    i.use(All(t))
    i.start()
    i.send("GO")
    i.stop()
    return t


if __name__ == "__main__":
    a = asyncio.run(a_trace())
    s = s_trace()
    print("ASYNC hook trace:")
    for x in a:
        print("   ", x)
    print("\nSYNC hook trace:")
    for x in s:
        print("   ", x)
    print(f"\nidentical: {a == s}")
    only_a = [x for x in a if x not in s]
    only_s = [x for x in s if x not in a]
    print(f"async-only records: {only_a}")
    print(f"sync-only  records: {only_s}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d7_hook_parity.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"async": a, "sync": s, "identical": a == s}, f, indent=2, default=str
        )
