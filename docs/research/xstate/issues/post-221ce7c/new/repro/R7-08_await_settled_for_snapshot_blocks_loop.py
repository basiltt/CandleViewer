# -*- coding: utf-8 -*-
"""R7-08 -- `_await_settled_for_snapshot` (base_interpreter.py:1273-1288)
spins `time.sleep(0.0005)` in its bounded wait loop instead of
`await asyncio.sleep(...)`. On the async `Interpreter` that spin runs on the
event-loop thread, so the mid-step ASYNC child it is waiting for cannot make
progress: the wait is guaranteed to burn its full ~0.5 s timeout and then
return the still-unsettled child anyway.

A parent takes `get_persisted_snapshot()` while a child actor is mid-step
inside a 500 ms action. The call site is `base_interpreter.py:1393`
(`if not self._configuration_is_legal(): self._await_settled_for_snapshot()`)
reached via the CHILD branch of the parent's recursive snapshot walk.

Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == the event loop was observed blocked for >=300 ms while
snapshotting a mid-step async child (the wait cannot succeed on a
single-threaded loop). Exit code 0 == it returned promptly.
"""
import asyncio
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CHILD = {
    "id": "kid",
    "initial": "k",
    "states": {
        "k": {"on": {"SPIN": {"target": "k2", "actions": ["slow"]}}},
        "k2": {},
    },
}
PARENT = {
    "id": "p",
    "initial": "up",
    "states": {"up": {"invoke": {"src": "kid", "id": "kid"}}},
}


async def slow(interp, ctx, ev, action_def):  # noqa: ANN001
    await asyncio.sleep(0.5)  # child is mid-step for 500 ms


async def main() -> int:
    child = create_machine(CHILD, logic=MachineLogic(actions={"slow": slow}))
    parent = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    p = Interpreter(parent)
    await p.start()
    kid = next(iter(p._actors.values()))
    kid.send("SPIN")           # fire-and-forget: child enters its macrostep
    await asyncio.sleep(0.05)  # let it get in flight

    t0 = time.monotonic()
    try:
        blob = p.get_persisted_snapshot()
        outcome = "snapshot returned: %r" % (blob.get("actors"),)
    except Exception as exc:  # noqa: BLE001
        outcome = "%s" % type(exc).__name__
    dt = time.monotonic() - t0

    print("parent snapshot over a mid-step ASYNC child: %s after %.0f ms"
          % (outcome, dt * 1000))

    try:
        await asyncio.wait_for(p.stop(), timeout=3)
    except Exception:  # noqa: BLE001
        print("stop() timed out")

    if dt >= 0.3:
        print("REPRODUCED: event loop was blocked for %.0f ms by a busy-wait "
              "spin (`time.sleep`, not `await asyncio.sleep`) while snapshotting "
              "a mid-step async child. The child cannot progress while the loop "
              "is blocked by the very wait meant to let it settle."
              % (dt * 1000))
        print("EXPECTED  : the bounded wait must yield the event loop "
              "(`await asyncio.sleep`) on the async engine so the child it is "
              "waiting for can actually run.")
        return 1
    print("NOT reproduced (blocked for only %.0f ms)." % (dt * 1000))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
