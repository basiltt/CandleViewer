"""LC-12 verification on xstate-statemachine 0.8.0.

CHANGELOG [wave 3 / #41]: "spawn_blocking_<key> on the async Interpreter
honoured only the spawn_ half and ran non-blocking. Both engines now wait
for the child to reach a terminal status before the parent's next action."
Also adds machine key `spawnBlockingTimeout` (default 30s) bounding the wait.

This is a DEFAULT behaviour fix (not opt-in): spawn_blocking_<key> should now
block on both engines, out of the box.
"""

from __future__ import annotations

import asyncio
import sys
import time

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CHILD_WORK_S = 0.25


def parent(action_type: str):
    # NOTE: a synchronous `time.sleep` in a child entry action occupies the
    # asyncio event-loop thread regardless of blocking mode, which makes the
    # async engine's spawn_/spawn_blocking_ durations look identical for a
    # reason unrelated to the defect (see original LC-12 issue notes). Using
    # a genuinely async invoked service (`asyncio.sleep`) lets the parent
    # actually proceed immediately in non-blocking mode and actually wait in
    # blocking mode, on both engines.
    async def wait_a_bit(interp, ctx, evt):  # noqa: ANN001
        await asyncio.sleep(CHILD_WORK_S)
        return {"ok": True}

    def wait_a_bit_sync(interp, ctx, evt):  # noqa: ANN001
        time.sleep(CHILD_WORK_S)
        return {"ok": True}

    child_async = create_machine(
        {"id": "w", "initial": "working",
         "states": {
             "working": {"invoke": {"id": "wait", "src": "wait", "onDone": "done"}},
             "done": {"type": "final"},
         }},
        logic=MachineLogic(services={"wait": wait_a_bit}),
    )
    child_sync = create_machine(
        {"id": "w", "initial": "working",
         "states": {
             "working": {"invoke": {"id": "wait", "src": "wait", "onDone": "done"}},
             "done": {"type": "final"},
         }},
        logic=MachineLogic(services={"wait": wait_a_bit_sync}),
    )
    return {
        "async": create_machine(
            {"id": "p", "initial": "a", "states": {"a": {"entry": [action_type]}}},
            logic=MachineLogic(services={"worker": child_async}),
        ),
        "sync": create_machine(
            {"id": "p", "initial": "a", "states": {"a": {"entry": [action_type]}}},
            logic=MachineLogic(services={"worker": child_sync}),
        ),
    }


async def main() -> int:
    res = {}
    for t in ("spawn_worker", "spawn_blocking_worker"):
        s = time.perf_counter()
        interp = await Interpreter(parent(t)["async"]).start()
        res[("async", t)] = (time.perf_counter() - s, len(interp._actors))
        await interp.stop()
    for t in ("spawn_worker", "spawn_blocking_worker"):
        s = time.perf_counter()
        interp = SyncInterpreter(parent(t)["sync"]).start()
        res[("sync", t)] = (time.perf_counter() - s, len(interp._actors))
        time.sleep(0.4)
        interp.stop()

    for (engine, t), (el, actors) in res.items():
        print(f"OBSERVED {engine:5s} {t:22s} start_blocked_ms={el * 1000:6.0f} actors_after_spawn={actors}")

    a_plain, a_block = res[("async", "spawn_worker")][0], res[("async", "spawn_blocking_worker")][0]
    s_plain, s_block = res[("sync", "spawn_worker")][0], res[("sync", "spawn_blocking_worker")][0]

    async_distinguishes = a_block > a_plain + CHILD_WORK_S / 2
    sync_distinguishes = s_block > s_plain + CHILD_WORK_S / 2

    print(f"OBSERVED async distinguishes spawn_ vs spawn_blocking_: {async_distinguishes} "
          f"({a_plain*1000:.0f} ms vs {a_block*1000:.0f} ms)")
    print(f"OBSERVED sync  distinguishes spawn_ vs spawn_blocking_: {sync_distinguishes} "
          f"({s_plain*1000:.0f} ms vs {s_block*1000:.0f} ms)")
    print("EXPECTED both engines agree: spawn_blocking_ blocks the parent until the "
          "child reaches a terminal state, on BOTH engines, by default (#41).")

    return 0 if (async_distinguishes and sync_distinguishes) else 1


sys.exit(asyncio.run(main()))
