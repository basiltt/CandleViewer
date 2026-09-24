"""(b) send_threadsafe() ingest-cost study: why 20k ev/s is not reached.

b1 shows 32 threads sustaining only ~9.2k ev/s, and 4 threads ~5.1k ev/s,
against a 20k ev/s target -- while the in-loop `send()` path in a1 ran at
~240k ev/s. This probe isolates where the cost sits.

`send_threadsafe` (interpreter.py:871-914) does, per event:
  1. `_prepare_event`  (normalisation)
  2. `_check_strict`   (on the calling thread, #78 -- correct and cheap)
  3. builds a NEW coroutine object `_deliver()`
  4. `asyncio.run_coroutine_threadsafe(...)` -> allocates a
     `concurrent.futures.Future`, wraps it in a `Task`, and does one
     `loop.call_soon_threadsafe` (which takes the loop lock and writes the
     self-pipe, waking the selector).

Step 4 is one full task schedule + one loop wake-up PER EVENT. It is
compared here against the theoretical floor for the same cross-thread hop.

Variants:
  V1  send_threadsafe, N threads, no pacing -- measured ingest rate
  V2  raw `loop.call_soon_threadsafe(noop)` from N threads -- the floor for
      the wake-up alone
  V3  raw `run_coroutine_threadsafe(noop_coro)` from N threads -- the floor
      for the task-per-event design
  V4  in-loop `send()` for the same machine -- the single-thread reference
"""

from __future__ import annotations

import asyncio
import threading
import time

from common import Accountant, counter_machine, emit
from xstate_statemachine import Interpreter

N_THREADS = 32
N_EVENTS = 40_000


def _drive_threads(fn, n_threads: int, n_events: int) -> float:
    per = n_events // n_threads
    barrier = threading.Barrier(n_threads + 1)

    def worker(tid: int):
        barrier.wait()
        for k in range(per):
            fn(tid, k)

    ts = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in ts:
        t.start()
    barrier.wait()
    t0 = time.perf_counter()
    for t in ts:
        t.join()
    return time.perf_counter() - t0


async def main():
    loop = asyncio.get_running_loop()
    res = {}

    # V1: send_threadsafe
    acc = Accountant()
    interp = Interpreter(counter_machine())
    interp.use(acc)
    await interp.start()

    done = threading.Event()

    def v1(tid, k):
        interp.send_threadsafe("PING")

    t = threading.Thread(
        target=lambda: (done.set() if _drive_threads(v1, N_THREADS, N_EVENTS) else None)
    )
    # run the producers off-loop but measure on-loop progress
    holder = {}

    def run_v1():
        holder["dt"] = _drive_threads(v1, N_THREADS, N_EVENTS)
        done.set()

    th = threading.Thread(target=run_v1)
    th.start()
    while not done.is_set():
        await asyncio.sleep(0.005)
    th.join()
    ingest_s = holder["dt"]
    t1 = time.perf_counter()
    while interp.queue_depth:
        await asyncio.sleep(0.005)
    consume_tail_s = time.perf_counter() - t1
    res["v1_send_threadsafe"] = {
        "threads": N_THREADS,
        "events": N_EVENTS,
        "ingest_s": round(ingest_s, 3),
        "ingest_rate_ev_s": round(N_EVENTS / ingest_s, 1),
        "us_per_event": round(ingest_s / N_EVENTS * 1e6, 2),
        "tail_to_drain_s": round(consume_tail_s, 3),
        "processed": interp.context["n"],
    }
    await interp.stop(drain=True, timeout=60)

    # V2: raw call_soon_threadsafe floor
    counter = {"n": 0}

    def bump():
        counter["n"] += 1

    def v2(tid, k):
        loop.call_soon_threadsafe(bump)

    done2 = threading.Event()
    h2 = {}

    def run_v2():
        h2["dt"] = _drive_threads(v2, N_THREADS, N_EVENTS)
        done2.set()

    th2 = threading.Thread(target=run_v2)
    th2.start()
    while not done2.is_set():
        await asyncio.sleep(0.005)
    th2.join()
    while counter["n"] < N_EVENTS:
        await asyncio.sleep(0.005)
    res["v2_call_soon_threadsafe_floor"] = {
        "ingest_s": round(h2["dt"], 3),
        "ingest_rate_ev_s": round(N_EVENTS / h2["dt"], 1),
        "us_per_event": round(h2["dt"] / N_EVENTS * 1e6, 2),
    }

    # V3: raw run_coroutine_threadsafe floor (the design send_threadsafe uses)
    c3 = {"n": 0}

    async def noop():
        c3["n"] += 1

    def v3(tid, k):
        asyncio.run_coroutine_threadsafe(noop(), loop)

    done3 = threading.Event()
    h3 = {}
    N3 = N_EVENTS // 2  # this path is the slowest; halve for wall-clock sanity

    def run_v3():
        h3["dt"] = _drive_threads(v3, N_THREADS, N3)
        done3.set()

    th3 = threading.Thread(target=run_v3)
    th3.start()
    while not done3.is_set():
        await asyncio.sleep(0.005)
    th3.join()
    deadline = time.perf_counter() + 60
    while c3["n"] < N3 and time.perf_counter() < deadline:
        await asyncio.sleep(0.005)
    res["v3_run_coroutine_threadsafe_floor"] = {
        "events": N3,
        "ingest_s": round(h3["dt"], 3),
        "ingest_rate_ev_s": round(N3 / h3["dt"], 1),
        "us_per_event": round(h3["dt"] / N3 * 1e6, 2),
    }

    # V4: in-loop send() reference
    i4 = Interpreter(counter_machine())
    await i4.start()
    t0 = time.perf_counter()
    for _ in range(N_EVENTS):
        await i4.send("PING")
    enq_s = time.perf_counter() - t0
    while i4.queue_depth:
        await asyncio.sleep(0.005)
    total_s = time.perf_counter() - t0
    await i4.stop(drain=True, timeout=60)
    res["v4_in_loop_send_reference"] = {
        "events": N_EVENTS,
        "enqueue_s": round(enq_s, 3),
        "enqueue_rate_ev_s": round(N_EVENTS / enq_s, 1),
        "end_to_end_rate_ev_s": round(N_EVENTS / total_s, 1),
    }

    emit("b2_threadsafe_cost", res)


if __name__ == "__main__":
    asyncio.run(main())
