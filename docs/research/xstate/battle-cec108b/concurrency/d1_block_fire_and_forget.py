"""D-concurrency-1 (minimal): OverflowPolicy.BLOCK silently discards every
fire-and-forget `send()`, even when the inbox is EMPTY.

`Interpreter.send()`'s own docstring (interpreter.py:556-566):

    ALL of the work -- thread check, normalisation, status guard and the
    queue put -- therefore happens eagerly, before anything is awaited.
    ... a fire-and-forget ``interp.send("GO")`` from inside the loop is
    delivered rather than silently dropped.

That holds for RAISE and DROP_NEWEST, which call the synchronous
`_enqueue()` inside `send()` itself. It is FALSE for BLOCK: `send()`
returns the *coroutine object* `_enqueue_blocking(...)` (interpreter.py:610,
`return self._enqueue_blocking(event_obj, receipt)`) without ever calling
it. Nothing is normalised onto a queue, no hook fires, no log line is
written. The only trace is a RuntimeWarning from the GC, which most
services never see -- and under `-W error` becomes a crash at an arbitrary
later point, in the GC, not at the call site.

Root cause: interpreter.py:610 (BLOCK branch of `send`) returns an
un-started coroutine, whereas the RAISE / DROP_NEWEST branch at
interpreter.py:636 calls `self._enqueue(event_obj)` eagerly.

Run:
    python d1_block_fire_and_forget.py
"""

from __future__ import annotations

import asyncio
import gc
import warnings

from common import Accountant, counter_machine
from xstate_statemachine import Interpreter
from xstate_statemachine.models import OverflowPolicy


async def main() -> int:
    acc = Accountant()
    interp = Interpreter(
        counter_machine(),
        max_queue_size=1000,  # generous: the inbox is never anywhere near full
        overflow_policy=OverflowPolicy.BLOCK,
    )
    interp.use(acc)
    await interp.start()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(10):
            interp.send("PING")  # fire-and-forget, as the docstring blesses
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0)
        warn_texts = [str(w.message) for w in caught]

    print("sent (fire-and-forget) : 10")
    print("processed              :", len(acc.received))
    print("context['n']           :", interp.context["n"])
    print("queue_depth            :", interp.queue_depth)
    print("on_event_dropped hook  :", acc.dropped)
    print("RuntimeWarnings        :", len(warn_texts))
    for t in set(warn_texts):
        print("   ", t)
    await interp.stop()

    ok = len(acc.received) == 10
    print("\nRESULT:", "PASS (events delivered)" if ok else "FAIL (all 10 lost silently)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
