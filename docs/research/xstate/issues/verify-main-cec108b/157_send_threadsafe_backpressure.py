"""Verify #157 on cec108b: send_threadsafe backpressure on the calling thread.

Acceptance criteria (issue #157 + CHANGELOG claim):
  A) Under OverflowPolicy.RAISE, a single-thread caller that floods a
     bounded inbox gets QueueOverflowError raised SYNCHRONOUSLY at the
     send_threadsafe() call site (not only attached to the returned Future).
  B) Concurrent producers (many threads) do not silently exceed the bound
     with zero calling-thread signal -- the CHANGELOG says "raised at the
     send_threadsafe() call site instead of on a future the fire-and-forget
     pattern never reads" with no single-thread caveat.

Exits 0 only if both hold. Prints PASS/FAIL per criterion.
"""
from __future__ import annotations

import asyncio
import sys
import threading

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import QueueOverflowError
from xstate_statemachine.models import OverflowPolicy

CFG = {
    "id": "ctr",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"PING": {"actions": ["bump"]}}}},
}


def bump(interpreter, ctx, event, action_def):
    ctx["n"] += 1


async def single_thread_case() -> bool:
    """Criterion A: one thread, synchronous send_threadsafe calls, floods
    the bound -- must raise QueueOverflowError at the call site."""
    logic = MachineLogic(actions={"bump": bump})
    interp = Interpreter(
        create_machine(CFG, logic=logic),
        max_queue_size=10,
        overflow_policy=OverflowPolicy.RAISE,
    )
    await interp.start()

    raised = False
    futures = []
    for _ in range(500):
        try:
            futures.append(interp.send_threadsafe("PING"))
        except QueueOverflowError:
            raised = True
            break
    await asyncio.sleep(0.2)
    await interp.stop(drain=True, timeout=30)
    print(f"  [A] single-thread flood raised QueueOverflowError at call site: {raised}")
    return raised


async def concurrent_case() -> bool:
    """Criterion B: many threads racing; overflow must not land ONLY on
    unread futures with zero calling-thread signal."""
    logic = MachineLogic(actions={"bump": bump})
    interp = Interpreter(
        create_machine(CFG, logic=logic),
        max_queue_size=100,
        overflow_policy=OverflowPolicy.RAISE,
    )
    await interp.start()

    n_threads = 16
    raised_on_thread = 0
    futures = []
    lock = threading.Lock()

    def producer():
        nonlocal raised_on_thread
        for _ in range(200):
            try:
                f = interp.send_threadsafe("PING")
                with lock:
                    futures.append(f)
            except QueueOverflowError:
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
    await interp.stop(drain=True, timeout=30)

    print(f"  [B] concurrent: raised_on_calling_thread={raised_on_thread}, "
          f"overflow_landed_on_unread_future={overflow_on_future}")
    # Pass only if overflow (if any occurred at all) was signalled on the
    # calling thread at least proportionally -- i.e. it is NOT the case that
    # zero calling-thread raises occurred while futures still carried errors.
    ok = not (raised_on_thread == 0 and overflow_on_future > 0)
    return ok


async def main() -> int:
    a = await single_thread_case()
    b = await concurrent_case()
    print(f"CRITERION A (single-thread sync raise): {'PASS' if a else 'FAIL'}")
    print(f"CRITERION B (concurrent, no silent-future-only overflow): {'PASS' if b else 'FAIL'}")
    return 0 if (a and b) else 1


sys.exit(asyncio.run(main()))
