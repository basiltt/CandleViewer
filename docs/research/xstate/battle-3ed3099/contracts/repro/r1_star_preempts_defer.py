# -*- coding: utf-8 -*-
"""REPRO: the inline A3 scaffolding (`"*": {"actions": ["defer"]}`) PRE-EMPTS the
runtime's `onUnhandled: "defer"` buffer, so the event is consumed and lost.

Catalogue 28 sec 1.3b (E50-T09) claims the inline handler is "dead but harmless"
because "with onUnhandled: 'defer' set, the runtime holds the event before any
'*' handler is consulted". This script shows the opposite: the wildcard is an
ordinary internal transition, it MATCHES, so the event is handled, the runtime
defer buffer is never consulted, and a fill delivered during `submitting`
disappears with no exception, no drop hook and no unhandled hook.
"""
from __future__ import annotations
import asyncio
from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 SimulatedClock)
from xstate_statemachine.plugins import PluginBase

BASE = {
    "id": "m",
    "actionErrorPolicy": "rollback",
    "onUnhandled": "defer",
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "strict": True,
    "initial": "busy",
    "context": {"fills": 0},
    "states": {
        "busy": {"on": {"ACK": {"target": "idle"}}},
        "idle": {"on": {"EXEC": {"actions": ["apply_fill"]}}},
    },
}


class P(PluginBase):
    def __init__(self):
        self.dropped, self.unhandled = [], []

    def on_event_dropped(self, i, e, reason):
        self.dropped.append((e.type, reason))

    def on_unhandled_event(self, i, e, ids, disp):
        self.unhandled.append((e.type, disp))


def cfg(with_star):
    import copy
    c = copy.deepcopy(BASE)
    if with_star:
        c["states"]["busy"]["on"]["*"] = {"actions": ["defer"]}
    return c


async def run(with_star):
    calls = []

    def apply_fill(i, ctx, e, ad):
        calls.append("apply_fill")
        ctx["fills"] += 1

    def defer(i, ctx, e, ad):
        calls.append("defer")

    logic = MachineLogic(actions={"apply_fill": apply_fill, "defer": defer},
                         strict=True)
    i = Interpreter(create_machine(cfg(with_star), logic=logic), clock=SimulatedClock())
    p = P()
    i.use(p)
    await i.start()
    await asyncio.sleep(0.03)
    r = await i.send("EXEC", wait=True)          # arrives one step early
    await asyncio.sleep(0.03)
    held = i.deferred_count
    await i.send("ACK")                          # handler is now armed
    await asyncio.sleep(0.06)
    out = dict(star=with_star, deferred_at_send=held, fills=i.context["fills"],
               actions=calls, dropped=p.dropped, unhandled=p.unhandled,
               receipt=(getattr(r, "changed", None), getattr(r, "deferred", None),
                        repr(getattr(r, "error", None))))
    await i.stop()
    return out


async def main():
    a = await run(False)
    b = await run(True)
    print("WITHOUT inline '*':", a)
    print("WITH    inline '*':", b)
    print()
    print("VERDICT: fill preserved without scaffolding =", a["fills"] == 1,
          "| fill LOST with scaffolding =", b["fills"] == 0)
    print("silent?  dropped hooks =", b["dropped"], " unhandled hooks =", b["unhandled"])


asyncio.run(main())
