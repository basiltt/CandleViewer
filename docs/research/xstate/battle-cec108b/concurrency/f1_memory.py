"""(f) GC / memory: tracemalloc over 1M events across 100 machines.

Growth must be flat. 100 interpreters share one `MachineNode`; events are
round-robined over them in batches, with a tracemalloc sample after every
batch so the shape of the curve -- not just the endpoints -- is visible.

Reported per sample: traced KiB, RSS KiB (psutil), live asyncio task count,
gc object count, and the interpreters' aggregate `queue_depth`. A leak that
only shows under a specific feature would hide behind a plain PING machine,
so three machine shapes are run:

  M1  plain self-transition (the throughput baseline)
  M2  two states ping-ponging, each with entry/exit actions
  M3  a machine that `raise`s an internal event per external event
      (exercises the internal queue and the chain-budget bookkeeping)

Also reported: the top tracemalloc allocation sites between the first and
last sample, so a real leak can be attributed to a line rather than merely
observed.

Usage: python f1_memory.py [total_events] [n_machines] [batches]
"""

from __future__ import annotations

import asyncio
import gc
import linecache
import sys
import tracemalloc

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine

try:
    import psutil

    _PROC = psutil.Process()
except Exception:  # noqa: BLE001
    _PROC = None


def bump(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


M1 = {
    "id": "m1",
    "initial": "idle",
    "context": {"n": 0},
    "states": {"idle": {"on": {"PING": {"actions": ["bump"]}}}},
}

M2 = {
    "id": "m2",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "entry": ["bump"],
            "exit": ["bump"],
            "on": {"PING": {"target": "b", "actions": ["bump"]}},
        },
        "b": {
            "entry": ["bump"],
            "exit": ["bump"],
            "on": {"PING": {"target": "a", "actions": ["bump"]}},
        },
    },
}

M3 = {
    "id": "m3",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "PING": {"actions": [{"type": "raise", "params": {"event": "INNER"}}]},
                "INNER": {"actions": ["bump"]},
            }
        }
    },
}

SHAPES = {"m1_plain": M1, "m2_entry_exit": M2, "m3_internal_raise": M3}


#: tracemalloc frame depth; see the note in `run_shape`.
TRACE_DEPTH = int(
    next((a.split("=")[1] for a in sys.argv if a.startswith("--depth=")), 4)
)


def _rss_kib() -> float:
    if _PROC is None:
        return -1.0
    return _PROC.memory_info().rss / 1024


async def run_shape(name: str, cfg: dict, total: int, n_machines: int, batches: int):
    machine = create_machine(cfg, logic=MachineLogic(actions={"bump": bump}))
    interps = [Interpreter(machine) for _ in range(n_machines)]
    await asyncio.gather(*(i.start() for i in interps))

    # Warm up so first-touch allocations are not counted as growth.
    for k in range(n_machines * 20):
        await interps[k % n_machines].send("PING")
    while any(i.queue_depth for i in interps):
        await asyncio.sleep(0.005)
    gc.collect()
    await asyncio.sleep(0.05)

    # 🔬 Frame depth is a real cost at this event count: at depth 15 the
    #    1M-event run itself grew to >4 GiB of tracemalloc bookkeeping and had
    #    to be killed -- the INSTRUMENT, not the engine. Depth 4 is enough to
    #    attribute an allocation to a library line, which is all the
    #    `top_alloc_diff` table is read for.
    tracemalloc.start(TRACE_DEPTH)
    first = tracemalloc.take_snapshot()
    samples = []
    per_batch = total // batches
    sent = 0
    for b in range(batches):
        for k in range(per_batch):
            await interps[(sent + k) % n_machines].send("PING")
        sent += per_batch
        while any(i.queue_depth for i in interps):
            await asyncio.sleep(0.002)
        gc.collect()
        await asyncio.sleep(0.01)
        cur, peak = tracemalloc.get_traced_memory()
        samples.append(
            {
                "batch": b + 1,
                "events_sent": sent,
                "traced_kib": round(cur / 1024, 1),
                "traced_peak_kib": round(peak / 1024, 1),
                "rss_kib": round(_rss_kib(), 1),
                "gc_objects": len(gc.get_objects()),
                "asyncio_tasks": len(asyncio.all_tasks()),
                "queue_depth_total": sum(i.queue_depth for i in interps),
            }
        )

    last = tracemalloc.take_snapshot()
    diff = last.compare_to(first, "lineno")[:8]
    top = []
    for st in diff:
        f = st.traceback[0]
        top.append(
            {
                "where": f"{f.filename.split('site-packages')[-1]}:{f.lineno}",
                "size_diff_kib": round(st.size_diff / 1024, 1),
                "count_diff": st.count_diff,
                "line": (linecache.getline(f.filename, f.lineno) or "").strip()[:90],
            }
        )
    tracemalloc.stop()

    for i in interps:
        await i.stop(drain=True, timeout=30)
    gc.collect()
    await asyncio.sleep(0.05)

    a, z = samples[0], samples[-1]
    span_events = z["events_sent"] - a["events_sent"]
    return {
        "machines": n_machines,
        "events": total,
        "context_n_total": None,
        "samples": samples,
        "traced_kib_first": a["traced_kib"],
        "traced_kib_last": z["traced_kib"],
        "traced_growth_kib": round(z["traced_kib"] - a["traced_kib"], 1),
        "traced_bytes_per_event": round(
            (z["traced_kib"] - a["traced_kib"]) * 1024 / span_events, 4
        )
        if span_events
        else None,
        "rss_growth_kib": round(z["rss_kib"] - a["rss_kib"], 1),
        "gc_objects_growth": z["gc_objects"] - a["gc_objects"],
        "asyncio_task_growth": z["asyncio_tasks"] - a["asyncio_tasks"],
        "top_alloc_diff": top,
    }


async def main():
    pos = [a for a in sys.argv[1:] if not a.startswith("-")]
    total = int(pos[0]) if pos else 1_000_000
    n_machines = int(pos[1]) if len(pos) > 1 else 100
    batches = int(pos[2]) if len(pos) > 2 else 20
    res = {}
    for name, cfg in SHAPES.items():
        res[name] = await run_shape(name, cfg, total, n_machines, batches)
    emit("f1_memory", res)


if __name__ == "__main__":
    asyncio.run(main())
