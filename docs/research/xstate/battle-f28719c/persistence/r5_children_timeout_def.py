# -*- coding: utf-8 -*-
"""R5 -- MINIMAL: `start(children_timeout=)` is not a bound for a plain-`def`
child entry action.

#181 says: "`start(children_timeout=)`, default 2 s; a slow child's
`async def` entry action no longer holds `await start()` for its whole
duration. On timeout a WARNING is logged, `start()` returns with the machine
running."

The bound is implemented as `asyncio.wait(pending, timeout=...)`
(`interpreter.py:2753`). `asyncio.wait` can only cut a task at an `await`
point. A child whose entry action is a **plain `def`** -- the style the
library accepts everywhere and the style this project's round-6 pins were
written in -- blocks the event-loop thread inside `child.start()`, so the
timeout coroutine never gets scheduled and `await start()` runs for the full
`N x delay`.

This probe holds N and `delay` fixed and sweeps `children_timeout`, so the
result cannot be read as "the bound was too generous": the elapsed time is
independent of the bound for `def` and tracks it for `async def`.

    usage: r5_children_timeout_def.py [N] [DELAY_MS]
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
DELAY = (int(sys.argv[2]) if len(sys.argv) > 2 else 100) / 1000.0


class Cap(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.msgs = []

    def emit(self, r):  # noqa: ANN001
        self.msgs.append(r.getMessage())


def build(kind: str):
    def slow_def(i, c, e, a):  # noqa: ANN001
        time.sleep(DELAY)

    async def slow_async(i, c, e, a):  # noqa: ANN001
        await asyncio.sleep(DELAY)

    kid = create_machine(
        {"id": "kid", "initial": "s", "states": {"s": {"entry": ["slow"]}}},
        logic=MachineLogic(
            actions={"slow": slow_def if kind == "def" else slow_async}
        ),
    )
    par = {
        "id": "par",
        "initial": "up",
        "states": {
            "up": {"invoke": [{"id": f"k{i}", "src": "kid"} for i in range(N)]}
        },
    }
    return create_machine(par, logic=MachineLogic(services={"kid": kid}))


async def one(kind: str, bound: float) -> tuple[float, int]:
    cap = Cap()
    log = logging.getLogger("xstate_statemachine")
    log.addHandler(cap)
    i = Interpreter(build(kind), clock=SimulatedClock())
    t0 = time.perf_counter()
    await i.start(children_timeout=bound)
    el = time.perf_counter() - t0
    warns = len([m for m in cap.msgs if "still" in m and "starting" in m])
    log.removeHandler(cap)
    await i.stop()
    return el, warns


async def main() -> None:
    print("children = %d, per-child entry delay = %.0f ms  "
          "(unbounded cost: def ~%.1fs serialised, async ~%.1fs)"
          % (N, DELAY * 1000, N * DELAY, DELAY))
    print("\n%-7s %-9s %-10s %-8s %s"
          % ("kind", "bound", "start() s", "warn", "verdict"))
    bad = []
    for kind in ("def", "async"):
        for bound in (0.05, 0.2, 1.0, None):
            el, w = await one(kind, bound)
            lim = None if bound is None else bound + 0.35
            ok = lim is None or el <= lim or w > 0
            verdict = "ok" if ok else "UNBOUNDED"
            if not ok:
                bad.append((kind, bound, round(el, 2)))
            print("%-7s %-9s %-10.2f %-8d %s"
                  % (kind, bound, el, w, verdict))
    print("\nunbounded cells:", bad if bad else "none")
    print("VERDICT:", "FAIL" if bad else "PASS")


asyncio.run(main())
