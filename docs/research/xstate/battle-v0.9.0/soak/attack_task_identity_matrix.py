# -*- coding: utf-8 -*-
"""NEW round-13 attack: task-identity matrix (#225) under concurrency.

Standalone (stdlib + xstate_statemachine only). Verifies that a worker
task spawned FROM an action, which OUTLIVES that action, is treated as
ordinary EXTERNAL traffic (its send() goes through the normal admission
path, not the in-step "am I one of my own actions" fast lane), across
many concurrent spawns -- i.e. no starvation / no misrouting under load.

Shapes covered (async engine; def-service lane covered by attack B):
  1. action -> asyncio.ensure_future(helper) -> helper outlives action -> helper.send()
  2. action -> task -> task -> send() (two hops)
  3. 100 concurrent hand-outs while the spawning actions keep awaiting
     other things (not the handed-out task) after spawn.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from xstate_statemachine import MachineLogic, create_machine

RESULTS: Dict[str, Any] = {"pings": 0, "hop2_pings": 0, "concurrent_pings": 0}

CONFIG = {
    "id": "m",
    "initial": "idle",
    "context": {},
    "states": {
        "idle": {
            "on": {
                "GO1": {"actions": ["spawn_outliving_worker"]},
                "GO2": {"actions": ["spawn_two_hop"]},
                "GO3": {"actions": ["spawn_concurrent"]},
                "PING": {"actions": ["count_ping"]},
                "PING2": {"actions": ["count_hop2"]},
                "PINGC": {"actions": ["count_concurrent"]},
            }
        }
    },
}


async def spawn_outliving_worker(i, ctx, ev, ad):
    async def worker():
        await asyncio.sleep(0.05)  # outlives the action
        i.send("PING")

    asyncio.ensure_future(worker())
    await asyncio.sleep(0.001)  # action returns before worker finishes


async def spawn_two_hop(i, ctx, ev, ad):
    async def hop2():
        await asyncio.sleep(0.02)
        i.send("PING2")

    async def hop1():
        asyncio.ensure_future(hop2())
        await asyncio.sleep(0.005)

    asyncio.ensure_future(hop1())


async def spawn_concurrent(i, ctx, ev, ad):
    async def worker(n):
        await asyncio.sleep(0.01 + (n % 5) * 0.001)
        i.send("PINGC")

    for n in range(100):
        asyncio.ensure_future(worker(n))
    await asyncio.sleep(0.001)


async def count_ping(i, ctx, ev, ad):
    RESULTS["pings"] += 1


async def count_hop2(i, ctx, ev, ad):
    RESULTS["hop2_pings"] += 1


async def count_concurrent(i, ctx, ev, ad):
    RESULTS["concurrent_pings"] += 1


async def main():
    logic = MachineLogic(
        actions={
            "spawn_outliving_worker": spawn_outliving_worker,
            "spawn_two_hop": spawn_two_hop,
            "spawn_concurrent": spawn_concurrent,
            "count_ping": count_ping,
            "count_hop2": count_hop2,
            "count_concurrent": count_concurrent,
        }
    )
    m = create_machine(CONFIG, logic=logic)
    i = m.start_sync() if hasattr(m, "start_sync") else None
    from xstate_statemachine import Interpreter

    i = Interpreter(m)
    await i.start()

    i.send("GO1")
    i.send("GO2")
    i.send("GO3")
    await asyncio.sleep(0.3)
    await i.stop()

    print("outliving-worker pings:", RESULTS["pings"], "(expect 1)")
    print("two-hop pings:", RESULTS["hop2_pings"], "(expect 1)")
    print("concurrent 100-worker pings:", RESULTS["concurrent_pings"], "(expect 100)")
    ok = RESULTS["pings"] == 1 and RESULTS["hop2_pings"] == 1 and RESULTS["concurrent_pings"] == 100
    print("TASK_IDENTITY_MATRIX_OK:", ok)


if __name__ == "__main__":
    asyncio.run(main())
