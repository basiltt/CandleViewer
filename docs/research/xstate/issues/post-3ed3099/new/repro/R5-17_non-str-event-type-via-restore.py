"""R5-17 repro: #113's non-`str` event-type guard is enforced on `send()`
but not on the restore path.

`send()` rejects a non-str event type with `InvalidEventError`
(`base_interpreter.py::_prepare_event`). `from_snapshot()` reconstructs
pending events via `events.restore_event()`, which reads `record["type"]`
with no type check, and `persistence.check_shape()` only asserts the `type`
key is PRESENT on a pending-event record, never that it is a string. A
snapshot blob is therefore the one way to get a non-`str` event type into a
live, running interpreter -- and a snapshot is exactly the artifact that
comes back from untrusted storage (Redis/disk/a queue).

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import InvalidEventError

CFG = {
    "id": "rp",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}}, "b": {}},
}


def bump(interpreter, ctx, event, action_def):
    ctx["n"] += 1


def build():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


async def main() -> int:
    live = Interpreter(build(), clock=SimulatedClock())
    await live.start()
    send_rejected = False
    try:
        await live.send(42)
    except InvalidEventError:
        send_rejected = True
    await live.stop()

    blob = {
        "version": 1,
        "status": "running",
        "context": {"n": 0},
        "state_ids": ["rp.a"],
        "configuration": ["rp", "rp.a"],
        "pending_events": [{"kind": "event", "type": 42, "payload": {}}],
    }
    restored = Interpreter.from_snapshot(json.dumps(blob), build(), clock=SimulatedClock())
    await restored.start()
    await asyncio.sleep(0.05)
    n = restored.context["n"]
    status = restored.status
    await restored.stop()

    print("OBSERVED:")
    print(f"  send(42) on a live interpreter rejected  = {send_rejected}")
    print(f"  from_snapshot() with pending type=42     = ACCEPTED (no exception)")
    print(f"  restored interpreter status              = {status}")
    print(f"  bump() ran (context.n)                   = {n}  (0 = event matched nothing)")

    print("EXPECTED:")
    print("  from_snapshot() applies the same non-str type guard #113 gives send(),")
    print("  refusing (or coercing) a pending_events record whose 'type' is not a str")

    failed = send_rejected and status == "running"
    print("RESULT:", "FAIL - restore path accepts what send() refuses" if failed else "PASS")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
