# -*- coding: utf-8 -*-
"""Standalone repro for R8-10: `_chain_owed` leaks permanently when an
`async def` invoke's task exits via a `BaseException` OTHER than
`asyncio.CancelledError` (e.g. `KeyboardInterrupt`/`SystemExit`), and the
settle path (`_deliver_priority`, interpreter.py:2384-2385) is a bare
counter decrement, not matched to the debt that opened it.

Root cause (interpreter.py @ 6db65d8): `_owe_completion` (:2660-2679)
increments `self._chain_owed` when a coroutine service task is armed and
registers ONE release path, via `add_done_callback`, that fires only if
`t.cancelled()`. `_invoke_service_task` (:2455-2557) catches
`asyncio.CancelledError` (-> task cancelled, handled above) and
`Exception` (routed through `_publish_completion`, decrementing the SAME
counter at :2384-2385). A `BaseException` that is neither -- e.g.
`KeyboardInterrupt`, `SystemExit` -- is caught by NEITHER handler: it
propagates out of the task coroutine, the task ends NOT cancelled, and
both release paths are skipped, so the debt is never settled. Because the
chain-end test ("raised nothing, armed nothing, owes nothing") requires
`_chain_owed == 0`, the leaked debt then blocks a later, wholly unrelated
`always` cycle governed by `maxIterations` from ever reaching chain end --
proof it is a *bare counter*, not a debt matched to its invocation.

Machine: one state `hold` invokes an `async def` service that raises a
`BaseException` subclass; `_chain_owed` must return to 0 once that task ends.

OBSERVED (6db65d8): `chain_owed` stays at 1 forever after the task ends --
the leak (`chain_owed != 0`) is the defect.
EXPECTED: `chain_owed` returns to 0 after the service's task ends.

Exits 1 while the defect is present, 0 once fixed. 20s watchdog.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine


class _SimulatedBaseExceptionExit(BaseException):
    """`BaseException` subclass standing in for `KeyboardInterrupt`/`SystemExit`."""


async def raises_base_exception(i, ctx, e):  # noqa: ANN001
    await asyncio.sleep(0)
    raise _SimulatedBaseExceptionExit("simulated BaseException service exit")


CFG = {
    "id": "r8_10", "initial": "hold", "context": {}, "maxIterations": 20,
    "states": {
        "hold": {"invoke": {"src": "boom", "onDone": {"target": "idle"}}},
        "idle": {},
    },
}


def owed(i) -> int:  # noqa: ANN001
    return getattr(i, "_chain_owed", -1)


async def run() -> int:
    m = create_machine(CFG, logic=MachineLogic(services={"boom": raises_base_exception}))
    interp = Interpreter(m)
    await asyncio.wait_for(interp.start(), 20)
    # Let the task run, raise, and finish; give the loop turns to run any
    # done-callback machinery.
    for _ in range(20):
        await asyncio.sleep(0.05)
    owed_after_raise = owed(interp)

    try:
        await asyncio.wait_for(interp.stop(), 20)
    except asyncio.TimeoutError:
        pass

    print("OBSERVED: chain_owed_after_baseexception=%s" % owed_after_raise)
    print("EXPECTED: chain_owed_after_baseexception=0 (debt released on any BaseException exit)")
    if owed_after_raise != 0:
        print(f"FAIL: chain_owed leaked after BaseException exit: {owed_after_raise}")
        return 1
    print("PASS")
    return 0


async def main() -> int:
    try:
        return await asyncio.wait_for(run(), 20)
    except asyncio.TimeoutError:
        print("FAIL: watchdog timeout (20s) -- interpreter hung")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
