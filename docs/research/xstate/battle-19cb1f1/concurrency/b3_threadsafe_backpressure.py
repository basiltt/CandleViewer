"""(b/g) `send_threadsafe` has no backpressure and no bound that works.

Observed while building g1: 32 free-running threads calling
`send_threadsafe` into 100 interpreters never terminate -- `queue_depth`
grows monotonically and the post-window drain never completes.

This is not a bug by itself (an unbounded queue plus a faster producer is
arithmetic), but two properties make it worth pinning:

  1. The loop-side ingest cost is ~87 us/event (b2), so a single loop
     saturates at roughly 11k ev/s of `send_threadsafe` -- well under the
     20k ev/s this track targets, and under what 32 threads produce
     trivially. The producer gets no signal at all: `send_threadsafe`
     returns a `concurrent.futures.Future` that resolves as soon as the
     event is QUEUED, which under overload is essentially immediately.

  2. `max_queue_size` does NOT protect the cross-thread path in the way a
     caller would expect. `send_threadsafe` schedules `_enqueue()` onto the
     loop (interpreter.py:911-914); the bound is therefore evaluated on the
     LOOP, after the calling thread has already returned. Under RAISE the
     `QueueOverflowError` is raised inside the scheduled coroutine, so it
     surfaces on the returned future -- which the documented usage
     (`interp.send_threadsafe("X")`, result never read) never inspects.
     The event is refused, and the producing thread is not told.

V1  unbounded: watch queue_depth over a fixed window, 32 threads
V2  bounded + RAISE: where does the QueueOverflowError land?
V3  bounded + DROP_NEWEST: is the drop hooked? (it should be)
"""

from __future__ import annotations

import asyncio
import threading
import time

from common import Accountant, counter_machine, emit
from xstate_statemachine import Interpreter
from xstate_statemachine.models import OverflowPolicy

N_THREADS = 32
WINDOW_S = 2.0


async def v1_unbounded():
    i = Interpreter(counter_machine())
    await i.start()
    stop = threading.Event()
    sent = [0] * N_THREADS

    def producer(tid):
        while not stop.is_set():
            i.send_threadsafe("PING")
            sent[tid] += 1

    ts = [threading.Thread(target=producer, args=(t,)) for t in range(N_THREADS)]
    for t in ts:
        t.start()
    depths = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < WINDOW_S:
        await asyncio.sleep(0.1)
        depths.append(i.queue_depth)
    stop.set()
    for t in ts:
        t.join()
    accepted = sum(sent)
    backlog = i.queue_depth
    t1 = time.perf_counter()
    while i.queue_depth and time.perf_counter() - t1 < 60:
        await asyncio.sleep(0.01)
    drain_s = time.perf_counter() - t1
    out = {
        "threads": N_THREADS,
        "window_s": WINDOW_S,
        "accepted_by_send_threadsafe": accepted,
        "processed_during_window": i.context["n"],
        "queue_depth_samples_every_100ms": depths,
        "backlog_at_window_end": backlog,
        "drain_after_producers_stopped_s": round(drain_s, 3),
        "monotonically_growing": all(
            b >= a for a, b in zip(depths, depths[1:])
        ),
    }
    await i.stop(drain=True, timeout=120)
    return out


async def v_bounded(policy: OverflowPolicy, cap: int = 100):
    acc = Accountant()
    i = Interpreter(counter_machine(), max_queue_size=cap, overflow_policy=policy)
    i.use(acc)
    await i.start()
    stop = threading.Event()
    sent = 0
    raised_on_thread = 0
    futures = []
    lock = threading.Lock()

    def producer(tid):
        nonlocal sent, raised_on_thread
        local_sent = local_raised = 0
        local_futs = []
        for _ in range(200):
            if stop.is_set():
                break
            try:
                f = i.send_threadsafe("PING")
                local_sent += 1
                local_futs.append(f)
            except Exception:  # noqa: BLE001
                local_raised += 1
        with lock:
            sent += local_sent
            raised_on_thread += local_raised
            futures.extend(local_futs)

    ts = [threading.Thread(target=producer, args=(t,)) for t in range(N_THREADS)]
    for t in ts:
        t.start()
    await asyncio.sleep(1.0)
    stop.set()
    for t in ts:
        t.join()
    await asyncio.sleep(0.5)

    fut_errors = {}
    unresolved = 0
    for f in futures:
        if not f.done():
            unresolved += 1
            continue
        exc = f.exception()
        key = type(exc).__name__ if exc else "ok"
        fut_errors[key] = fut_errors.get(key, 0) + 1

    out = {
        "policy": policy.value,
        "cap": cap,
        "calls_returned_without_raising_on_calling_thread": sent,
        "raised_on_calling_thread": raised_on_thread,
        "future_outcomes": fut_errors,
        "futures_unresolved": unresolved,
        "processed": i.context["n"],
        "on_event_dropped_hook_count": len(acc.dropped),
        "queue_depth": i.queue_depth,
        "note": (
            "under RAISE the QueueOverflowError lands on a future the "
            "documented usage never reads; the producing thread sees nothing."
        ),
    }
    await i.stop(drain=True, timeout=60)
    return out


async def main():
    emit(
        "b3_threadsafe_backpressure",
        {
            "v1_unbounded": await v1_unbounded(),
            "v2_bounded_raise": await v_bounded(OverflowPolicy.RAISE),
            "v3_bounded_drop_newest": await v_bounded(OverflowPolicy.DROP_NEWEST),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
