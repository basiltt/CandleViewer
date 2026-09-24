"""N6b - #114 residual: an external cancel that lands BEFORE the run-loop
task's first scheduling turn is not published.

#114 makes an externally cancelled run loop flip `status` to "error", fail
pending receipts and fire `on_error`. That works via the
`except asyncio.CancelledError:` handler inside `_run_event_loop`
(interpreter.py:1446) which calls `_die` (interpreter.py:1605).

But `start()` creates the task with `asyncio.create_task(...)`
(interpreter.py:444) and returns without awaiting a turn for it. If the
owner cancels between `await start()` and the loop task's first turn --
exactly what an `asyncio.timeout()` / TaskGroup / supervisor abort around
the startup sequence does -- the coroutine has never begun, so Python
cancels the *task* without ever entering the coroutine body. The
`except CancelledError` handler never executes, `_die` never runs, and the
machine is left in the pre-#114 state:

    status == "running", is_running False, error None,
    send(..., wait=True) hangs forever.

A single `await asyncio.sleep(0)` between `start()` and `cancel()` gives
the loop its first turn and the #114 path then works perfectly -- which is
what makes this deterministic and easy to demonstrate side by side.
"""

from __future__ import annotations

import asyncio

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "c114",
    "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {}},
}


def mk():
    return create_machine(CFG, logic=MachineLogic())


async def case(yield_first: bool) -> dict:
    interp = Interpreter(mk())
    await interp.start()
    if yield_first:
        await asyncio.sleep(0)  # give the run-loop task its first turn
    interp._event_loop_task.cancel()  # noqa: SLF001 - simulating a supervisor
    await asyncio.sleep(0.15)

    out = {
        "yield_before_cancel": yield_first,
        "status": interp.status,
        "is_running": interp.is_running,
        "error": repr(interp.error),
    }
    try:
        r = await asyncio.wait_for(interp.send("GO", wait=True), 2)
        out["send_wait_true"] = f"resolved: error={r.error!r}"
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
    ok = all(c["publishes_114"] for c in no_yield + with_yield)
    emit("n6b_cancel_before_first_turn", {
        "cancel_before_first_turn": no_yield,
        "control_cancel_after_first_turn": with_yield,
        "deterministic": (
            all(not c["publishes_114"] for c in no_yield)
            and all(c["publishes_114"] for c in with_yield)
        ),
        "result": "PASS" if ok else "FAIL",
    })
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
