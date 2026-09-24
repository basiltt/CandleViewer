# -*- coding: utf-8 -*-
"""R7/G1 -- SUPERSEDED BY g4 (harness bug: kind "async_def" did not
match the `== "async"` branch, so BOTH rows ran a plain `def` service).
Kept for the audit trail. Real result is in g4.

Original intent: the #168 invoke-cycle budget trips for a plain-`def` service but
NOT for an `async def` service.

The library's own #168 test (tests/test_round6_findings.py) uses a plain `def`
service, which resolves INSIDE the entering macrostep (`_processing` True), so
`_enqueue_priority` charges it to the chain budget. An `async def` service is
awaited as a task and its completion lands when the loop is idle
(`_processing` False) -- free. Our catalogue mandates `async def` everywhere
(CV-C32), so every contract invoke cycle is on the uncharged path.

Same machine, same lap counter, two service kinds. Budget = 50.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "cyc",
    "initial": "idle",
    "maxIterations": 50,
    "states": {
        "idle": {"on": {"GO": "ver"}},
        "ver": {"invoke": {"id": "ver", "src": "svc", "onDone": "#cyc.arm"}},
        "arm": {"invoke": {"id": "arm", "src": "svc", "onDone": "#cyc.ver"}},
    },
}


class Drops:
    def __init__(self) -> None:
        self.d = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.d.append(reason)

    def __getattr__(self, _n):  # tolerate the rest of PluginBase
        return lambda *a, **k: None


async def run(kind: str, budget_s: float = 3.0) -> dict:
    laps = {"n": 0}

    if kind == "async":

        async def svc(i, c, e):  # noqa: ANN001
            laps["n"] += 1
            return 1

    else:

        def svc(i, c, e):  # noqa: ANN001
            laps["n"] += 1
            return 1

    m = create_machine(CFG, logic=MachineLogic(services={"svc": svc}))
    d = Drops()
    interp = Interpreter(m)
    interp.use(d)
    await interp.start()
    await interp.send("GO")
    t0 = time.time()
    while time.time() - t0 < budget_s:
        await asyncio.sleep(0.05)
        if not interp.last_transition_ok:
            break
    out = {
        "service_kind": kind,
        "elapsed_s": round(time.time() - t0, 2),
        "laps": laps["n"],
        "budget_maxIterations": 50,
        "tripped": not interp.last_transition_ok,
        "last_error": type(interp.last_error).__name__
        if interp.last_error
        else None,
        "dropped_reasons": d.d[:3],
        "states": sorted(interp.current_state_ids),
    }
    await interp.stop()
    return out


async def main() -> None:
    res = [await run("plain_def"), await run("async_def")]
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    import logging

    logging.disable(logging.ERROR)
    sys.exit(asyncio.run(main()))
