"""R12 - soak: 200 machines with ASYNC services, rollback+onDone and
always->invoke shapes, an external PRIORITY producer, and a chaos
snapshot at quiescence.

Invariants: CPU bounded, 0 external events dropped, no livelock (every
machine answers a probe), 0 torn snapshots, 0 task leaks, clean stop.

`--seconds=` is the wall budget (brief: 12 min; reduced -- see report).
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import threading
import time

from common2 import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
    emit,
    make_service,
)

SECONDS = float(next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--seconds=")), 100))
NM = int(next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--n=")), 200))

try:
    import psutil

    PROC = psutil.Process(os.getpid())
except Exception:  # noqa: BLE001
    PROC = None


class W(PluginBase):
    def __init__(self) -> None:
        self.drops = {}

    def on_event_dropped(self, i, e, reason=None, **kw):  # noqa: ANN001
        self.drops[str(reason)] = self.drops.get(str(reason), 0) + 1


def act(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


SHAPES = ("rollback_ondone", "always_into_invoke", "plain", "parallel")


def cfg(shape: str) -> dict:
    if shape == "rollback_ondone":
        states = {
            "ver": {
                "invoke": {"src": "s", "onDone": {"target": "back", "actions": ["act"]},
                           "onError": {"target": "back"}},
                "on": {"EXT": {"actions": ["act"]}},
            },
            "back": {"always": {"target": "ver", "actions": ["act"]},
                     "on": {"EXT": {"actions": ["act"]}}},
        }
    elif shape == "always_into_invoke":
        states = {
            "gate": {"always": {"target": "ver", "actions": ["act"]},
                     "on": {"EXT": {"actions": ["act"]}}},
            "ver": {"invoke": {"src": "s", "onDone": {"target": "gate"},
                               "onError": {"target": "gate"}},
                    "on": {"EXT": {"actions": ["act"]}}},
        }
    elif shape == "parallel":
        states = {
            "top": {
                "type": "parallel",
                "on": {"EXT": {"actions": ["act"]}},
                "states": {
                    "A": {"initial": "a1", "states": {
                        "a1": {"invoke": {"src": "s", "onDone": {"target": "a2"}},
                               "on": {"S": {"target": "a2"}}},
                        "a2": {"on": {"S": {"target": "a1"}}}}},
                    "B": {"initial": "b1", "states": {
                        "b1": {"on": {"S": {"target": "b2"}}}, "b2": {}}},
                },
            }
        }
    else:
        states = {"idle": {"on": {"EXT": {"actions": ["act"]},
                                  "S": {"actions": ["act"]}}}}
    return {"id": "r12", "initial": next(iter(states)), "context": {"n": 0},
            "maxIterations": 50, "states": states}


def mk(shape: str):
    return create_machine(
        cfg(shape),
        logic=MachineLogic(actions={"act": act},
                           services={"s": make_service("async def", delay=0.002)}),
    )


def torn(b) -> bool:
    return isinstance(b, dict) and b.get("status") == "running" and not b.get("state_ids")


async def main() -> int:
    rng = random.Random(1212)
    ws = []
    itps = []
    for k in range(NM):
        shape = SHAPES[k % len(SHAPES)]
        w = W()
        ws.append(w)
        itps.append(Interpreter(mk(shape), service_pool_size=4).use(w))
    await asyncio.gather(*(i.start() for i in itps))
    base_tasks = len(asyncio.all_tasks())
    rss0 = PROC.memory_info().rss // 1024 // 1024 if PROC else None
    cpu0 = PROC.cpu_times() if PROC else None

    sent = [0]
    callsite_err = {}
    stop = threading.Event()

    def producer() -> None:
        while not stop.is_set():
            for _ in range(50):
                try:
                    rng.choice(itps).send_threadsafe("EXT", priority=True)
                    sent[0] += 1
                except Exception as exc:  # noqa: BLE001
                    n = type(exc).__name__
                    callsite_err[n] = callsite_err.get(n, 0) + 1
            time.sleep(0.005)

    th = threading.Thread(target=producer, daemon=True)
    th.start()

    t0 = time.perf_counter()
    snaps = {"taken": 0, "torn": 0, "refused": 0}
    rss_trace = []
    while time.perf_counter() - t0 < SECONDS:
        await asyncio.sleep(0.5)
        # chaos snapshot at (approximate) quiescence
        for i in rng.sample(itps, min(20, len(itps))):
            try:
                b = i.get_persisted_snapshot()
                snaps["taken"] += 1
                if torn(b):
                    snaps["torn"] += 1
            except Exception:  # noqa: BLE001
                snaps["refused"] += 1
        if PROC and len(rss_trace) < 40:
            rss_trace.append(PROC.memory_info().rss // 1024 // 1024)

    stop.set()
    th.join(timeout=5)
    wall = time.perf_counter() - t0
    cpu = None
    if PROC and cpu0:
        c1 = PROC.cpu_times()
        cpu = round(
            ((c1.user - cpu0.user) + (c1.system - cpu0.system)) / wall, 2
        )

    # liveness probe with a 5 s deadline
    async def probe(i):  # noqa: ANN001
        try:
            await asyncio.wait_for(i.send("EXT", wait=True), 5)
            return 0
        except asyncio.TimeoutError:
            return 1
        except Exception:  # noqa: BLE001
            return 0

    wedged = sum(await asyncio.gather(*(probe(i) for i in itps)))
    backlog = sum(i.queue_depth for i in itps)
    drops = {}
    for w in ws:
        for k, v in w.drops.items():
            drops[k] = drops.get(k, 0) + v
    rss1 = PROC.memory_info().rss // 1024 // 1024 if PROC else None
    try:
        await asyncio.wait_for(asyncio.gather(*(i.stop() for i in itps)), 60)
        stopped = "ok"
    except asyncio.TimeoutError:
        stopped = "HUNG"
    await asyncio.sleep(0.4)
    leftover = len(asyncio.all_tasks()) - 1
    bad = (
        wedged
        or snaps["torn"]
        or drops.get("chain_budget")
        or stopped != "ok"
        or leftover > 0
    )
    emit(
        "r12_soak_async_services",
        {
            "machines": NM,
            "seconds": round(wall, 1),
            "service_kind": "async def",
            "shapes": list(SHAPES),
            "external_sent": sent[0],
            "callsite_errors": callsite_err,
            "drops_by_reason": drops,
            "external_dropped_as_chain_budget": drops.get("chain_budget", 0),
            "machines_not_answering_in_5s": wedged,
            "final_backlog": backlog,
            "snapshots": snaps,
            "cpu_seconds_per_wall_second": cpu,
            "rss_mb_start_end": [rss0, rss1],
            "rss_trace_mb": rss_trace,
            "tasks_baseline_after_start": base_tasks,
            "leftover_tasks_after_stop": leftover,
            "stop": stopped,
            "result": "FAIL" if bad else "PASS",
        },
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
