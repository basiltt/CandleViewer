# -*- coding: utf-8 -*-
"""R4-03: OverflowPolicy.BLOCK silently discards every fire-and-forget send().

`Interpreter.send()` is documented as doing ALL of its work eagerly so that a
fire-and-forget `interp.send("GO")` is delivered rather than silently dropped.
That holds for RAISE and DROP_NEWEST, which call the synchronous `_enqueue()`.
It is FALSE for BLOCK: `send()` returns the *coroutine object*
`_enqueue_blocking(...)` without ever starting it. Nothing is queued, no hook
fires, no log line is written -- the only trace is a GC-timed RuntimeWarning.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio
import gc
import warnings

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.models import OverflowPolicy

CONFIG = {
    "id": "counter",
    "initial": "idle",
    "context": {"n": 0},
    "states": {"idle": {"on": {"PING": {"actions": ["bump"]}}}},
}


def bump(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["n"] += 1


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"bump": bump}))


async def main() -> int:
    interp = Interpreter(
        build(),
        max_queue_size=1000,  # generous: the inbox is never anywhere near full
        overflow_policy=OverflowPolicy.BLOCK,
    )
    await interp.start()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(10):
            interp.send("PING")  # fire-and-forget, as the docstring blesses
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0)
        warn_texts = [str(w.message) for w in caught]

    depth = interp.queue_depth
    n = interp.context["n"]
    await interp.stop()

    print("OBSERVED: sent=10 processed_context_n=%d queue_depth=%d "
          "RuntimeWarnings=%d" % (n, depth, len(warn_texts)))
    for t in sorted(set(warn_texts)):
        print("OBSERVED:   warning:", t)
    print("EXPECTED: sent=10 processed_context_n=10 queue_depth=0 "
          "RuntimeWarnings=0")

    ok = n == 10
    print("RESULT:", "PASS" if ok else "FAIL (all 10 events lost silently)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
