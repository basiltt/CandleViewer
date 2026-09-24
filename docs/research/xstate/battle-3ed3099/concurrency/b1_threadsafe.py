"""(b) send_threadsafe() from 32 OS threads into one interpreter.

Target rate 20,000 ev/s sustained. Per-event accounting:

    attempted == accepted_future_ok + raised_on_calling_thread
    accepted  == processed + dropped_hook + still_queued

Also checks:
  * ordering: events carry a per-thread monotonic seq; the machine records
    arrival order. Per-thread order MUST be preserved (FIFO per producer);
    global interleaving is expected.
  * `strict` is applied on the calling thread (#78): one deliberate typo'd
    event per thread must raise UnknownEventError there.
  * loop responsiveness while 32 threads hammer it (see g1 for the full
    latency study).

Usage: python b1_threadsafe.py [n_threads] [events_per_thread] [target_rate]
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import threading
import time

from common import Accountant, emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    UnknownEventError,
    create_machine,
)

CFG = {
    "id": "ts",
    "initial": "idle",
    "context": {"n": 0, "last": {}, "order_violations": 0},
    "strict": True,
    "states": {"idle": {"on": {"PING": {"actions": ["rec"]}}}},
}


def rec(interpreter, ctx, event, action_def):  # noqa: ANN001
    p = event.payload
    tid, seq = p["tid"], p["seq"]
    prev = ctx["last"].get(tid, -1)
    if seq <= prev:
        ctx["order_violations"] += 1
    ctx["last"][tid] = seq
    ctx["n"] += 1


async def run(n_threads: int, per_thread: int, target_rate: int):
    m = create_machine(CFG, logic=MachineLogic(actions={"rec": rec}))
    acc = Accountant()
    interp = Interpreter(m)
    interp.use(acc)
    await interp.start()

    loop = asyncio.get_running_loop()
    stats = {
        "attempted": 0,
        "future_ok": 0,
        "raised": 0,
        "strict_raised": 0,
        "unexpected": [],
    }
    slock = threading.Lock()
    start_barrier = threading.Barrier(n_threads + 1)
    per_thread_delay = (n_threads / target_rate) if target_rate else 0.0

    def producer(tid: int):
        a = ok = raised = strict_r = 0
        unexpected = []
        start_barrier.wait()
        next_t = time.perf_counter()
        for seq in range(per_thread):
            # one deliberate undeclared event per thread, mid-run (#78)
            if seq == per_thread // 2:
                try:
                    interp.send_threadsafe("PIGN", tid=tid, seq=seq)
                    unexpected.append("typo accepted")
                except UnknownEventError:
                    strict_r += 1
                except Exception as exc:  # noqa: BLE001
                    unexpected.append(f"typo -> {type(exc).__name__}")
            a += 1
            try:
                interp.send_threadsafe("PING", tid=tid, seq=seq)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                raised += 1
                unexpected.append(f"{type(exc).__name__}: {exc}")
            next_t += per_thread_delay
            # Pacing. Windows `time.sleep()` granularity is ~1-15 ms, much
            # coarser than the 1.6 ms inter-send interval that 20k ev/s over
            # 32 threads implies, so pace only when the slack is worth a
            # syscall; otherwise free-run. `target_rate=0` disables pacing
            # entirely (max-rate mode).
            if per_thread_delay:
                slack = next_t - time.perf_counter()
                if slack > 0.002:
                    time.sleep(slack)
        with slock:
            stats["attempted"] += a
            stats["future_ok"] += ok
            stats["raised"] += raised
            stats["strict_raised"] += strict_r
            stats["unexpected"] += unexpected[:3]

    threads = [
        threading.Thread(target=producer, args=(t,), name=f"prod-{t}")
        for t in range(n_threads)
    ]
    for t in threads:
        t.start()

    # Loop-responsiveness sampler on the asyncio side.
    gaps: list[float] = []
    sampling = {"v": True}

    async def sampler():
        last = time.perf_counter()
        while sampling["v"]:
            await asyncio.sleep(0)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    samp = asyncio.create_task(sampler())
    start_barrier.wait()
    t0 = time.perf_counter()
    while any(t.is_alive() for t in threads):
        await asyncio.sleep(0.005)
    for t in threads:
        t.join()
    produce_s = time.perf_counter() - t0
    sampling["v"] = False
    await samp

    # Give the loop time to drain everything accepted.
    deadline = time.perf_counter() + 120
    while interp.queue_depth and time.perf_counter() < deadline:
        await asyncio.sleep(0.01)
    await interp.stop(drain=True, timeout=60)

    gaps_ms = sorted(g * 1000 for g in gaps)
    emit(
        "b1_threadsafe",
        {
            "n_threads": n_threads,
            "events_per_thread": per_thread,
            "target_rate_ev_s": target_rate,
            "attempted": stats["attempted"],
            "accepted_future_ok": stats["future_ok"],
            "raised_on_calling_thread": stats["raised"],
            "strict_typo_rejected_on_calling_thread": stats["strict_raised"],
            "strict_typos_sent": n_threads,
            "processed_hook": len(acc.received),
            "context_n": interp.context["n"],
            "per_thread_order_violations": interp.context["order_violations"],
            "dropped_hook": acc.dropped[:5],
            "dropped_hook_count": len(acc.dropped),
            "unaccounted_lost": stats["future_ok"]
            - interp.context["n"]
            - len(acc.dropped),
            "achieved_rate_ev_s": round(stats["attempted"] / produce_s, 1),
            "produce_s": round(produce_s, 3),
            "loop_turn_gap_ms_p50": round(statistics.median(gaps_ms), 4)
            if gaps_ms
            else None,
            "loop_turn_gap_ms_p999": round(gaps_ms[int(len(gaps_ms) * 0.999)], 4)
            if gaps_ms
            else None,
            "loop_turn_gap_ms_max": round(gaps_ms[-1], 4) if gaps_ms else None,
            "unexpected_sample": stats["unexpected"][:10],
        },
    )


if __name__ == "__main__":
    nt = int(sys.argv[1]) if len(sys.argv) > 1 else 32
    pt = int(sys.argv[2]) if len(sys.argv) > 2 else 2500
    tr = int(sys.argv[3]) if len(sys.argv) > 3 else 20000
    asyncio.run(run(nt, pt, tr))
