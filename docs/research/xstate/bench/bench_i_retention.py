# -----------------------------------------------------------------------------
# bench_i_retention.py — is the post-teardown RSS a leak or allocator retention?
# -----------------------------------------------------------------------------
"""bench_b showed ~16 MB (N=1k) / ~80 MB (N=10k) of RSS still held after every
interpreter was stopped, dereferenced and gc'd — ~8 KB per interpreter.

That could be (1) a real reference leak in the library, or (2) CPython/OS
allocator arenas not returned to the OS, which is harmless. This distinguishes
them by running the same create/teardown cycle REPEATEDLY: a real leak grows
without bound across cycles, retention plateaus.

Also checks for surviving references via gc.
"""

from __future__ import annotations

import asyncio
import gc
import sys
from typing import Any, Dict, List

import common
from xstate_statemachine import Interpreter


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 1024**2


async def cycle(n: int) -> None:
    interps = [Interpreter(common.oms_machine()) for _ in range(n)]
    await asyncio.gather(*(i.start() for i in interps))
    events = common.oms_event_cycle(20)
    for i in interps:
        for e in events:
            await i.send(e)
    while any(i.context["events"] < 21 for i in interps):
        await asyncio.sleep(0.001)
    await asyncio.gather(*(i.stop() for i in interps))
    del interps
    gc.collect()


async def main() -> None:
    common.report("machine_specs", common.machine_specs())
    N = 1_000
    marks: List[float] = []
    gc.collect()
    marks.append(rss_mb())
    for c in range(5):
        await cycle(N)
        gc.collect()
        marks.append(rss_mb())

    # 🔍 are any Interpreter objects still reachable?
    gc.collect()
    live = [o for o in gc.get_objects() if isinstance(o, Interpreter)]

    deltas = [round(marks[i + 1] - marks[i], 2) for i in range(len(marks) - 1)]
    common.report(
        "i_retention",
        {
            "interpreters_per_cycle": N,
            "cycles": 5,
            "rss_after_each_cycle_mb": [round(m, 2) for m in marks],
            "per_cycle_growth_mb": deltas,
            "first_cycle_growth_mb": deltas[0],
            "last_cycle_growth_mb": deltas[-1],
            "plateaus": abs(deltas[-1]) < abs(deltas[0]) / 2,
            "verdict": (
                "allocator retention (plateaus)"
                if abs(deltas[-1]) < abs(deltas[0]) / 2
                else "UNBOUNDED GROWTH — investigate as a leak"
            ),
            "live_interpreter_objects_after_gc": len(live),
            "gc_garbage_len": len(gc.garbage),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
