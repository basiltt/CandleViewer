"""R5-16 repro: `send_threadsafe` has no usable backpressure signal on the
calling thread.

`send_threadsafe` schedules `_enqueue()` onto the event loop
(`interpreter.py`), so the bounded-queue overflow check runs on the LOOP,
after the calling thread has already returned. Under `OverflowPolicy.RAISE`
the resulting `QueueOverflowError` is attached to the returned
`concurrent.futures.Future` -- which the documented fire-and-forget usage
(`interp.send_threadsafe("X")`, result never read) never inspects. The
producing thread is told nothing.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import sys
import threading

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.models import OverflowPolicy

CFG = {
    "id": "ctr",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"PING": {"actions": ["bump"]}}}},
}


def bump(interpreter, ctx, event, action_def):
    ctx["n"] += 1


async def main() -> int:
    logic = MachineLogic(actions={"bump": bump})
    interp = Interpreter(
        create_machine(CFG, logic=logic),
        max_queue_size=100,
        overflow_policy=OverflowPolicy.RAISE,
    )
    await interp.start()

    n_threads = 16
    sent = 0
    raised_on_thread = 0
    futures = []
    lock = threading.Lock()

    def producer():
        nonlocal sent, raised_on_thread
        for _ in range(200):
            try:
                f = interp.send_threadsafe("PING")
                with lock:
                    sent += 1
                    futures.append(f)
            except Exception:  # noqa: BLE001
                with lock:
                    raised_on_thread += 1

    threads = [threading.Thread(target=producer) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    await asyncio.sleep(0.5)

    overflow_on_future = sum(
        1 for f in futures if f.done() and f.exception() is not None
    )

    print("OBSERVED:")
    print(f"  calls_returned_without_raising_on_calling_thread = {sent}")
    print(f"  raised_on_calling_thread                         = {raised_on_thread}")
    print(f"  QueueOverflowError_landed_on_unread_future        = {overflow_on_future}")

    print("EXPECTED:")
    print("  overflow under RAISE is signalled to the CALLING thread synchronously,")
    print("  e.g. send_threadsafe raises QueueOverflowError before returning, or the")
    print("  bound is checked before scheduling onto the loop")

    failed = raised_on_thread == 0 and overflow_on_future > 0
    print("RESULT:", "FAIL - no calling-thread backpressure signal" if failed else "PASS")
    await interp.stop(drain=True, timeout=30)
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
