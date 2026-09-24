# -*- coding: utf-8 -*-
"""R5-07: a plain-`def` invoked service runs INLINE on the async run loop,
stalling every timer, actor and inbound send for its full duration (#116).

#116 made a non-coroutine service run inline, inside the macrostep that
enters the invoking state, to fix an ordering divergence between the sync and
async engines. The side effect is that `await Interpreter(...).start()` now
blocks the event loop for the whole wall-clock duration of the service: a
concurrent 10 ms ticker gets ZERO iterations while an 0.8 s service runs.

Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, create_machine

SERVICE_SECONDS = 0.8
CFG = {
    "id": "s",
    "initial": "w",
    "states": {
        "w": {"invoke": {"id": "svc", "src": "slow", "onDone": "d"}},
        "d": {},
    },
}


def slow(interp, ctx, event):  # noqa: ANN001 -- a plain, blocking `def` service
    time.sleep(SERVICE_SECONDS)
    return 1


async def main() -> int:
    ticks = {"n": 0}

    async def ticker() -> None:
        while True:
            ticks["n"] += 1
            await asyncio.sleep(0.01)

    task = asyncio.ensure_future(ticker())
    await asyncio.sleep(0.05)  # prove the ticker is alive and scheduled
    baseline = ticks["n"]

    machine = create_machine(
        json.loads(json.dumps(CFG)), logic=MachineLogic(services={"slow": slow})
    )
    started = time.monotonic()
    interp = await Interpreter(machine).start()
    blocked = time.monotonic() - started
    during = ticks["n"] - baseline

    task.cancel()
    await interp.stop()

    print(f"  ticker iterations in the 50 ms BEFORE start(): {baseline}")
    print(f"  await start() blocked for               : {blocked:.3f} s")
    print(f"  ticker iterations DURING start()        : {during}")
    print()
    print(f"OBSERVED: an 0.8 s plain-`def` service blocks `await start()` for "
          f"{blocked:.3f} s and a live 10 ms ticker advances {during} times "
          f"(expected ~{int(SERVICE_SECONDS / 0.01)}). The loop is occupied, so "
          f"no timer, actor or inbound send is serviced for the duration.")
    print("EXPECTED: the async engine never blocks its own event loop. A plain "
          "blocking callable belongs on `run_in_executor`, with its "
          "`done.invoke` delivered through the priority lane so #116's "
          "ordering guarantee is preserved without occupying the loop.")
    blocked_loop = during <= 2
    print("RESULT:", "FAIL" if blocked_loop else "PASS")
    return 1 if blocked_loop else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
