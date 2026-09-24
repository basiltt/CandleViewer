# -----------------------------------------------------------------------------
# bench_f_sync_vs_async.py — (f) SyncInterpreter vs async Interpreter
# -----------------------------------------------------------------------------
"""Throughput comparison on the identical OMS machine.

SyncInterpreter processes an event to completion inside `send()` — no queue,
no event loop. That makes it the right engine for CandleViewer's *rule
evaluation* path (pure, CPU-bound, called from inside an already-async tick
handler) and the wrong one for anything that must `invoke` a coroutine.

Also measures the sync engine under a "many machines" shape equivalent to (b),
and records which features the sync engine refuses.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import common
from xstate_statemachine import Interpreter, SyncInterpreter

WARMUP = 2_000


def bench_sync_single(n: int) -> Dict[str, Any]:
    interp = SyncInterpreter(common.oms_machine()).start()
    events = common.oms_event_cycle(n)
    t0 = time.perf_counter()
    for e in events:
        interp.send(e)
    dt = time.perf_counter() - t0
    processed = interp.context["events"]
    interp.stop()
    return {
        "events": n,
        "processed": processed,
        "total_s": dt,
        "events_per_sec": n / dt,
        "us_per_event": dt / n * 1e6,
    }


def bench_sync_latency(n: int) -> Dict[str, Any]:
    """Per-send latency — in the sync engine send() == full transition."""
    interp = SyncInterpreter(common.oms_machine()).start()
    events = common.oms_event_cycle(n)
    lat: List[float] = []
    for e in events:
        t0 = time.perf_counter()
        interp.send(e)
        lat.append((time.perf_counter() - t0) * 1e6)
    interp.stop()
    return {"events": n, "latency_us": common.summarize(lat)}


def bench_sync_many(n_machines: int, events_each: int) -> Dict[str, Any]:
    events = common.oms_event_cycle(events_each)
    t0 = time.perf_counter()
    interps = [
        SyncInterpreter(common.oms_machine()).start()
        for _ in range(n_machines)
    ]
    build = time.perf_counter() - t0
    t0 = time.perf_counter()
    for i in interps:
        for e in events:
            i.send(e)
    dt = time.perf_counter() - t0
    for i in interps:
        i.stop()
    total = n_machines * events_each
    return {
        "machines": n_machines,
        "events_each": events_each,
        "build_s": build,
        "build_us_each": build / n_machines * 1e6,
        "total_s": dt,
        "aggregate_events_per_sec": total / dt,
        "us_per_event": dt / total * 1e6,
    }


async def bench_async_single(n: int) -> Dict[str, Any]:
    interp = await Interpreter(common.oms_machine()).start()
    events = common.oms_event_cycle(n)
    base = interp.context["events"]
    t0 = time.perf_counter()
    for e in events:
        await interp.send(e)
    deadline = time.perf_counter() + 120
    while interp.context["events"] < base + n:
        if time.perf_counter() > deadline:
            break
        await asyncio.sleep(0)
    dt = time.perf_counter() - t0
    await interp.stop()
    return {
        "events": n,
        "total_s": dt,
        "events_per_sec": n / dt,
        "us_per_event": dt / n * 1e6,
    }


def sync_feature_probe() -> Dict[str, Any]:
    """What does SyncInterpreter refuse? Record it rather than assume."""
    from xstate_statemachine import MachineLogic, create_machine

    out: Dict[str, Any] = {}

    # --- invoked async service ------------------------------------------
    cfg = {
        "id": "svc",
        "initial": "loading",
        "context": {},
        "states": {
            "loading": {
                "invoke": {
                    "src": "fetch",
                    "onDone": "ok",
                    "onError": "bad",
                }
            },
            "ok": {"type": "final"},
            "bad": {"type": "final"},
        },
    }

    async def fetch(i, ctx, e):
        return 1

    try:
        s = SyncInterpreter(
            create_machine(cfg, logic=MachineLogic(services={"fetch": fetch}))
        ).start()
        out["async_service_in_sync_engine"] = (
            f"accepted, states={sorted(s.current_state_ids)}"
        )
        s.stop()
    except Exception as exc:
        out["async_service_in_sync_engine"] = f"{type(exc).__name__}: {exc}"

    # --- `after` timer ---------------------------------------------------
    tcfg = {
        "id": "t",
        "initial": "w",
        "context": {},
        "states": {
            "w": {"after": {50: {"target": "f"}}},
            "f": {"type": "final"},
        },
    }
    try:
        s = SyncInterpreter(create_machine(tcfg, logic=MachineLogic())).start()
        before = sorted(s.current_state_ids)
        time.sleep(0.2)
        after = sorted(s.current_state_ids)
        out["after_timer_in_sync_engine"] = {
            "immediately": before,
            "after_200ms_wall": after,
            "timer_fired_without_event_pump": before != after,
        }
        s.stop()
    except Exception as exc:
        out["after_timer_in_sync_engine"] = f"{type(exc).__name__}: {exc}"

    return out


async def main() -> None:
    common.report("machine_specs", common.machine_specs())
    bench_sync_single(WARMUP)
    await bench_async_single(WARMUP)

    out: Dict[str, Any] = {}
    out["sync_single_50000"] = bench_sync_single(50_000)
    out["async_single_50000"] = await bench_async_single(50_000)
    out["sync_latency_5000"] = bench_sync_latency(5_000)
    out["sync_many_1000x100"] = bench_sync_many(1_000, 100)
    out["speedup_sync_over_async"] = (
        out["sync_single_50000"]["events_per_sec"]
        / out["async_single_50000"]["events_per_sec"]
    )
    out["sync_feature_probe"] = sync_feature_probe()
    common.report("f_sync_vs_async", out)


if __name__ == "__main__":
    asyncio.run(main())
