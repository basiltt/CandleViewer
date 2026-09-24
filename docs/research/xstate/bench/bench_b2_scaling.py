# -----------------------------------------------------------------------------
# bench_b2_scaling.py — why does aggregate throughput collapse with N?
# -----------------------------------------------------------------------------
"""Follow-up probe on (b).

bench_b showed ~30k ev/s for ONE interpreter but only ~5.3k ev/s aggregate
across 1,000. This isolates the cause:

  1. Aggregate throughput vs N (1, 10, 100, 500, 1000).
  2. Whether a single `MachineNode` can be SHARED across interpreters
     (create_machine costs ~1.1 ms each — 11 s for 10k orders otherwise).
  3. Whether context is shared (aliasing bug risk) when the node is shared.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import common
from xstate_statemachine import Interpreter

EVENTS = 100


async def aggregate(n: int, shared_machine: bool) -> Dict[str, Any]:
    events = common.oms_event_cycle(EVENTS)
    if shared_machine:
        m = common.oms_machine()
        t0 = time.perf_counter()
        interps = [Interpreter(m) for _ in range(n)]
        build_s = time.perf_counter() - t0
    else:
        t0 = time.perf_counter()
        interps = [Interpreter(common.oms_machine()) for _ in range(n)]
        build_s = time.perf_counter() - t0

    await asyncio.gather(*(i.start() for i in interps))

    async def feed(i: Any) -> None:
        for e in events:
            await i.send(e)

    t0 = time.perf_counter()
    await asyncio.gather(*(feed(i) for i in interps))
    target = EVENTS + 1
    while any(i.context["events"] < target for i in interps):
        await asyncio.sleep(0.0005)
    dt = time.perf_counter() - t0

    ctx_shared = False
    if n > 1:
        ctx_shared = interps[0].context is interps[1].context
    counts = sorted({i.context["events"] for i in interps})
    await asyncio.gather(*(i.stop() for i in interps))

    return {
        "n": n,
        "shared_machine_node": shared_machine,
        "build_s": build_s,
        "build_us_each": build_s / n * 1e6,
        "drain_s": dt,
        "aggregate_ev_per_sec": n * EVENTS / dt,
        "per_interp_ev_per_sec": EVENTS / dt,
        "context_object_shared_between_interpreters": ctx_shared,
        "distinct_event_counts": counts[:5],
    }


async def batched_send(n: int) -> Dict[str, Any]:
    """Does `send_events` (batch enqueue) beat per-event `await send()`?"""
    events = common.oms_event_cycle(EVENTS)
    m = common.oms_machine()
    interps = [Interpreter(common.oms_machine()) for _ in range(n)]
    await asyncio.gather(*(i.start() for i in interps))
    t0 = time.perf_counter()
    await asyncio.gather(*(i.send_events(list(events)) for i in interps))
    target = EVENTS + 1
    while any(i.context["events"] < target for i in interps):
        await asyncio.sleep(0.0005)
    dt = time.perf_counter() - t0
    await asyncio.gather(*(i.stop() for i in interps))
    return {
        "n": n,
        "mode": "send_events batch",
        "drain_s": dt,
        "aggregate_ev_per_sec": n * EVENTS / dt,
    }


async def main() -> None:
    out: Dict[str, Any] = {}
    for n in (1, 10, 100, 500, 1000):
        out[f"own_machine_n{n}"] = await aggregate(n, shared_machine=False)
    for n in (100, 1000):
        try:
            out[f"shared_machine_n{n}"] = await aggregate(
                n, shared_machine=True
            )
        except Exception as exc:
            out[f"shared_machine_n{n}"] = {"error": repr(exc)}
    for n in (100, 1000):
        out[f"batched_n{n}"] = await batched_send(n)
    common.report("b2_scaling_probe", out)


if __name__ == "__main__":
    asyncio.run(main())
