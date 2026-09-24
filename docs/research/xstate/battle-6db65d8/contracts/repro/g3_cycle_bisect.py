# -*- coding: utf-8 -*-
"""R7/G3 -- bisect which feature lets an async invoke cycle escape the #168
chain budget on 221ce7c.

Variants over the SAME two-state invoke cycle (`ver -> arm -> ver`,
maxIterations=50, async def service):

  base          flat root, default clock
  parallel      root type=parallel with the cycle in one region
  simclock      flat root, SimulatedClock attached
  entryactions  flat root, entry actions on both cycle states
  policies      flat root + the catalogue policy block
  par+sim       parallel root + SimulatedClock  (== the B8 shape)

For each: laps in a 2.5 s budget, whether the budget tripped, and the maximum
`_raise_depth` observed.
"""
from __future__ import annotations

import asyncio
import copy
import json
import time

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock

BUDGET = 2.5

CYCLE = {
    "idle": {"on": {"GO": "#cyc.ver"}},
    "ver": {"invoke": {"id": "ver", "src": "svc", "onDone": "#cyc.arm"}},
    "arm": {"invoke": {"id": "arm", "src": "svc", "onDone": "#cyc.ver"}},
}

BASE = {"id": "cyc", "maxIterations": 50, "initial": "idle", "states": CYCLE}

POLICIES = {
    "actionErrorPolicy": "rollback",
    "onUnhandled": "defer",
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "strict": True,
}


def parallel_cfg() -> dict:
    cyc = json.loads(json.dumps(CYCLE).replace("#cyc.", "#cyc.main."))
    return {
        "id": "cyc",
        "maxIterations": 50,
        "type": "parallel",
        "states": {
            "main": {"initial": "idle", "states": cyc},
            "other": {
                "initial": "a",
                "states": {"a": {"on": {"PING": "b"}}, "b": {}},
            },
        },
    }


def entry_cfg() -> dict:
    c = copy.deepcopy(BASE)
    c["states"]["ver"]["entry"] = ["mark"]
    c["states"]["arm"]["entry"] = ["mark"]
    return c


VARIANTS = {
    "base": (copy.deepcopy(BASE), False),
    "parallel": (parallel_cfg(), False),
    "simclock": (copy.deepcopy(BASE), True),
    "entryactions": (entry_cfg(), False),
    "policies": ({**copy.deepcopy(BASE), **POLICIES}, False),
    "par+sim(B8 shape)": (parallel_cfg(), True),
}


class Drops:
    def __init__(self) -> None:
        self.d = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.d.append(reason)

    def __getattr__(self, _n):
        return lambda *a, **k: None


async def run(name: str, cfg: dict, simclock: bool) -> dict:
    laps = {"n": 0}

    async def svc(i, c, e):  # noqa: ANN001
        laps["n"] += 1
        return 1

    def mark(i, c, e, a):  # noqa: ANN001
        pass

    m = create_machine(
        cfg, logic=MachineLogic(services={"svc": svc}, actions={"mark": mark})
    )
    kw = {}
    if simclock:
        kw = {
            "clock": SimulatedClock(),
            "max_queue_size": 64,
            "overflow_policy": OverflowPolicy.RAISE,
        }
    interp = Interpreter(m, **kw)
    d = Drops()
    interp.use(d)
    await interp.start()
    await asyncio.sleep(0.02)
    await interp.send("GO")
    t0 = time.monotonic()
    depths = []
    while time.monotonic() - t0 < BUDGET:
        await asyncio.sleep(0.02)
        depths.append(interp._raise_depth)
        if not interp.last_transition_ok:
            break
    out = {
        "variant": name,
        "laps": laps["n"],
        "elapsed_s": round(time.monotonic() - t0, 2),
        "tripped": not interp.last_transition_ok,
        "last_error": type(interp.last_error).__name__
        if interp.last_error
        else None,
        "max_raise_depth": max(depths) if depths else None,
        "dropped": d.d[:2],
    }
    await interp.stop()
    return out


async def main() -> None:
    res = [await run(n, c, s) for n, (c, s) in VARIANTS.items()]
    print(json.dumps(res, indent=1))
    json.dump(res, open("repro/g3_cycle_bisect.json", "w"), indent=1)


if __name__ == "__main__":
    import logging

    logging.disable(logging.ERROR)
    asyncio.run(main())
