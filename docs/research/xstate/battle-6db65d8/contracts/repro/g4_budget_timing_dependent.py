# -*- coding: utf-8 -*-
"""R7/G4 -- the #168 async chain budget for invoke cycles is TIMING-dependent,
not structural.

Identical machine (`ver -> arm -> ver`, maxIterations=50), identical service.
The only difference is whether the loop was allowed to go IDLE between
`start()` and the `GO` that enters the cycle.

  hot   : await start(); await send("GO")                -> trips at ~52 laps
  idle  : await start(); await sleep(50ms); send("GO")   -> UNBOUNDED

Root cause: `_enqueue_priority` charges a completion to `_raise_depth` only
`if self._processing`. When the cycle runs at steady state the loop is idle
each time an `async def` service's `done.invoke` lands, so `_processing` is
False, the completion is free, and `_raise_depth` never leaves 0. The library's
own #168 test hits the `hot` path (no sleep after `start()`), which is why it
passes while the real contract machine spins for ever.

A production interpreter is idle between laps by definition. `hot` is the
artificial case.
"""
from __future__ import annotations

import asyncio
import json
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "cyc",
    "maxIterations": 50,
    "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "#cyc.ver"}},
        "ver": {"invoke": {"id": "ver", "src": "svc", "onDone": "#cyc.arm"}},
        "arm": {"invoke": {"id": "arm", "src": "svc", "onDone": "#cyc.ver"}},
    },
}
BUDGET = 2.0


class Drops:
    def __init__(self) -> None:
        self.d = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.d.append(reason)

    def __getattr__(self, _n):
        return lambda *a, **k: None


async def run(kind: str, idle_before_go: float) -> dict:
    laps = {"n": 0}

    if kind == "async":

        async def svc(i, c, e):  # noqa: ANN001
            laps["n"] += 1
            return 1

    else:

        def svc(i, c, e):  # noqa: ANN001
            laps["n"] += 1
            return 1

    interp = Interpreter(create_machine(CFG, logic=MachineLogic(services={"svc": svc})))
    d = Drops()
    interp.use(d)
    await interp.start()
    if idle_before_go:
        await asyncio.sleep(idle_before_go)
    await interp.send("GO")
    t0 = time.monotonic()
    depths = []
    while time.monotonic() - t0 < BUDGET:
        await asyncio.sleep(0.02)
        depths.append(interp._raise_depth)
        if not interp.last_transition_ok:
            break
    out = {
        "service_kind": kind,
        "idle_before_go_s": idle_before_go,
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
    res = [
        await run("async", 0.0),
        await run("async", 0.05),
        await run("plain_def", 0.0),
        await run("plain_def", 0.05),
    ]
    print(json.dumps(res, indent=1))
    json.dump(res, open("repro/g4_budget_timing_dependent.json", "w"), indent=1)


if __name__ == "__main__":
    import logging

    logging.disable(logging.ERROR)
    asyncio.run(main())
