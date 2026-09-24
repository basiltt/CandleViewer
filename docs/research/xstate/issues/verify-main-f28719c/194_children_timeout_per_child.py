"""Verify #194 on f28719c: children_timeout is per-child, WARNING always
fires on overrun (including non-preemptable `def` entry actions), and the
bound is not aggregate over N children.

Standalone (stdlib + xstate_statemachine only). Exit 0 iff every criterion
holds; exit 1 otherwise. Prints a cell table.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

FAIL: list[str] = []
ROWS: list[dict] = []

KID = {"id": "kid", "initial": "k", "context": {}, "states": {"k": {"entry": ["slow"]}}}
PAR = {"id": "r194", "initial": "up", "context": {}, "states": {
    "up": {"invoke": {"src": "kid", "id": "kid"}, "on": {"P": {"target": "off"}}},
    "off": {},
}}


def build(n_children: int, entry_kind: str, delay: float):
    if entry_kind == "def":
        def slow(i, c, e, a):
            time.sleep(delay)
    else:
        async def slow(i, c, e, a):
            await asyncio.sleep(delay)

    kid = create_machine(json.loads(json.dumps(KID)), logic=MachineLogic(actions={"slow": slow}))
    par = json.loads(json.dumps(PAR))
    par["states"]["up"]["invoke"] = [{"src": "kid", "id": f"kid{j}"} for j in range(n_children)]
    return create_machine(par, logic=MachineLogic(actions={"slow": slow}, services={"kid": kid}))


class _WarnCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.hit = False

    def emit(self, record):
        if "children_timeout" in record.getMessage():
            self.hit = True


async def trial(n_children: int, entry_kind: str, delay: float, timeout: float):
    m = build(n_children, entry_kind, delay)
    it = Interpreter(m)
    cap = _WarnCapture()
    logging.getLogger("xstate_statemachine.interpreter").addHandler(cap)
    t0 = time.monotonic()
    await asyncio.wait_for(it.start(children_timeout=timeout), 30)
    elapsed = time.monotonic() - t0
    logging.getLogger("xstate_statemachine.interpreter").removeHandler(cap)
    await asyncio.wait_for(it.stop(), 10)
    return elapsed, cap.hit


async def main() -> int:
    # Criterion A: async def, per-child bound. N children each sleeping
    # `delay` seconds must all settle in ~delay, NOT N*delay, when
    # children_timeout is generous (unbounded wait case is not tested here;
    # we test the *aggregate-vs-per-child* shape with timeout=None so we
    # measure natural concurrency, and separately with a tight timeout for
    # the bound+WARNING behavior).
    for n in (1, 5):
        elapsed, warned = await trial(n, "async def", delay=0.5, timeout=None)
        ROWS.append({"case": "concurrency(no bound)", "kind": "async def", "n": n,
                      "elapsed": round(elapsed, 2), "warned": warned})
        if elapsed > 0.5 * 3:
            FAIL.append(f"async def n={n} concurrency: elapsed {elapsed:.2f}s looks serial (aggregate), not per-child")

    # Criterion B: async def, tight timeout bounds start() near `timeout`
    # regardless of N, and WARNING fires.
    for n in (1, 5):
        elapsed, warned = await trial(n, "async def", delay=3.0, timeout=0.2)
        ROWS.append({"case": "bounded+warned", "kind": "async def", "n": n,
                      "elapsed": round(elapsed, 2), "warned": warned})
        if elapsed > 1.0:
            FAIL.append(f"async def n={n} bounded: elapsed {elapsed:.2f}s not bounded near 0.2s timeout")
        if not warned:
            FAIL.append(f"async def n={n} bounded: WARNING not logged on overrun")

    # Criterion C: def (non-yielding) entry action -- documented limitation:
    # cannot be pre-empted (start() blocks ~delay regardless of timeout),
    # BUT the WARNING must still fire (this is the #194 fix: warning no
    # longer silently suppressed).
    def_delay = 0.3
    for n in (1, 5):
        elapsed, warned = await trial(n, "def", delay=def_delay, timeout=0.05)
        ROWS.append({"case": "def-nonpreemptable", "kind": "def", "n": n,
                      "elapsed": round(elapsed, 2), "warned": warned})
        if not warned:
            FAIL.append(f"def n={n}: WARNING not logged despite overrun (silent failure regression)")
        # elapsed should be close to n*? -- per-child: with n children run
        # concurrently as asyncio tasks even for `def` services (offloaded
        # inline execution runs on the loop thread sequentially per #193/#194
        # notes), so we only assert it is NOT wildly larger than n*delay
        # (sanity, not a strict per-child claim for this documented case).
        if elapsed > n * def_delay * 3 + 1:
            FAIL.append(f"def n={n}: elapsed {elapsed:.2f}s far exceeds n*delay={n*def_delay:.2f}s envelope")

    print(json.dumps({"rows": ROWS, "failures": FAIL}, indent=2))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
