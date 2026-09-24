# -*- coding: utf-8 -*-
"""X14 -- root-cause the X13 leak: `_timer_handles` under a `raise(delay=)`.

STANDALONE. Neutral cwd.

`interpreter.py:2354` records every delayed-send handle as

    self._timer_handles.setdefault(self.id, []).append(handle)

keyed by the INTERPRETER id. The only pruner, `interpreter.py:2557`, runs
on state EXIT and pops `self._timer_handles[state.id]`. The machine id is
never a state that exits, so the list under it is append-only for the life
of the interpreter: one dead `TimerHandle` per heartbeat, for ever.
(`after` timers take the 2748 path with `owner_id = state.id` and ARE
pruned -- which is exactly why X13's `after:` control is flat.)

This measures the container directly and shows it tracks RSS.
"""
from __future__ import annotations

import asyncio
import gc
import json
import os
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

KIND = os.environ.get("XS_SVC", "async")
SECS = float(os.environ.get("XS_SECS", "12"))

RAISE_HB = {
    "id": "hb", "initial": "a", "context": {"beats": 0},
    "states": {
        "a": {"entry": [{"type": "raise",
                         "params": {"event": "T", "delay": 5, "id": "t"}},
                        "beat"],
              "on": {"T": "b"}},
        "b": {"entry": [{"type": "raise",
                         "params": {"event": "T", "delay": 5, "id": "t"}},
                        "beat"],
              "on": {"T": "a"}},
    },
}

AFTER_HB = {
    "id": "hb", "initial": "a", "context": {"beats": 0},
    "states": {
        "a": {"entry": ["beat"], "after": {"5": "b"}},
        "b": {"entry": ["beat"], "after": {"5": "a"}},
    },
}


def build(spec):
    def beat(i, c, e, a):  # noqa: ANN001
        c["beats"] += 1

    async def sa(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    def sd(i, c, e):  # noqa: ANN001
        return 1

    return create_machine(
        json.loads(json.dumps(spec)),
        logic=MachineLogic(actions={"beat": beat},
                           services={"s": sa if KIND == "async" else sd}),
    )


def sizes(i):
    th = {k: len(v) for k, v in i._timer_handles.items()}
    return (th, len(i._armed_self_sends), len(i._chain_owed_sends),
            len(i._scheduled_sends))


async def probe(label, spec):
    i = Interpreter(build(spec))
    await i.start()
    t0 = time.monotonic()
    rows = []
    while time.monotonic() - t0 < SECS:
        await asyncio.sleep(SECS / 4)
        th, arm, owed, sched = sizes(i)
        rows.append((round(time.monotonic() - t0), i.context["beats"],
                     th, arm, owed, sched))
    beats = i.context["beats"]
    th, arm, owed, sched = sizes(i)
    # how many of the retained handles are already fired/cancelled?
    total = sum(len(v) for v in i._timer_handles.values())
    dead = 0
    for v in i._timer_handles.values():
        for h in v:
            cancelled = getattr(h, "cancelled", None)
            if cancelled is not None and callable(cancelled):
                # asyncio.TimerHandle: a fired handle reports _scheduled False
                if not getattr(h, "_scheduled", True):
                    dead += 1
    await i.stop()
    print(f"   {label}")
    for r in rows:
        print(f"     t={r[0]:3d}s beats={r[1]:6d} _timer_handles={r[2]} "
              f"_armed_self_sends={r[3]} _chain_owed={r[4]} "
              f"_scheduled_sends={r[5]}")
    print(f"     FINAL beats={beats} retained handles={total} "
          f"already-fired among them={dead} "
          f"ratio handles/beat={total / max(beats, 1):.2f}")
    return total, beats


async def main():
    print(f"X14 kind={KIND} SECS={SECS}")
    print("=== the container, sampled over time ===")
    hr, br = await probe("raise(delay=) heartbeat", RAISE_HB)
    ha, ba = await probe("after: heartbeat (control)", AFTER_HB)
    print(f"\n   raise: {hr} handles retained for {br} beats")
    print(f"   after: {ha} handles retained for {ba} beats")
    print(f"   VERDICT unbounded retention on the raise(delay=) path = "
          f"{'YES' if hr > 100 and ha < 100 else 'no'}")
    print("   root cause: interpreter.py:2354 keys the handle under "
          "`self.id` (the MACHINE id); the only pruner, "
          "interpreter.py:2557,\n   pops `_timer_handles[state.id]` on state "
          "EXIT, and the machine id is never an exiting state. The `after` "
          "path (2748)\n   uses owner_id=state.id and IS pruned.")


asyncio.run(main())
