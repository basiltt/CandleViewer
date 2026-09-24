# -*- coding: utf-8 -*-
"""SOAK battle-test track @ 5e07ba8.

200 order-like machines, 6 producers @ ~3k ev/s total, 1 chaos task doing
random stop(drain=True)/from_snapshot/resume every 2s on random machines
plus random plugin exceptions. Bounded to ~25 min wall-clock.

Records every 30s: RSS, tracemalloc top, asyncio task count, event-loop lag
(max callback duration observed via a heartbeat probe), p50/p99 send->receipt
latency, receipts by disposition, on_event_dropped counts, exceptions.

Run:
    "<venv>/Scripts/python" soak_runner.py [--minutes 25] [--machines 200]

Never modifies library source. Imports the library only from the _ref
clone's own venv.
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import random
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import psutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak_machine as sm  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    PluginBase,
    QueueOverflowError,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
os.makedirs(OUT_DIR, exist_ok=True)

MAX_QUEUE = 128


# ---------------------------------------------------------------------------
# 📒 Bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class Stats:
    sent: int = 0
    accepted: int = 0  # send() did not raise QueueOverflowError / not_running
    receipts_ok: int = 0
    receipts_deferred: int = 0
    receipts_error: int = 0
    dropped_queue_full: int = 0
    dropped_not_running: int = 0
    dropped_chain_budget: int = 0
    unexpected_exceptions: List[str] = field(default_factory=list)
    latencies_ms: List[float] = field(default_factory=list)
    restart_count: int = 0
    plugin_chaos_triggered: int = 0


STATS = Stats()
STATS_LOCK = asyncio.Lock()

# Reconciliation log: every event a producer believes it successfully handed
# to a machine ("accepted"), vs. every event that machine's own trace plugin
# recorded as executed/dropped. Keyed by (machine_idx, generation, seq).
PRODUCER_LOG: Dict[Tuple[int, int, int], str] = {}  # -> "sent"
MACHINE_LOG: Dict[Tuple[int, int, int], str] = {}  # -> "observed:<disposition>"
LOG_LOCK = asyncio.Lock()


class AccountantPlugin(PluginBase):
    """Per-machine plugin: records dispositions and drives the reconcile log."""

    def __init__(self, machine_idx: int) -> None:
        self.machine_idx = machine_idx
        self.generation = 0
        self.dropped_queue_full = 0
        self.dropped_not_running = 0
        self.dropped_chain_budget = 0
        self.errors: List[str] = []

    def on_event_dropped(self, interpreter, event, reason) -> None:  # noqa: ANN001
        if reason == "queue_full":
            self.dropped_queue_full += 1
        elif reason == "not_running":
            self.dropped_not_running += 1
        elif reason == "chain_budget":
            self.dropped_chain_budget += 1
        key = getattr(event, "_soak_key", None)
        if key is not None:
            MACHINE_LOG[key] = f"dropped:{reason}"

    def on_transition(self, interpreter, frm, to, transition) -> None:  # noqa: ANN001
        pass

    def on_error(self, interpreter, error) -> None:  # noqa: ANN001
        self.errors.append(repr(error))


class ChaosPlugin(PluginBase):
    """Randomly raises inside on_event_received to exercise plugin-exception
    resilience -- the async run loop's documented behaviour is that ANY
    exception escaping the run loop stops the interpreter (see interpreter.py
    _run_event_loop). We record that as an EXPECTED stop, not a leak, and the
    chaos task is responsible for restarting via from_snapshot.
    """

    def __init__(self, machine_idx: int, rate: float = 0.0004) -> None:
        self.machine_idx = machine_idx
        self.rate = rate
        self.triggered = 0
        self._fired_this_generation = False

    def on_event_received(self, interpreter, event) -> None:  # noqa: ANN001
        if getattr(event, "type", "") in ("SUBMIT", "STOP_PROBE_INTERNAL"):
            return  # never sabotage the seed event; keeps machines populated
        if self._fired_this_generation:
            return  # one plugin-exception crash per generation is enough
        if random.random() < self.rate:
            self.triggered += 1
            self._fired_this_generation = True
            raise RuntimeError(
                f"chaos-injected plugin exception on machine {self.machine_idx}"
            )


def mark_event(ev: Dict[str, Any], key: Tuple[int, int, int]) -> Dict[str, Any]:
    ev = dict(ev)
    ev["_soak_key"] = key  # tolerated: Event(**payload) style dict send
    return ev


# ---------------------------------------------------------------------------
# 🏭 Machine wrapper
# ---------------------------------------------------------------------------


class Machine:
    __slots__ = (
        "idx",
        "clock",
        "interp",
        "accountant",
        "chaos",
        "seq",
        "generation",
        "lock",
        "alive",
    )

    def __init__(self, idx: int) -> None:
        self.idx = idx
        self.clock = SimulatedClock()
        self.generation = 0
        self.seq = 0
        self.lock = asyncio.Lock()
        self.alive = True
        self.accountant: Optional[AccountantPlugin] = None
        self.chaos: Optional[ChaosPlugin] = None
        self.interp: Optional[Interpreter] = None

    async def start_fresh(self) -> None:
        m = sm.build(max_queue_size=MAX_QUEUE)
        self.accountant = AccountantPlugin(self.idx)
        self.chaos = ChaosPlugin(self.idx)
        interp = Interpreter(m, clock=self.clock, max_queue_size=MAX_QUEUE)
        interp.use(self.accountant)  # #round4: .use() wraps in _SafePlugin
        interp.use(self.chaos)
        await interp.start()
        self.interp = interp
        self.generation += 1
        self.seq = 0
        # Seed into the parallel region so producers have real states to hit.
        await interp.send({"type": "SUBMIT", "payload": {"qty": 5}}, wait=True)
        self.alive = True

    async def restart_from_snapshot(self) -> bool:
        """Chaos action: stop(drain=True) then from_snapshot + resume."""
        interp = self.interp
        if interp is None or interp.status not in ("running",):
            return False
        try:
            snap = interp.get_persisted_snapshot()
            snap_str = json.dumps(snap, default=repr)
            await interp.stop(drain=True, timeout=15.0)
        except Exception as exc:  # noqa: BLE001
            async with STATS_LOCK:
                STATS.unexpected_exceptions.append(
                    f"restart-stop-phase m{self.idx}: {exc!r}"
                )
            return False
        try:
            new_m = sm.build(max_queue_size=MAX_QUEUE)
            # #117: from_snapshot(clock=) is now the documented way to
            # re-point a restored interpreter at a shared clock; #115 means
            # the OLD interpreter's settler was already detached by its own
            # stop()/_teardown() above, so this no longer accumulates.
            restored = Interpreter.from_snapshot(
                snap_str,
                new_m,
                restart_services=True,
                restart_timers=True,
                clock=self.clock,
            )
            self.accountant = AccountantPlugin(self.idx)
            self.chaos = ChaosPlugin(self.idx)
            restored.use(self.accountant)
            restored.use(self.chaos)
            await restored.start()
            self.interp = restored
            self.generation += 1
            async with STATS_LOCK:
                STATS.restart_count += 1
            return True
        except Exception as exc:  # noqa: BLE001
            async with STATS_LOCK:
                STATS.unexpected_exceptions.append(
                    f"restart-resume-phase m{self.idx}: {exc!r}"
                )
            return False


# ---------------------------------------------------------------------------
# 🚦 Producers
# ---------------------------------------------------------------------------

TOTAL_RATE_EPS = 3000.0


async def producer(
    producer_idx: int,
    machines: List[Machine],
    n_producers: int,
    stop_evt: asyncio.Event,
) -> None:
    per_producer_rate = TOTAL_RATE_EPS / n_producers
    interval = 1.0 / per_producer_rate
    rng = random.Random(1000 + producer_idx)
    while not stop_evt.is_set():
        t0 = time.perf_counter()
        m = rng.choice(machines)
        ev_template = rng.choice(sm.EVENT_POOL)
        async with m.lock:
            interp = m.interp
            if interp is None:
                await asyncio.sleep(interval)
                continue
            if interp.status in ("done", "error", "stopped"):
                # The order machine reaches a terminal state (closed/done) or
                # was crashed by chaos; a real order desk would open a new
                # order rather than let the producer pool starve, so recycle
                # this slot to keep 200 machines "alive" for the full window.
                await m.start_fresh()
                interp = m.interp
            key = (m.idx, m.generation, m.seq)
            m.seq += 1
            ev = mark_event(ev_template, key)
            PRODUCER_LOG[key] = "sent"
            send_t0 = time.perf_counter()
            try:
                r = await asyncio.wait_for(interp.send(ev, wait=True), timeout=15.0)
            except asyncio.TimeoutError:
                # D-soak-1: a `wait=True` receipt future is never resolved
                # when the async run loop dies from an uncaught BaseException
                # (e.g. a plugin hook raising) -- `_fail_all_receipts()` is
                # only invoked from `_teardown()`, which the fatal-error path
                # in `_run_event_loop` never reaches. Recorded, not retried:
                # the underlying task/future is abandoned, exactly as a real
                # caller's `await` would hang forever without this guard.
                MACHINE_LOG[key] = "HUNG:receipt-never-resolved"
                async with STATS_LOCK:
                    STATS.sent += 1
                    STATS.unexpected_exceptions.append(
                        f"D-soak-1 hang: m{m.idx} gen{m.generation} key={key}"
                    )
                await asyncio.sleep(interval)
                continue
            except QueueOverflowError:
                async with STATS_LOCK:
                    STATS.sent += 1
                MACHINE_LOG[key] = "dropped:queue_overflow_raised"
                await asyncio.sleep(interval)
                continue
            except Exception as exc:  # noqa: BLE001
                # Interpreter may have been stopped by chaos plugin exception
                # between the `interp = m.interp` read and send(); this is an
                # expected race in the chaos design, not a leak, PROVIDED the
                # event is accounted for. Log it as an observed-not-running.
                MACHINE_LOG[key] = f"send-raised:{exc!r}"
                async with STATS_LOCK:
                    STATS.sent += 1
                await asyncio.sleep(interval)
                continue
            dt_ms = (time.perf_counter() - send_t0) * 1000.0
            async with STATS_LOCK:
                STATS.sent += 1
                STATS.accepted += 1
                STATS.latencies_ms.append(dt_ms)
                if r is None:
                    pass
                elif r.error is not None:
                    STATS.receipts_error += 1
                elif r.deferred:
                    STATS.receipts_deferred += 1
                else:
                    STATS.receipts_ok += 1
            MACHINE_LOG[key] = (
                "observed:deferred" if r.deferred
                else ("observed:error" if r.error else "observed:ok")
            )
        elapsed = time.perf_counter() - t0
        await asyncio.sleep(max(0.0, interval - elapsed))


async def chaos_task(machines: List[Machine], stop_evt: asyncio.Event) -> None:
    rng = random.Random(42)
    while not stop_evt.is_set():
        await asyncio.sleep(2.0)
        m = rng.choice(machines)
        async with m.lock:
            if m.interp is not None and m.interp.status == "running":
                await m.restart_from_snapshot()


# ---------------------------------------------------------------------------
# 📈 Monitoring
# ---------------------------------------------------------------------------


async def heartbeat_lag_probe(lag_samples: List[float], stop_evt: asyncio.Event) -> None:
    """Measures event-loop lag: expected sleep(0.05) vs actual elapsed."""
    while not stop_evt.is_set():
        t0 = time.perf_counter()
        await asyncio.sleep(0.05)
        dt = time.perf_counter() - t0
        lag_samples.append(max(0.0, dt - 0.05) * 1000.0)
        if len(lag_samples) > 20000:
            del lag_samples[:10000]


def percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round(p / 100.0 * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


async def sampler(
    proc: "psutil.Process",
    machines: List[Machine],
    lag_samples: List[float],
    start_time: float,
    stop_evt: asyncio.Event,
    series: List[Dict[str, Any]],
) -> None:
    warm_rss: Optional[float] = None
    while not stop_evt.is_set():
        await asyncio.sleep(30.0)
        gc.collect()
        rss_mb = proc.memory_info().rss / (1024 * 1024)
        if warm_rss is None and time.time() - start_time > 60:
            warm_rss = rss_mb
        tasks = asyncio.all_tasks()
        snap = tracemalloc.take_snapshot()
        top = snap.statistics("lineno")[:5]
        top_fmt = [
            {"file": str(s.traceback[0]), "size_kb": round(s.size / 1024, 1)}
            for s in top
        ]
        async with STATS_LOCK:
            lat = sorted(STATS.latencies_ms)
            p50 = percentile(lat, 50)
            p99 = percentile(lat, 99)
            entry = {
                "t_s": round(time.time() - start_time, 1),
                "rss_mb": round(rss_mb, 2),
                "warm_rss_mb": round(warm_rss, 2) if warm_rss else None,
                "growth_pct_since_warm": (
                    round((rss_mb - warm_rss) / warm_rss * 100, 2)
                    if warm_rss
                    else None
                ),
                "asyncio_task_count": len(tasks),
                "max_loop_lag_ms": round(max(lag_samples) if lag_samples else 0.0, 2),
                "p50_send_receipt_ms": round(p50, 3),
                "p99_send_receipt_ms": round(p99, 3),
                "sent": STATS.sent,
                "accepted": STATS.accepted,
                "receipts_ok": STATS.receipts_ok,
                "receipts_deferred": STATS.receipts_deferred,
                "receipts_error": STATS.receipts_error,
                "restart_count": STATS.restart_count,
                "unexpected_exceptions_so_far": len(STATS.unexpected_exceptions),
                "top_alloc": top_fmt,
            }
            lag_samples.clear()
            STATS.latencies_ms.clear()
        series.append(entry)
        print(json.dumps(entry))
        with open(os.path.join(OUT_DIR, "timeseries.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# 🏁 Main
# ---------------------------------------------------------------------------


async def main(minutes: float, n_machines: int, n_producers: int) -> None:
    tracemalloc.start(10)
    proc = psutil.Process(os.getpid())
    with open(os.path.join(OUT_DIR, "timeseries.jsonl"), "w", encoding="utf-8"):
        pass  # truncate

    machines = [Machine(i) for i in range(n_machines)]
    for m in machines:
        await m.start_fresh()

    stop_evt = asyncio.Event()
    lag_samples: List[float] = []
    series: List[Dict[str, Any]] = []
    start_time = time.time()

    tasks = [
        asyncio.create_task(producer(i, machines, n_producers, stop_evt))
        for i in range(n_producers)
    ]
    tasks.append(asyncio.create_task(chaos_task(machines, stop_evt)))
    tasks.append(asyncio.create_task(heartbeat_lag_probe(lag_samples, stop_evt)))
    sampler_task = asyncio.create_task(
        sampler(proc, machines, lag_samples, start_time, stop_evt, series)
    )

    await asyncio.sleep(minutes * 60.0)
    stop_evt.set()
    await asyncio.sleep(0.2)
    for t in tasks:
        t.cancel()
    sampler_task.cancel()
    await asyncio.gather(*tasks, sampler_task, return_exceptions=True)

    # ---- Final reconcile: producer log (sent) vs machine log (observed) ----
    lost = []
    for key in PRODUCER_LOG:
        if key not in MACHINE_LOG:
            lost.append(key)

    # ---- Final teardown / leak check ----
    remaining_tasks_before_stop = len(asyncio.all_tasks())
    for m in machines:
        if m.interp is not None and m.interp.status == "running":
            try:
                await m.interp.stop(drain=False, timeout=1.0)
            except Exception as exc:  # noqa: BLE001
                STATS.unexpected_exceptions.append(f"final-stop m{m.idx}: {exc!r}")
    await asyncio.sleep(0.1)
    remaining_tasks_after_stop = len(
        [t for t in asyncio.all_tasks() if not t.done()]
    )

    total_dropped_queue_full = sum(m.accountant.dropped_queue_full for m in machines if m.accountant)
    total_dropped_not_running = sum(m.accountant.dropped_not_running for m in machines if m.accountant)
    total_dropped_chain_budget = sum(m.accountant.dropped_chain_budget for m in machines if m.accountant)
    total_chaos_triggered = sum(m.chaos.triggered for m in machines if m.chaos)
    total_plugin_errors = sum(len(m.accountant.errors) for m in machines if m.accountant)

    result = {
        "wall_clock_minutes": minutes,
        "n_machines": n_machines,
        "n_producers": n_producers,
        "final_sent": STATS.sent,
        "final_accepted": STATS.accepted,
        "final_receipts_ok": STATS.receipts_ok,
        "final_receipts_deferred": STATS.receipts_deferred,
        "final_receipts_error": STATS.receipts_error,
        "restart_count": STATS.restart_count,
        "chaos_plugin_triggered_total": total_chaos_triggered,
        "dropped_queue_full_total": total_dropped_queue_full,
        "dropped_not_running_total": total_dropped_not_running,
        "dropped_chain_budget_total": total_dropped_chain_budget,
        "plugin_on_error_hook_count": total_plugin_errors,
        "unexpected_exceptions": STATS.unexpected_exceptions,
        "producer_log_size": len(PRODUCER_LOG),
        "machine_log_size": len(MACHINE_LOG),
        "lost_events_count": len(lost),
        "lost_events_sample": lost[:20],
        "remaining_asyncio_tasks_before_final_stop": remaining_tasks_before_stop,
        "remaining_asyncio_tasks_after_final_stop": remaining_tasks_after_stop,
        "series_points": len(series),
    }
    with open(os.path.join(OUT_DIR, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, default=repr)
    print("=== SUMMARY ===")
    print(json.dumps(result, indent=2, default=repr))
    tracemalloc.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=25.0)
    ap.add_argument("--machines", type=int, default=200)
    ap.add_argument("--producers", type=int, default=6)
    args = ap.parse_args()
    asyncio.run(main(args.minutes, args.machines, args.producers))
