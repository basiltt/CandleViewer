# -----------------------------------------------------------------------------
# bench_e_actors.py — (e) actor spawn / teardown cost
# -----------------------------------------------------------------------------
"""Cost of the actor model: spawning child machines and tearing them down.

CandleViewer shape: one parent "trade group" / algo supervisor machine that
spawns a child per leg (OCO legs, TWAP slices, iceberg clips), then stops
them. Measures spawn cost, send-to-child cost, and parent-stop teardown.
"""

from __future__ import annotations

import asyncio
import gc
import time
from typing import Any, Dict, List

import common
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CHILD = {
    "id": "leg",
    "initial": "idle",
    "context": {"jobs": 0},
    "states": {
        "idle": {"on": {"JOB": {"target": "idle", "actions": ["count"]}}}
    },
}


def child_logic() -> MachineLogic:
    def count(i: Any, ctx: Dict[str, Any], e: Any, a: Any) -> None:
        ctx["jobs"] += 1

    return MachineLogic(actions={"count": count})


def parent_machine(n_children: int) -> Any:
    entry = [
        {
            "type": "spawnChild",
            "params": {
                "src": "leg",
                "id": f"leg{k}",
                "systemId": f"leg{k}",
            },
        }
        for k in range(n_children)
    ]
    cfg = {
        "id": "algo",
        "initial": "up",
        "context": {},
        "states": {
            "up": {
                "entry": entry,
                "on": {
                    "DISPATCH": {
                        "actions": [
                            {
                                "type": "sendTo",
                                "params": {
                                    "to": "leg0",
                                    "event": {"type": "JOB"},
                                },
                            }
                        ]
                    }
                },
            }
        },
    }
    logic = MachineLogic(
        services={
            "leg": lambda i, ctx, e: create_machine(
                dict(CHILD), logic=child_logic()
            )
        }
    )
    return create_machine(cfg, logic=logic)


async def spawn_teardown(n_children: int, reps: int) -> Dict[str, Any]:
    spawn_us: List[float] = []
    stop_us: List[float] = []
    ok = True
    for _ in range(reps):
        interp = Interpreter(parent_machine(n_children))
        t0 = time.perf_counter()
        await interp.start()
        # children are spawned by the entry action of the initial state
        await asyncio.sleep(0)
        spawn_us.append((time.perf_counter() - t0) / n_children * 1e6)
        if len(list(interp.system.get_all())) != n_children:
            ok = False
        t0 = time.perf_counter()
        await interp.stop()
        stop_us.append((time.perf_counter() - t0) / n_children * 1e6)
    return {
        "children": n_children,
        "reps": reps,
        "spawn_us_per_child": common.summarize(spawn_us),
        "teardown_us_per_child": common.summarize(stop_us),
        "all_children_registered": ok,
    }


async def send_to_child(n_msgs: int) -> Dict[str, Any]:
    interp = await Interpreter(parent_machine(4)).start()
    await asyncio.sleep(0.01)
    t0 = time.perf_counter()
    for _ in range(n_msgs):
        await interp.send("DISPATCH")
    deadline = time.perf_counter() + 60
    child = interp.system.get("leg0")
    while child.context["jobs"] < n_msgs:
        if time.perf_counter() > deadline:
            break
        await asyncio.sleep(0.001)
    dt = time.perf_counter() - t0
    delivered = child.context["jobs"]
    await interp.stop()
    return {
        "messages": n_msgs,
        "delivered_to_child": delivered,
        "all_delivered": delivered == n_msgs,
        "total_s": dt,
        "parent_to_child_msgs_per_sec": delivered / dt if dt else None,
        "us_per_forwarded_msg": dt / delivered * 1e6 if delivered else None,
    }


async def leak_check(n_children: int, cycles: int) -> Dict[str, Any]:
    """Spawn/teardown repeatedly — does anything accumulate?"""
    import psutil

    proc = psutil.Process()
    gc.collect()
    before = proc.memory_info().rss / 1024**2
    for _ in range(cycles):
        interp = await Interpreter(parent_machine(n_children)).start()
        await asyncio.sleep(0)
        await interp.stop()
        del interp
    gc.collect()
    after = proc.memory_info().rss / 1024**2
    return {
        "cycles": cycles,
        "children_each": n_children,
        "rss_before_mb": before,
        "rss_after_mb": after,
        "rss_growth_mb": after - before,
        "rss_growth_kb_per_actor": (after - before)
        * 1024
        / (cycles * n_children),
    }


async def main() -> None:
    common.report("machine_specs", common.machine_specs())
    out: Dict[str, Any] = {}
    out["spawn_4_children"] = await spawn_teardown(4, 200)
    out["spawn_50_children"] = await spawn_teardown(50, 40)
    out["send_to_child_10000"] = await send_to_child(10_000)
    out["leak_check"] = await leak_check(10, 300)
    common.report("e_actor_spawn_teardown", out)


if __name__ == "__main__":
    asyncio.run(main())
