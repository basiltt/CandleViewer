"""D3c -- the ABORT race: a pure scheduling perturbation changes the OUTCOME.

D3/P1 produced 3 distinct final contexts from an identical event script under
service jitter alone. D3b showed that with no competing exit transition the
outcome is stable but the plugin-hook ORDER moves. This isolates the case where
the outcome itself moves: an event that LEAVES the invoking state races the
service's completion.

The only variable is how many `await asyncio.sleep(0)` turns the service burns.
Nothing about the machine, the event script, or the (simulated) clock changes.
A replay engine that re-feeds a recorded script therefore cannot reproduce the
recorded run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(
    0, "<workspace>/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

CFG = {
    "id": "race",
    "initial": "idle",
    "context": {"filled": 0, "aborted": 0},
    "states": {
        "idle": {"on": {"ORDER": {"target": "working"}}},
        "working": {
            "invoke": {
                "id": "exec",
                "src": "execute",
                "onDone": {"target": "idle", "actions": ["filled"]},
            },
            "on": {"ABORT": {"target": "idle", "actions": ["aborted"]}},
        },
    },
}

# ORDER, then one loop turn later ABORT. Both are ordinary external sends.
SCRIPT = ["ORDER", "ABORT"] * 20


async def run(yields, gap):
    def filled(i, c, e, a):
        c["filled"] += 1

    def aborted(i, c, e, a):
        c["aborted"] += 1

    async def execute(i, c, e):
        for _ in range(yields):
            await asyncio.sleep(0)
        return {"px": 1}

    m = create_machine(
        CFG,
        logic=MachineLogic(
            actions={"filled": filled, "aborted": aborted},
            services={"execute": execute},
        ),
    )
    interp = Interpreter(m, clock=SimulatedClock())
    await interp.start()
    for _ in range(20):
        await interp.send("ORDER")
        # ⏳ the ONLY other variable: how many loop turns the *producer*
        #    waits before cancelling. A real market feed's inter-arrival
        #    gap is not under the replay engine's control.
        for _ in range(gap):
            await asyncio.sleep(0)
        await interp.send("ABORT")
    for _ in range(20_000):
        await asyncio.sleep(0)
    out = dict(interp.context)
    await interp.stop()
    return out


if __name__ == "__main__":
    print("script: 20x (ORDER, <gap loop turns>, ABORT)")
    print("variables: service `sleep(0)` turns, producer gap turns")
    print("Neither is machine logic; both are pure asyncio scheduling.\n")
    seen = {}
    print(f"{'gap':>4} |" + "".join(f"{y:>16}" for y in range(0, 8)))
    print("     |" + "-" * (16 * 8))
    for gap in range(0, 8):
        row = []
        for y in range(0, 8):
            ctx = asyncio.run(run(y, gap))
            key = json.dumps(ctx, sort_keys=True)
            seen.setdefault(key, []).append((gap, y))
            row.append(f"{ctx['filled']:>2}f/{ctx['aborted']:<2}a")
        print(f"{gap:>4} |" + "".join(f"{c:>16}" for c in row))
    print(f"\ndistinct outcomes for one fixed event script: {len(seen)}")
    for k, v in sorted(seen.items()):
        print(f"  {k}  <- {len(v)} (gap,yields) combos, e.g. {v[:4]}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d3c_race.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in seen.items()}, f, indent=2)
