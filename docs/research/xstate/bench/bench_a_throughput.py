# -----------------------------------------------------------------------------
# bench_a_throughput.py — (a) events/sec through a single async Interpreter
# -----------------------------------------------------------------------------
"""Single-interpreter throughput for the 5-state OMS machine (guards+actions).

Three modes are measured because they answer different questions:

  * burst      : enqueue N events, then wait for the queue to drain. Upper
                 bound on engine throughput (amortises loop scheduling).
  * lockstep   : send one event, await until it is processed, repeat. This is
                 the shape of a real order flow where the caller needs the
                 post-transition state before continuing. Gives per-event
                 latency.
  * raw_send   : cost of `send()` alone (enqueue only, no processing).

Also benchmarks the pure/no-interpreter API as a floor.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import common
from xstate_statemachine import Interpreter

WARMUP = 2_000


async def _drain(interp: Any, target: int, timeout: float = 120.0) -> None:
    """Wait until the machine's `events` counter reaches `target`."""
    deadline = time.perf_counter() + timeout
    while interp.context["events"] < target:
        if time.perf_counter() > deadline:
            raise TimeoutError(
                f"drain timeout at {interp.context['events']}/{target}"
            )
        await asyncio.sleep(0)


async def bench_burst(n: int) -> Dict[str, Any]:
    interp = await Interpreter(common.oms_machine()).start()
    events = common.oms_event_cycle(n)
    base = interp.context["events"]

    t0 = time.perf_counter()
    for e in events:
        await interp.send(e)
    t_enqueued = time.perf_counter()
    await _drain(interp, base + n)
    t1 = time.perf_counter()

    await interp.stop()
    return {
        "events": n,
        "enqueue_s": t_enqueued - t0,
        "total_s": t1 - t0,
        "events_per_sec": n / (t1 - t0),
        "us_per_event": (t1 - t0) / n * 1e6,
    }


async def bench_lockstep(n: int) -> Dict[str, Any]:
    interp = await Interpreter(common.oms_machine()).start()
    events = common.oms_event_cycle(n)
    lat: List[float] = []
    processed = interp.context["events"]

    t0 = time.perf_counter()
    for e in events:
        processed += 1
        s = time.perf_counter()
        await interp.send(e)
        await _drain(interp, processed, timeout=10.0)
        lat.append((time.perf_counter() - s) * 1e6)
    t1 = time.perf_counter()

    await interp.stop()
    return {
        "events": n,
        "total_s": t1 - t0,
        "events_per_sec": n / (t1 - t0),
        "latency_us": common.summarize(lat),
    }


async def bench_raw_send(n: int) -> Dict[str, Any]:
    """Enqueue-only cost: how fast can a producer hand events off?"""
    interp = await Interpreter(common.oms_machine()).start()
    ev = {"type": "AMEND", "qty": 1.0}
    t0 = time.perf_counter()
    for _ in range(n):
        await interp.send(ev)
    t1 = time.perf_counter()
    # let it drain before stopping so teardown isn't measured
    await asyncio.sleep(0)
    await interp.stop()
    return {
        "events": n,
        "enqueue_per_sec": n / (t1 - t0),
        "us_per_send": (t1 - t0) / n * 1e6,
    }


def bench_pure(n: int) -> Dict[str, Any]:
    """`get_next_snapshot` — no interpreter, no queue, no asyncio."""
    from xstate_statemachine import get_initial_snapshot, get_next_snapshot

    machine = common.oms_machine()
    snap = get_initial_snapshot(machine)
    events = common.oms_event_cycle(n)
    t0 = time.perf_counter()
    for e in events:
        snap = get_next_snapshot(machine, snap, e)
    t1 = time.perf_counter()
    return {
        "events": n,
        "events_per_sec": n / (t1 - t0),
        "us_per_event": (t1 - t0) / n * 1e6,
        "final_states": sorted(getattr(snap, "state_ids", []) or []),
    }


async def main() -> None:
    common.report("machine_specs", common.machine_specs())

    # 🔥 warm up the interpreter code paths / JIT-free CPython caches
    await bench_burst(WARMUP)

    results: Dict[str, Any] = {}
    for n in (10_000, 50_000):
        results[f"burst_{n}"] = await bench_burst(n)
    results["lockstep_5000"] = await bench_lockstep(5_000)
    results["raw_send_50000"] = await bench_raw_send(50_000)
    try:
        results["pure_api_50000"] = bench_pure(50_000)
    except Exception as exc:
        results["pure_api_50000"] = {"error": repr(exc)}

    common.report("a_single_interpreter_throughput", results)


if __name__ == "__main__":
    asyncio.run(main())
