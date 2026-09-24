"""D8 -- a PLAIN SYNC `invoke` src completes at a different point on each engine.

`SyncInterpreter._invoke_service` (sync_interpreter.py:1367-1375) calls the
service INLINE during `_enter_states` and `self.send(DoneEvent(...))` right
there, so `done.invoke.*` is queued inside the entering macrostep and processed
before the caller's `send()` returns.

`Interpreter._invoke_service` (interpreter.py:1868+) always wraps the service in
an asyncio TASK (`_invoke_service_task`, interpreter.py:1771). Even when the
callable is a plain sync function that returns immediately
(interpreter.py:1813-1816 detects this and does NOT await it), the DoneEvent is
sent from that task, which cannot run until the current macrostep yields.

Consequence: the same machine + same events + same (simulated) clock produces a
DIFFERENT number of service completions on the two engines, because on the
async engine a competing external event can overtake the completion.

This script measures the exact yield-count at which the two agree.
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
    "id": "d8",
    "initial": "idle",
    "context": {"ok": 0, "cancel": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "busy"}}},
        "busy": {
            "invoke": {
                "id": "s",
                "src": "work",
                "onDone": {"target": "idle", "actions": ["ok"]},
            },
            "on": {"CANCEL": {"target": "idle", "actions": ["cancel"]}},
        },
    },
}


def logic():
    def ok(i, c, e, a):
        c["ok"] += 1

    def cancel(i, c, e, a):
        c["cancel"] += 1

    def work(i, c, e):  # PLAIN SYNC -- returns instantly, no awaits
        return 1

    return MachineLogic(
        actions={"ok": ok, "cancel": cancel}, services={"work": work}
    )


def build():
    return create_machine(CFG, logic=logic())


N = 10


async def a_run(gap):
    i = Interpreter(build(), clock=SimulatedClock())
    await i.start()
    for _ in range(N):
        await i.send("GO")
        for _ in range(gap):
            await asyncio.sleep(0)
        await i.send("CANCEL")
    for _ in range(2000):
        await asyncio.sleep(0)
    out = dict(i.context)
    await i.stop()
    return out


def s_run():
    i = SyncInterpreter(build(), clock=SimulatedClock())
    i.start()
    for _ in range(N):
        i.send("GO")
        i.send("CANCEL")
    out = dict(i.context)
    i.stop()
    return out


if __name__ == "__main__":
    sync = s_run()
    print(f"script: {N}x (GO, CANCEL); service is a plain sync callable")
    print(f"\nSYNC engine (no scheduling to vary): {sync}")
    print("\nASYNC engine, varying only the producer's loop-turn gap:")
    rows = {}
    for gap in range(0, 8):
        ctx = asyncio.run(a_run(gap))
        rows[gap] = ctx
        match = "  <- matches sync" if ctx == sync else ""
        print(f"  gap={gap}: {ctx}{match}")
    matches = [g for g, c in rows.items() if c == sync]
    print(
        f"\nasync matches sync for gap in {matches} "
        f"(of {list(rows)}) -- the engines agree only for particular "
        f"asyncio interleavings, not by construction."
    )
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d8_sync_invoke.json"), "w", encoding="utf-8") as f:
        json.dump({"sync": sync, "async_by_gap": rows}, f, indent=2)
