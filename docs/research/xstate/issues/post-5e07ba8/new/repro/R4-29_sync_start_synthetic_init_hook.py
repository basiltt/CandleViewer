"""R4-29: SyncInterpreter.start() fires a synthetic init `on_transition` hook
record (sync_interpreter.py:336-339) that the async engine's start() never
emits (interpreter.py). Any hook-based audit trace diffed across engines
therefore mismatches at index 0 always -- a fixed constant offset, not
run-to-run instability.

Exits 1 while the sync trace has a leading transition record for the
synthetic init event `___xstate_statemachine_init___` that has no
counterpart in the async trace.
"""
from __future__ import annotations

import asyncio
import logging
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

CFG = {
    "id": "h",
    "initial": "a",
    "context": {},
    "states": {"a": {"entry": ["ea"], "on": {"GO": "b"}}, "b": {"entry": ["eb"]}},
}


class All(PluginBase):
    def __init__(self, t):
        self.t = t

    def on_transition(self, i, f, to, tr):
        self.t.append(("transition", tr.event, tuple(sorted(s.id for s in f)), tuple(sorted(s.id for s in to))))


def mk():
    return create_machine(
        CFG,
        logic=MachineLogic(actions={"ea": lambda i, c, e, a: None, "eb": lambda i, c, e, a: None}),
    )


async def a_trace():
    t = []
    i = Interpreter(mk())
    i.use(All(t))
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.05)
    await i.stop()
    return t


def s_trace():
    t = []
    i = SyncInterpreter(mk())
    i.use(All(t))
    i.start()
    i.send("GO")
    i.stop()
    return t


if __name__ == "__main__":
    a = asyncio.run(a_trace())
    s = s_trace()
    print("OBSERVED sync trace  :", s)
    print("OBSERVED async trace :", a)
    print("EXPECTED: sync[0] == async[0] (both emit, or neither emits, the init transition)")
    sync_only_init = bool(s) and s[0][1] == "___xstate_statemachine_init___" and (not a or a[0] != s[0])
    if sync_only_init:
        print("FAIL: sync-only leading synthetic init transition record; traces diverge at index 0")
        sys.exit(1)
    print("PASS: no sync-only leading init record")
    sys.exit(0)
