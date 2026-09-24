# -*- coding: utf-8 -*-
"""S8 -- `children_timeout` at scale: 50 `def` + 50 `async def` children.

#194 (reopened #181): the bound is PER CHILD, not aggregate, and the
WARNING fires whenever the allowance was exceeded -- including the
single-threaded `def` case a bound cannot pre-empt.

Two claims are separable and both are checked here with 100 children
(50 of each kind), each holding D = 0.1 s:

  A. PER-CHILD, not N*D: with an `async def` entry hold, `start()` must
     return in ~D (not 50*D). Measured against `children_timeout=0.2`.
  B. The WARNING is ALWAYS emitted on overrun, including the plain-`def`
     lane that the bound cannot interrupt (so `start()` takes ~50*D and
     the log still says so).

The `def` and `async` halves are run as separate machines so the two
claims are not confounded; then a MIXED machine is run, which is the shape
a real system has.

STANDALONE.
"""
from __future__ import annotations

import asyncio
import logging
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

N = 50
D = 0.1
FAIL: list[str] = []


class Catch(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


def child_spec(cid, hold):
    return {
        "id": cid,
        "initial": "s",
        "states": {"s": {"entry": [hold]}},
    }


def build(n_def, n_async):
    """A parallel parent invoking n_def + n_async child machines."""
    def hold_def(interp, ctx, ev, act):
        time.sleep(D)

    async def hold_async(interp, ctx, ev, act):
        await asyncio.sleep(D)

    services = {}
    states = {}
    for i in range(n_def + n_async):
        kind = "d" if i < n_def else "a"
        hold = "hold_def" if kind == "d" else "hold_async"
        cid = "kid%s%d" % (kind, i)
        services[cid] = create_machine(
            child_spec(cid, hold),
            logic=MachineLogic(actions={hold: hold_def if kind == "d"
                                        else hold_async}),
        )
        states["r%d" % i] = {
            "initial": "x",
            "states": {"x": {"invoke": [{"id": cid, "src": cid}]}},
        }
    spec = {"id": "par", "type": "parallel", "states": states}
    return create_machine(
        spec,
        logic=MachineLogic(
            actions={"hold_def": hold_def, "hold_async": hold_async},
            services=services,
        ),
    )


async def case(label, n_def, n_async, bound):
    cap = Catch()
    lg = logging.getLogger("xstate_statemachine.interpreter")
    lg.addHandler(cap)
    m = build(n_def, n_async)
    i = Interpreter(m)
    t0 = time.perf_counter()
    await i.start(children_timeout=bound)
    el = time.perf_counter() - t0
    warned = [x for x in cap.msgs if "children_timeout" in x]
    lg.removeHandler(cap)
    await i.stop()
    print("  %-26s bound=%-5s start=%6.3fs  warnings=%d"
          % (label, bound, el, len(warned)))
    return el, warned


async def main() -> None:
    print("=== S8 children_timeout at scale (N=%d each, hold=%.2fs) ===\n"
          % (N, D))
    print("A. per-child bound (async children, bound=0.2s)")
    el, w = await case("50 async children", 0, N, 0.2)
    if el > N * D * 0.5:
        FAIL.append("A: 50 async children took %.2fs -- the bound looks "
                    "AGGREGATE (N*D=%.1fs), not per child" % (el, N * D))

    print("\nB. plain-`def` children -- bound cannot pre-empt, "
          "WARNING must still fire")
    el, w = await case("50 def children", N, 0, 0.2)
    if not w:
        FAIL.append("B: 50 def children overran (%.2fs vs 0.2s bound) with "
                    "NO children_timeout WARNING" % el)

    print("\nC. mixed 50 def + 50 async")
    el, w = await case("50 def + 50 async", N, N, 0.2)
    if not w:
        FAIL.append("C: mixed overrun (%.2fs) with no WARNING" % el)

    print("\nD. control: no bound")
    await case("50 async, bound=None", 0, N, None)

    print("\nFAILURES:", FAIL if FAIL else "none")
    print("VERDICT:", "FAIL" if FAIL else "PASS")


asyncio.run(main())
