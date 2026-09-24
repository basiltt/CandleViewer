# -*- coding: utf-8 -*-
"""R7-01 -- an `async def` invoked service's completion is published on the
PUBLIC INBOX lane, so it is never charged to the chain budget and the
self-generated invoke cycle is unbounded.

Same chart, same `maxIterations`, ONE WORD changed:

    def   svc(...)   -> `_finish_plain_service` -> `_deliver_priority`
                        (interpreter.py:2690), which charges `_raise_depth`
                        at interpreter.py:2287-2288  ->  RunawayChainError.

    async def svc(...) -> `_invoke_service_task` -> `await self.send(done_evt)`
                        (interpreter.py:2414), the public inbox  ->  never
                        reaches the charging site under ANY value of
                        `_processing`, and arriving `from_inbox` it ALSO
                        satisfies the disjunct at interpreter.py:1647 and
                        RESETS `_settle_iterations` / `_settle_tripped` on
                        every lap.  Result: uncharged AND budget-clearing.

The library's own three regression pins for this family
(tests/test_round6_findings.py:124/184/486) all declare `def svc`, so the
suite is structurally blind to the lane the documentation recommends (#174).

Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == the unbounded coroutine-service cycle was observed.
"""
import asyncio
import copy
import logging
import time

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)

MAX_ITERATIONS = 20
RUN_SECONDS = 2.0

CFG = {
    "id": "lane",
    "actionErrorPolicy": "rollback",
    "maxIterations": MAX_ITERATIONS,
    "initial": "a",
    "context": {},
    "states": {
        # a --invoke--> onDone --> b --invoke--> onDone --> a --> ...
        "a": {
            "invoke": {"id": "sa", "src": "svc",
                       "onDone": {"target": "#lane.b"}},
        },
        "b": {
            "invoke": {"id": "sb", "src": "svc",
                       "onDone": {"target": "#lane.a"}},
        },
    },
}

laps = []


def svc_plain(interp, ctx, evt):
    laps.append(1)
    return {"ok": True}


async def svc_coro(interp, ctx, evt):
    laps.append(1)
    return {"ok": True}


def build(coro):
    return create_machine(
        copy.deepcopy(CFG),
        logic=MachineLogic(services={"svc": svc_coro if coro else svc_plain}),
    )


async def probe(coro):
    laps.clear()
    it = Interpreter(build(coro))
    await it.start()
    t0 = time.monotonic()
    while time.monotonic() - t0 < RUN_SECONDS:
        await asyncio.sleep(0.05)
        if getattr(it, "last_error", None) is not None:
            break
    n = len(laps)
    le = getattr(it, "last_error", None)
    err = type(le).__name__ if le is not None else None
    print("%-9s : service calls=%-7d status=%-8s last_error=%s"
          % ("async def" if coro else "def", n, it.status, err))
    await it.stop()
    return n, err


async def main():
    print("maxIterations = %d, run = %.1fs, async Interpreter both times.\n"
          % (MAX_ITERATIONS, RUN_SECONDS))
    n_plain, err_plain = await probe(False)
    n_coro, err_coro = await probe(True)
    print()
    bounded_plain = err_plain == "RunawayChainError" and n_plain <= 10 * MAX_ITERATIONS
    unbounded_coro = err_coro is None and n_coro > 50 * MAX_ITERATIONS
    if bounded_plain and unbounded_coro:
        print("REPRODUCED: plain `def` is bounded (%d calls, %s) while the "
              "IDENTICAL chart with `async def` ran %d calls with "
              "last_error=None." % (n_plain, err_plain, n_coro))
        print("EXPECTED  : both service kinds charged on the same lane, both "
              "tripping RunawayChainError at the same lap count.")
        return 1
    print("NOT reproduced (plain=%r/%s, coro=%r/%s)."
          % (n_plain, err_plain, n_coro, err_coro))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
