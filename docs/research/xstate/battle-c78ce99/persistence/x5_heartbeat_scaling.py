# -*- coding: utf-8 -*-
"""X5 -- scaling probe: is the 1 ms `raise(delay=)` heartbeat CPU-bounded
BY THE CLOCK, or does the engine saturate a core?

STANDALONE. Neutral cwd. X4/A showed cpu/wall == 1.00 at both 20 and 200
machines, so this ladders the machine count and the period and reports the
ACHIEVED beat rate against the NOMINAL one. A heartbeat "bounded by the
clock" should achieve ~1 beat/period/machine until the CPU runs out; the
point at which achieved << nominal is the real capacity number a wrapper
has to size against.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

KIND = os.environ.get("XS_SVC", "async")
SECS = float(os.environ.get("XS_SECS", "3"))

SPEC = {
    "id": "hb",
    "initial": "a",
    "context": {"beats": 0},
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "T", "delay": 1}},
                        "beat"],
              "on": {"T": "b"}},
        "b": {"entry": [{"type": "raise", "params": {"event": "T", "delay": 1}},
                        "beat"],
              "on": {"T": "a"}},
    },
}

AFTER_SPEC = {
    "id": "hb2",
    "initial": "a",
    "context": {"beats": 0},
    "states": {
        "a": {"entry": ["beat"], "after": {"1": "b"}},
        "b": {"entry": ["beat"], "after": {"1": "a"}},
    },
}


def build(spec, period):
    s = json.loads(json.dumps(spec))
    if "after" in s["states"]["a"]:
        s["states"]["a"]["after"] = {str(period): "b"}
        s["states"]["b"]["after"] = {str(period): "a"}
    else:
        s["states"]["a"]["entry"][0]["params"]["delay"] = period
        s["states"]["b"]["entry"][0]["params"]["delay"] = period

    def beat(i, c, e, a):  # noqa: ANN001
        c["beats"] += 1

    async def sa(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    def sd(i, c, e):  # noqa: ANN001
        return 1

    return create_machine(
        s,
        logic=MachineLogic(actions={"beat": beat},
                           services={"s": sa if KIND == "async" else sd}),
    )


def cpu() -> float:
    t = os.times()
    return t.user + t.system


async def rung(spec, label, n, period):
    interps = [Interpreter(build(spec, period)) for _ in range(n)]
    c0, w0 = cpu(), time.monotonic()
    await asyncio.gather(*(i.start() for i in interps))
    await asyncio.sleep(SECS)
    c1, w1 = cpu(), time.monotonic()
    beats = [i.context["beats"] for i in interps]
    await asyncio.gather(*(i.stop() for i in interps if i.status == "running"))
    wall = w1 - w0
    total = sum(beats)
    nominal = n * (wall * 1000.0 / period)
    achieved_period = wall * 1000.0 / (sum(beats) / n) if total else float("inf")
    print(f"   {label:6s} n={n:4d} period={period:4d}ms  beats/machine="
          f"{total / n:8.1f}  achieved_period={achieved_period:7.2f}ms  "
          f"efficiency={total / nominal:5.1%}  cpu/wall={(c1 - c0) / wall:.2f}")
    return total / nominal


async def main():
    print(f"X5 kind={KIND} SECS={SECS}")
    print("=== raise(delay=) heartbeat ladder ===")
    for n in (1, 10, 50, 200):
        await rung(SPEC, "raise", n, 1)
    print("=== after: parity ladder (same shape, `after` spelling) ===")
    for n in (1, 10, 50, 200):
        await rung(AFTER_SPEC, "after", n, 1)
    print("=== longer period (25 ms), the realistic heartbeat ===")
    for n in (200, 1000):
        await rung(SPEC, "raise", n, 25)


asyncio.run(main())
