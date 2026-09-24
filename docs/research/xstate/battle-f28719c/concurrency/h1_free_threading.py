"""(h) Free-threaded CPython 3.13t -- NOTE ONLY, per the track brief.

Run with the free-threading interpreter (`Py_GIL_DISABLED=1`,
`sys._is_gil_enabled() is False`). The engine is a single-event-loop,
single-thread design: `Interpreter` asserts the owning thread on every
`send()` (`_assert_owning_thread`, interpreter.py:1083) and the documented
cross-thread path is `send_threadsafe()`, which hops through
`run_coroutine_threadsafe`. So free-threading is not expected to make the
engine parallel; the question is only whether removing the GIL breaks any
of its assumptions.

This is a NOTE, not a verdict: the library does not claim 3.13t support and
we are not gating on it.

Checks:
  V1  import, build, start, send, stop on 3.13t at all
  V2  the same accounting invariant as a1 (single interpreter, RAISE)
  V3  32 threads on send_threadsafe -- per-thread FIFO order preserved,
      no lost/duplicated events. Under free-threading the producers run
      genuinely in parallel, so any unsynchronised state the ingest path
      touches on the CALLING thread (`_prepare_event`, `_check_strict`)
      is exercised much harder than on the GIL build.
  V4  a deliberately racy read: 8 threads reading `current_state_ids` /
      `context` / `queue_depth` while the loop transitions, looking for a
      torn read or an exception from an unsynchronised container.
"""

from __future__ import annotations

import asyncio
import sys
import sysconfig
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
    "id": "ft",
    "initial": "a",
    "context": {"n": 0, "last": {}, "order_violations": 0},
    "strict": True,
    "states": {
        "a": {"on": {"PING": {"actions": ["rec"]}, "FLIP": {"target": "b"}}},
        "b": {"on": {"PING": {"actions": ["rec"]}, "FLIP": {"target": "a"}}},
    },
}


def rec(interpreter, ctx, event, action_def):  # noqa: ANN001
    p = event.payload
    tid, seq = p["tid"], p["seq"]
    if seq <= ctx["last"].get(tid, -1):
        ctx["order_violations"] += 1
    ctx["last"][tid] = seq
    ctx["n"] += 1


def machine():
    return create_machine(CFG, logic=MachineLogic(actions={"rec": rec}))


async def v1_smoke():
    i = Interpreter(machine())
    await i.start()
    for k in range(100):
        await i.send("PING", tid=-1, seq=k)
    r = await asyncio.wait_for(i.send("FLIP", wait=True), 5)
    out = {
        "context_n": i.context["n"],
        "receipt_changed": r.changed,
        "states": sorted(i.current_state_ids),
        "status": i.status,
    }
    await i.stop(drain=True, timeout=30)
    return out


async def v3_threads(n_threads: int = 32, per_thread: int = 1000):
    acc = Accountant()
    i = Interpreter(machine())
    i.use(acc)
    await i.start()
    barrier = threading.Barrier(n_threads + 1)
    raised = [0] * n_threads
    strict_ok = [0] * n_threads
    accepted = [0] * n_threads

    def producer(tid):
        barrier.wait()
        for seq in range(per_thread):
            if seq == per_thread // 2:
                try:
                    i.send_threadsafe("PIGN", tid=tid, seq=seq)
                except UnknownEventError:
                    strict_ok[tid] += 1
                except Exception:  # noqa: BLE001
                    raised[tid] += 1
            try:
                i.send_threadsafe("PING", tid=tid, seq=seq)
                accepted[tid] += 1
            except Exception:  # noqa: BLE001
                raised[tid] += 1

    ts = [threading.Thread(target=producer, args=(t,)) for t in range(n_threads)]
    for t in ts:
        t.start()
    barrier.wait()
    t0 = time.perf_counter()
    while any(t.is_alive() for t in ts):
        await asyncio.sleep(0.005)
    for t in ts:
        t.join()
    ingest_s = time.perf_counter() - t0
    deadline = time.perf_counter() + 120
    while i.queue_depth and time.perf_counter() < deadline:
        await asyncio.sleep(0.005)
    out = {
        "threads": n_threads,
        "per_thread": per_thread,
        "accepted": sum(accepted),
        "raised_unexpectedly": sum(raised),
        "strict_typos_rejected_on_calling_thread": sum(strict_ok),
        "strict_typos_sent": n_threads,
        "processed": i.context["n"],
        "per_thread_order_violations": i.context["order_violations"],
        "lost": sum(accepted) - i.context["n"] - len(acc.dropped),
        "ingest_s": round(ingest_s, 3),
        "ingest_rate_ev_s": round(sum(accepted) / ingest_s, 1) if ingest_s else None,
    }
    await i.stop(drain=True, timeout=60)
    return out


async def v4_racy_readers(n_readers: int = 8, window_s: float = 2.0):
    i = Interpreter(machine())
    await i.start()
    stop = threading.Event()
    errors: list[str] = []
    reads = [0] * n_readers

    def reader(rid):
        while not stop.is_set():
            try:
                _ = sorted(i.current_state_ids)
                _ = dict(i.context)
                _ = i.queue_depth
                _ = i.status
                reads[rid] += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
                if len(errors) > 50:
                    return

    ts = [threading.Thread(target=reader, args=(r,)) for r in range(n_readers)]
    for t in ts:
        t.start()
    t0 = time.perf_counter()
    k = 0
    while time.perf_counter() - t0 < window_s:
        await i.send("FLIP")
        await i.send("PING", tid=-2, seq=k)
        k += 1
        await asyncio.sleep(0)
    stop.set()
    for t in ts:
        t.join()
    while i.queue_depth:
        await asyncio.sleep(0.005)
    out = {
        "readers": n_readers,
        "reads_total": sum(reads),
        "reader_exceptions": len(errors),
        "reader_exception_sample": sorted(set(errors))[:5],
        "transitions_driven": k,
        "final_states": sorted(i.current_state_ids),
    }
    await i.stop(drain=True, timeout=30)
    return out


async def main():
    emit(
        "h1_free_threading",
        {
            "build": sys.version,
            "Py_GIL_DISABLED": sysconfig.get_config_var("Py_GIL_DISABLED"),
            "gil_enabled_at_runtime": (
                sys._is_gil_enabled() if hasattr(sys, "_is_gil_enabled") else "n/a"
            ),
            "v1_smoke": await v1_smoke(),
            "v3_threads": await v3_threads(),
            "v4_racy_readers": await v4_racy_readers(),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
