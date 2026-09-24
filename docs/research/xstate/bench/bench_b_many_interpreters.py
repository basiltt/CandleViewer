# -----------------------------------------------------------------------------
# bench_b_many_interpreters.py — (b) 1k / 10k concurrent interpreters
# -----------------------------------------------------------------------------
"""One interpreter per order, each receiving 100 events.

Measures:
  * construction + start cost per interpreter
  * wall time to push and drain 100 events x N interpreters
  * RSS delta (psutil) and Python-heap delta (tracemalloc) per interpreter
  * teardown cost

Run as:  python bench_b_many_interpreters.py [N] [trace|notrace]
Each N runs in a FRESH process so memory numbers are not polluted.

⚠️ Methodology note: `tracemalloc` costs ~3.5x on this workload (measured —
compare the `trace` and `notrace` rows). TIMING numbers must be read from the
`notrace` run; MEMORY numbers from the `trace` run.
"""

from __future__ import annotations

import asyncio
import gc
import subprocess
import sys
import time
import tracemalloc
from typing import Any, Dict, List

import common
from xstate_statemachine import Interpreter

EVENTS_PER_ORDER = 100


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 1024**2


async def run(n_interp: int, trace: bool = True) -> Dict[str, Any]:
    events = common.oms_event_cycle(EVENTS_PER_ORDER)

    gc.collect()
    if trace:
        tracemalloc.start()
        base_tm = tracemalloc.get_traced_memory()[0]
    else:
        base_tm = 0
    base_rss = rss_mb()

    # --- construction ---------------------------------------------------
    t0 = time.perf_counter()
    machines = [common.oms_machine() for _ in range(n_interp)]
    t_machines = time.perf_counter() - t0

    t0 = time.perf_counter()
    interps: List[Any] = [Interpreter(m) for m in machines]
    t_ctor = time.perf_counter() - t0

    t0 = time.perf_counter()
    await asyncio.gather(*(i.start() for i in interps))
    t_start = time.perf_counter() - t0

    after_start_rss = rss_mb()
    after_start_tm = tracemalloc.get_traced_memory()[0] if trace else 0

    # --- event storm ----------------------------------------------------
    total_events = n_interp * EVENTS_PER_ORDER

    async def feed(i: Any) -> None:
        for e in events:
            await i.send(e)

    t0 = time.perf_counter()
    await asyncio.gather(*(feed(i) for i in interps))
    t_enqueue = time.perf_counter() - t0

    # drain: every machine must have processed its 100 events (+1 initial entry)
    target = EVENTS_PER_ORDER + 1
    deadline = time.perf_counter() + 600
    while True:
        remaining = sum(1 for i in interps if i.context["events"] < target)
        if remaining == 0:
            break
        if time.perf_counter() > deadline:
            raise TimeoutError(f"{remaining} interpreters not drained")
        await asyncio.sleep(0.001)
    t_total = time.perf_counter() - t0

    peak_rss = rss_mb()
    tm_cur, tm_peak = tracemalloc.get_traced_memory() if trace else (0, 0)

    # --- teardown -------------------------------------------------------
    t0 = time.perf_counter()
    await asyncio.gather(*(i.stop() for i in interps))
    t_stop = time.perf_counter() - t0

    if trace:
        tracemalloc.stop()
    del interps, machines
    gc.collect()
    after_gc_rss = rss_mb()

    return {
        "n_interpreters": n_interp,
        "tracemalloc_enabled": trace,
        "events_per_interpreter": EVENTS_PER_ORDER,
        "total_events": total_events,
        "create_machine_s": t_machines,
        "create_machine_us_each": t_machines / n_interp * 1e6,
        "interpreter_ctor_s": t_ctor,
        "interpreter_ctor_us_each": t_ctor / n_interp * 1e6,
        "start_s": t_start,
        "start_us_each": t_start / n_interp * 1e6,
        "enqueue_s": t_enqueue,
        "drain_total_s": t_total,
        "aggregate_events_per_sec": total_events / t_total,
        "us_per_event": t_total / total_events * 1e6,
        "stop_s": t_stop,
        "stop_us_each": t_stop / n_interp * 1e6,
        "rss_baseline_mb": base_rss,
        "rss_after_start_mb": after_start_rss,
        "rss_peak_mb": peak_rss,
        "rss_after_teardown_gc_mb": after_gc_rss,
        "rss_per_idle_interpreter_kb": (after_start_rss - base_rss)
        * 1024
        / n_interp,
        "rss_leak_after_teardown_mb": after_gc_rss - base_rss,
        "tracemalloc_after_start_kb_each": (after_start_tm - base_tm)
        / 1024
        / n_interp,
        "tracemalloc_peak_mb": tm_peak / 1024**2,
        "tracemalloc_current_end_mb": tm_cur / 1024**2,
    }


def main() -> None:
    if len(sys.argv) > 1:
        n = int(sys.argv[1])
        trace = (sys.argv[2] if len(sys.argv) > 2 else "trace") == "trace"
        tag = "trace" if trace else "notrace"
        common.report(
            f"b_{n}_interpreters_{tag}", asyncio.run(run(n, trace))
        )
        return
    # 🧪 orchestrate: one fresh process per N for clean memory accounting
    common.report("machine_specs", common.machine_specs())
    for n in (1_000, 10_000):
        for mode in ("notrace", "trace"):
            print(f"\n--- fresh process: N={n} mode={mode} ---", flush=True)
            subprocess.run(
                [sys.executable, __file__, str(n), mode], check=True
            )


if __name__ == "__main__":
    main()
