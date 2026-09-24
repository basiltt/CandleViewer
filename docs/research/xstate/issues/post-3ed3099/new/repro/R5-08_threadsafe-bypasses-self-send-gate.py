"""R5-08 repro: `send_threadsafe` bypasses the #105 self-send gate.

`_issued_from_own_action()` reads a `ContextVar`. A thread started by a user
action gets a fresh, empty context, so its `send_threadsafe` is classified as
an EXTERNAL event, skips the internal queue, and is never charged to the
chain budget. `maxIterations` therefore does not bound an action that hands
its own re-trigger to a worker thread.

Control (same machine, same action, direct `await i.send(...)`) IS budgeted.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""

import asyncio
import logging
import sys
import threading

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CEILING = 60  # the action's own stop, so the probe always terminates
LIMIT = 20  # machine maxIterations

CFG = {
    "id": "spin",
    "initial": "a",
    "maxIterations": LIMIT,
    "context": {},
    "states": {"a": {"on": {"T": {"actions": ["resend"]}}}},
}


async def run(mode: str) -> int:
    seen = {"n": 0}

    async def resend(i, c, e, a):
        seen["n"] += 1
        if seen["n"] >= CEILING:
            return
        if mode == "direct":
            await i.send("T")
        else:
            threading.Thread(
                target=lambda: i.send_threadsafe("T"), daemon=True
            ).start()

    interp = await Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"resend": resend}))
    ).start()
    await interp.send("T")
    await asyncio.sleep(1.5)
    await interp.stop()
    return seen["n"]


async def main() -> int:
    direct = await run("direct")
    threadsafe = await run("threadsafe")

    print("OBSERVED:")
    print("  maxIterations                       :", LIMIT)
    print("  direct  `await i.send()` executions  :", direct)
    print("  `send_threadsafe()` executions       :", threadsafe)
    print("  threadsafe budgeted (<= 25)          :", threadsafe <= 25)
    print("EXPECTED:")
    print("  both routes are self-generated work and are charged to the")
    print("  chain budget; both counts <= ~25 (maxIterations + slack)")

    if threadsafe > 25:
        print("RESULT: FAIL - send_threadsafe is not gated by maxIterations")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(asyncio.run(main()))
