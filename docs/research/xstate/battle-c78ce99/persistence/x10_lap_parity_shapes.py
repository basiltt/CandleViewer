# -*- coding: utf-8 -*-
"""X10 -- #215 lap parity: the PINNED shape vs adversarial variants.

STANDALONE. Neutral cwd.

`tests/test_round10_findings.py::TestLapParityOnEngineWorkOnlyChart` pins
ONE chart -- `a: entry raise GO + on GO -> b`, `b: always -> a` -- at
limits 1,3,5,10,15,19,25. X9/C found async != sync on a NEIGHBOURING shape.
This isolates which shapes agree and which do not, sweeping every limit
1..25 on all three lanes (sync / async-def / async-async).

  S1 PINNED    a: raise GO + tick, on GO->b ; b: always->a, tick
  S2 VARIANT   a: raise Z + lap, always->b  ; b: lap, on Z->a, always->a
  S3 always-only cycle (no raise at all)
  S4 raise-only cycle (no always at all)
"""
from __future__ import annotations

import asyncio
import json
import os

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import RunawayChainError

KIND = os.environ.get("XS_SVC", "async")

S1 = {
    "id": "w", "initial": "a",
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "GO"}}, "tick"],
              "on": {"GO": "b"}},
        "b": {"always": "a", "entry": ["tick"]},
    },
}
S2 = {
    "id": "w", "initial": "a",
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "Z"}}, "tick"],
              "always": [{"target": "b"}]},
        "b": {"entry": ["tick"], "on": {"Z": "a"},
              "always": [{"target": "a"}]},
    },
}
S3 = {
    "id": "w", "initial": "a",
    "states": {
        "a": {"entry": ["tick"], "always": [{"target": "b"}]},
        "b": {"entry": ["tick"], "always": [{"target": "a"}]},
    },
}
S4 = {
    "id": "w", "initial": "a",
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "Z"}}, "tick"],
              "on": {"Z": "b"}},
        "b": {"entry": [{"type": "raise", "params": {"event": "Z"}}, "tick"],
              "on": {"Z": "a"}},
    },
}


def mk(spec, mi, counter, kind):
    s = json.loads(json.dumps(spec))
    s["maxIterations"] = mi

    def tick_def(i, c, e, a):  # noqa: ANN001
        counter[0] += 1

    async def tick_async(i, c, e, a):  # noqa: ANN001
        counter[0] += 1

    return create_machine(
        s,
        logic=MachineLogic(
            actions={"tick": tick_def if kind == "def" else tick_async}
        ),
    )


async def lane_async(spec, mi, kind):
    n = [0]
    i = Interpreter(mk(spec, mi, n, kind))
    try:
        await i.start()
    except RunawayChainError:
        pass
    await asyncio.sleep(0.3)
    err = type(i.last_error).__name__ if i.last_error else None
    if i.status == "running":
        await i.stop()
    return n[0], err


def lane_sync(spec, mi):
    n = [0]
    i = SyncInterpreter(mk(spec, mi, n, "def"))
    try:
        i.start()
    except RunawayChainError:
        pass
    err = type(i.last_error).__name__ if i.last_error else None
    if i.status == "running":
        i.stop()
    return n[0], err


SYNC = {}


def sync_pass():
    for name, spec in (("S1", S1), ("S2", S2), ("S3", S3), ("S4", S4)):
        for mi in range(1, 26):
            SYNC[(name, mi)] = lane_sync(spec, mi)


async def main():
    print(f"X10 kind={KIND} -- #215 lap parity sweep, limits 1..25")
    for name, spec, desc in (
        ("S1", S1, "PINNED  raise+on / always"),
        ("S2", S2, "VARIANT raise+always / on+always"),
        ("S3", S3, "always-only cycle"),
        ("S4", S4, "raise-only cycle"),
    ):
        bad = []
        rows = []
        for mi in range(1, 26):
            sn, se = SYNC[(name, mi)]
            an, ae = await lane_async(spec, mi, "async")
            dn, de = await lane_async(spec, mi, "def")
            rows.append((mi, sn, dn, an))
            if not (sn == dn == an):
                bad.append((mi, sn, dn, an))
        print(f"\n   {name} {desc}")
        print(f"     limit: (sync, async-def, async-async)")
        print("     " + "  ".join(
            f"{r[0]}:({r[1]},{r[2]},{r[3]})" for r in rows[:10]))
        print(f"     disagreements over 1..25 = {len(bad)}")
        if bad:
            print(f"     first 6 = {bad[:6]}")
        print(f"     VERDICT {name} parity = {'PASS' if not bad else 'FAIL'}")


sync_pass()
asyncio.run(main())
