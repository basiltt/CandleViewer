"""LC-24 repro: queued events are lost on stop and invisible in the snapshot.

`Interpreter.send()` puts the event on an in-memory `asyncio.Queue`
(`interpreter.py:375`). `get_persisted_snapshot()` records status, context,
configuration, history, output and actors — but NOT that queue. `stop()`
cancels the run loop and discards whatever is still queued. There is also no
public API to drain it, so no shutdown path can flush events durably.

Exit code 1 on failure.
"""

from __future__ import annotations

import asyncio
import json
import logging

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

N = 50

CFG = {
    "id": "counter",
    "initial": "up",
    "context": {"n": 0},
    "states": {"up": {"on": {"TICK": {"actions": ["bump"]}}}},
}


def bump(i, c, e, a):  # noqa: ANN001
    c["n"] += 1


async def main() -> int:
    ok = True
    machine = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    i = await Interpreter(machine).start()

    # Enqueue a burst without yielding to the run loop, then crash/stop.
    for _ in range(N):
        await i.send("TICK")

    snap = json.loads(i.get_snapshot())
    print(f"OBSERVED snapshot keys        = {sorted(snap)}")
    print("EXPECTED snapshot keys        = include a pending-event field")
    queue_fields = [k for k in snap if "queue" in k or "pending_event" in k]
    if not queue_fields:
        ok = False

    print(f"OBSERVED snapshot context.n   = {snap['context']['n']}")
    print(f"EXPECTED snapshot context.n   = {N} (or n pending events recorded)")

    has_drain = any(
        hasattr(i, name) for name in ("drain_pending", "pending_events")
    )
    print(f"OBSERVED drain/pending API    = {has_drain}")
    print("EXPECTED drain/pending API    = True")
    if not has_drain:
        ok = False

    await i.stop()
    processed = i.context["n"]
    lost = N - processed
    print(f"OBSERVED processed after stop = {processed}")
    print(f"OBSERVED events lost          = {lost}")
    print("EXPECTED events lost          = 0 (drained, or recoverable from snapshot)")
    if lost:
        ok = False

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
