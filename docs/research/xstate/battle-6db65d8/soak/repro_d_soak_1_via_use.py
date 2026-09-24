# -*- coding: utf-8 -*-
"""Minimal repro: D-soak-1.

`Interpreter.send(event, wait=True)` returns an `asyncio.Future` that is
resolved from inside `_run_event_loop`'s normal per-event bookkeeping
(`_resolve_receipt` / `_fail_receipt`). When the run loop itself dies from
an uncaught `BaseException` (e.g. a `PluginBase` hook raising, per the
documented `on_action_error`-style contract that plugin hooks are user code
running inside the loop), the `except BaseException` handler at
`interpreter.py` around line 1300 sets `self.status = "stopped"` and
re-raises -- but never calls `self._fail_all_receipts()`. Every event whose
receipt future was still pending (the one that crashed the loop, and any
event already accepted into the queue behind it) is never resolved. A
caller `await`-ing that receipt hangs forever.

Compare with the orderly path: `stop()` -> `_teardown()` -> `_fail_all_receipts()`
IS called (interpreter.py ~996), so an intentional shutdown does not hang.
Only the *unexpected* exception path skips it.

Root cause: xstate_statemachine/interpreter.py, `_run_event_loop`,
`except BaseException as exc:` block (~line 1300-1319): missing a call to
`self._fail_all_receipts()` (or equivalent) before/at the `status = "stopped"`
assignment.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"GO": {"target": "a"}}}},
}


class Boom(PluginBase):
    """A plugin hook raising models a real observability/metrics plugin bug,
    or the SOAK track's chaos-injection design -- either way, user code
    inside a hook is not guaranteed exception-free in production."""

    def on_event_received(self, interp, event):  # noqa: ANN001
        if event.type == "TRIGGER":
            raise RuntimeError("boom")


async def main() -> None:
    m = create_machine(CFG, logic=MachineLogic())
    interp = Interpreter(m)
    interp.use(Boom())
    await interp.start()

    # A normal, innocent event queued just ahead of the crashing one.
    f_go = interp.send("GO", wait=True)
    f_trigger = interp.send("TRIGGER", wait=True)

    try:
        await asyncio.wait_for(asyncio.gather(f_go, f_trigger), timeout=3.0)
        print("FAIL (not reproduced): both receipts resolved")
    except asyncio.TimeoutError:
        print("REPRODUCED: at least one wait=True receipt never resolved")
        print("  interpreter.status =", interp.status)
        print("  pending receipt futures:", len(interp._receipts))


if __name__ == "__main__":
    asyncio.run(main())
