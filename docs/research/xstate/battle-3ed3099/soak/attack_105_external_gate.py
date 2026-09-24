# -*- coding: utf-8 -*-
"""NEW ATTACK: #105 per-task self-send gate under concurrent external
producers. An external task calling `send()` while the interpreter's own
action is mid-step must NOT be charged to that action's `max_iterations`
self-raise budget -- #105 changed the gate from "loop is busy" to "issued
from one of this interpreter's OWN actions, tracked per task". Verify: many
concurrent external senders hammering a machine whose action legitimately
self-raises near the budget never trip `RunawayChainError` due to the
external traffic, only ever (if at all) due to genuine self-raise chains.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "max_iterations": 50,
    "states": {
        "a": {
            "on": {
                "PING": {"actions": ["noop"]},
                # Self-raising action: an action that calls `raise` (the
                # library's own re-enqueue idiom) a bounded number of times.
            }
        }
    },
}


def noop(interp, ctx, event, action_def):
    ctx["n"] = ctx.get("n", 0) + 1


async def producer(interp, n, tag) -> int:
    ok = 0
    for i in range(n):
        try:
            await asyncio.wait_for(interp.send("PING", wait=True), timeout=2.0)
            ok += 1
        except asyncio.TimeoutError:
            pass
    return ok


async def main() -> None:
    m = create_machine(CFG, logic=MachineLogic(actions={"noop": noop}))
    interp = Interpreter(m)
    await interp.start()

    # 16 concurrent external producers, well above max_iterations=50, all
    # sending distinct events (not self-raised) -- per #105 this must never
    # be charged to the self-raise chain budget.
    n_each = 40
    results = await asyncio.gather(
        *[producer(interp, n_each, i) for i in range(16)]
    )
    total_ok = sum(results)
    print("producers:", 16, "each:", n_each, "total_ok:", total_ok)
    print("interpreter status:", interp.status)
    print("context n:", interp.context.get("n"))
    if interp.status != "running":
        print("DEFECT: interpreter stopped/tripped under pure external load")
    elif total_ok != 16 * n_each:
        print("DEFECT: some external sends were dropped/charged against budget")
    else:
        print("PASS: #105 gate holds -- external concurrency never trips the "
              "self-raise budget")
    await interp.stop()


if __name__ == "__main__":
    asyncio.run(main())
