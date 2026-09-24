"""R4-16: when a plugin hook manufactures asyncio.CancelledError (not from an
external cancellation), the run loop's `except asyncio.CancelledError: raise`
(interpreter.py ~1246-1247, re-entering the outer handler at ~1285-1299)
propagates without normalizing `status`. The loop task dies, `status` stays
"running", and any `wait=True` receipt already pending or submitted after is
never resolved (`_fail_all_receipts()` is only called from `_teardown()`,
reached only via an orderly `stop()`).

EXPECTED: a dead run loop must not leave `status == "running"`, and it must
fail every outstanding/subsequent receipt rather than hang it forever.
OBSERVED: status stays "running", the run-loop task is done with
CancelledError, and send(..., wait=True) hangs indefinitely (no receipt, no
error, no timeout raised by the library itself).

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "px",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {"on": {"BACK": "a"}},
    },
}


class CancellingPlugin(PluginBase):
    """Models an observer whose async transport surfaced a cancellation."""

    def on_transition(self, interpreter, from_states, to_states, transition):  # noqa: ANN001
        raise asyncio.CancelledError("metrics push was cancelled")


async def main() -> int:
    interp = Interpreter(create_machine(CFG, logic=MachineLogic()))
    interp.use(CancellingPlugin())
    await interp.start()

    await interp.send("GO")  # fire-and-forget; the hook raises during this
    await asyncio.sleep(0.1)

    status_after_kill = interp.status
    task = interp._event_loop_task
    loop_done = task.done() if task else None

    try:
        await asyncio.wait_for(interp.send("BACK", wait=True), 3)
        hung = False
    except asyncio.TimeoutError:
        hung = True

    print(f"status after loop death : {status_after_kill}")
    print(f"run loop task done      : {loop_done}")
    print(f"send(..., wait=True) hung: {hung}")

    defect_present = hung and status_after_kill == "running"
    print(
        "\nOBSERVED:",
        "run loop dead, status still 'running', receipt hangs forever"
        if defect_present
        else "loop death was reported/receipts failed correctly",
    )
    print(
        "EXPECTED: status normalized away from 'running' when the loop "
        "dies, and pending/subsequent receipts fail rather than hang"
    )
    print("RESULT:", "FAIL - defect present" if defect_present else "PASS")

    await interp.stop()
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
