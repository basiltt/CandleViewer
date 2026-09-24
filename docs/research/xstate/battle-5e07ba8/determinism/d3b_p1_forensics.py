"""D3b -- P1 forensics: why does a pure asyncio-scheduling perturbation change
the trace, and why does `ok` stay 0?

D3/P1 showed 3 distinct final contexts under jitter alone. This drills in with
a small script and a full drain, printing the per-run trace so the divergence
can be attributed to a mechanism rather than to a short drain.
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
    PluginBase,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

CFG = {
    "id": "p1b",
    "initial": "idle",
    "context": {"ok": 0, "n": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "busy"}, "TICK": {"actions": ["n"]}}},
        "busy": {
            "invoke": {
                "id": "svc",
                "src": "work",
                "onDone": {"target": "idle", "actions": ["ok"]},
            },
            "on": {"TICK": {"actions": ["n"]}, "ABORT": {"target": "idle"}},
        },
    },
}


class Hooks(PluginBase):
    def __init__(self, t):
        self.t = t

    def on_event_received(self, i, e):
        self.t.append(("recv", e.type))

    def on_transition(self, i, f, to, tr):
        self.t.append(("trans", tr.event, tuple(sorted(s.id for s in to))))

    def on_service_start(self, i, inv):
        self.t.append(("svc_start", inv.id))

    def on_service_done(self, i, inv, r):
        self.t.append(("svc_done", inv.id))


async def run(script, yields):
    """`yields` = exactly how many `sleep(0)` turns the service burns."""
    trace = []

    def n(i, c, e, a):
        trace.append(("act:n", e.type))
        c["n"] += 1

    def ok(i, c, e, a):
        trace.append(("act:ok", e.type))
        c["ok"] += 1

    async def work(i, c, e):
        for _ in range(yields):
            await asyncio.sleep(0)
        return {"v": c["n"]}

    m = create_machine(
        CFG,
        logic=MachineLogic(actions={"n": n, "ok": ok}, services={"work": work}),
    )
    interp = Interpreter(m, clock=SimulatedClock())
    interp.use(Hooks(trace))
    await interp.start()
    for t in script:
        await interp.send(t)
    for _ in range(20_000):
        await asyncio.sleep(0)
    out = (trace, dict(interp.context), sorted(interp.current_state_ids))
    await interp.stop()
    return out


SCRIPT = ["GO", "TICK", "TICK", "TICK", "TICK", "TICK", "TICK"]

if __name__ == "__main__":
    print("script:", SCRIPT)
    print("Only the number of loop turns the SERVICE burns varies.\n")
    rows = {}
    for y in range(0, 10):
        trace, ctx, state = asyncio.run(run(SCRIPT, y))
        key = json.dumps([ctx, state], sort_keys=True)
        rows.setdefault(key, []).append(y)
        print(f"  yields={y}: ctx={ctx} state={state}")
        print(f"            trace={trace}")
    print(f"\ndistinct (context,state) outcomes: {len(rows)}")
    for k, v in rows.items():
        print(f"  {k}  <- yields {v}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d3b_p1.json"), "w", encoding="utf-8") as f:
        json.dump({"outcomes": {k: v for k, v in rows.items()}}, f, indent=2)
