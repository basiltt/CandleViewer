# -*- coding: utf-8 -*-
"""R5-06: an external cancel landing before the run loop's first scheduling
turn is never published (#114 residual).

#114 makes an externally cancelled run loop flip `status` to "error", fail
pending receipts and fire `on_error`, via the `except asyncio.CancelledError`
handler INSIDE `_run_event_loop`. But `start()` only `create_task`s the loop
and returns. Cancelling in the window between `await start()` returning and
the task's first turn cancels a coroutine that never began, so the handler
never executes: the machine stays `status="running"` with `is_running=False`,
`error=None`, and `send(..., wait=True)` hangs forever.

A single `await asyncio.sleep(0)` before the cancel gives the loop its first
turn and #114 then works perfectly -- the control arm below.

Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "c114",
    "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {}},
}


def mk():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


async def case(yield_first: bool) -> dict:
    interp = Interpreter(mk())
    await interp.start()
    if yield_first:
        await asyncio.sleep(0)  # give the run-loop task its first turn
    interp._event_loop_task.cancel()  # noqa: SLF001 -- simulating a supervisor
    await asyncio.sleep(0.15)

    out = {
        "yield_before_cancel": yield_first,
        "status": interp.status,
        "is_running": interp.is_running,
        "error": repr(interp.error),
    }
    try:
        receipt = await asyncio.wait_for(interp.send("GO", wait=True), 2)
        out["send_wait_true"] = f"resolved: error={receipt.error!r}"
    except asyncio.TimeoutError:
        out["send_wait_true"] = "HUNG (no receipt, no exception)"
    except Exception as exc:  # noqa: BLE001
        out["send_wait_true"] = f"raised {type(exc).__name__}"
    try:
        await interp.stop()
    except Exception:  # noqa: BLE001
        pass
    out["publishes_114"] = out["status"] == "error"
    return out


async def main() -> int:
    no_yield = [await case(False) for _ in range(3)]
    with_yield = [await case(True) for _ in range(3)]
    print("cancel BEFORE first scheduling turn:")
    for row in no_yield:
        print("  ", row)
    print("control -- cancel AFTER first scheduling turn:")
    for row in with_yield:
        print("  ", row)
    deterministic = all(not r["publishes_114"] for r in no_yield) and all(
        r["publishes_114"] for r in with_yield
    )
    ok = all(r["publishes_114"] for r in no_yield + with_yield)
    print()
    print(f"OBSERVED: cancel-before-first-turn never publishes the #114 landing "
          f"(3/3 report status='running', is_running=False, error=None and hang "
          f"on send(wait=True)); the control arm publishes 3/3. "
          f"deterministic={deterministic}")
    print("EXPECTED: an externally cancelled run loop publishes the same "
          "terminal landing regardless of whether the task had begun -- "
          "status='error', a cancellation error on .error, on_error fired, "
          "and pending/late receipts failed rather than hung.")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
