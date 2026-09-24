"""LC-41 verification on xstate-statemachine 0.8.0.

Exercises the new `queue_depth` property and `max_queue_size` /
`overflow_policy` constructor options against the acceptance criteria in
LC-41-unbounded-queue-no-backpressure.md.

Exit 0 if every checked criterion passes, 1 otherwise. Prints
OBSERVED/EXPECTED for each check.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    QueueOverflowError,
    SyncInterpreter,
    create_machine,
)

logging.disable(logging.CRITICAL)

CFG = {
    "id": "gw",
    "initial": "idle",
    "states": {"idle": {"on": {"TICK": {"actions": ["work"]}}}},
}


async def work(interp, ctx, event, action_def):  # noqa: ANN001
    await asyncio.sleep(0.01)


async def main() -> int:
    ok = True
    logic = MachineLogic(actions={"work": work})

    # --- 1) queue_depth is public and tracks pending events ---------------
    interp = await Interpreter(create_machine(CFG, logic=logic)).start()
    print(f"OBSERVED hasattr(interp, 'queue_depth') = {hasattr(interp, 'queue_depth')}")
    print("EXPECTED True")
    if not hasattr(interp, "queue_depth"):
        ok = False

    before = interp.queue_depth
    for i in range(50):
        await interp.send("TICK", i=i)
    after = interp.queue_depth
    print(f"OBSERVED queue_depth before={before}, after 50 sends={after}")
    print("EXPECTED depth to have increased (tracks pending events)")
    if not (after > before):
        ok = False
    await interp.stop()

    # --- 2) default (max_queue_size=None) preserves unbounded 0.7.x behaviour
    interp2 = await Interpreter(create_machine(CFG, logic=logic)).start()
    for i in range(2000):
        await interp2.send("TICK", i=i)
    depth2 = interp2.queue_depth
    print(f"OBSERVED default Interpreter accepted 2000 sends, queue_depth={depth2}")
    print("EXPECTED all 2000 accepted, no exception (byte-for-byte 0.7.x default)")
    if depth2 < 1900:
        ok = False
    await interp2.stop()

    # --- 3) RAISE policy raises QueueOverflowError with depth/maxsize -----
    interp3 = await Interpreter(
        create_machine(CFG, logic=logic),
        max_queue_size=5,
        overflow_policy=OverflowPolicy.RAISE,
    ).start()
    raised = None
    try:
        for i in range(50):
            await interp3.send("TICK", i=i)
    except QueueOverflowError as exc:
        raised = exc
    print(f"OBSERVED RAISE policy -> {raised!r}")
    print("EXPECTED QueueOverflowError with .depth and .maxsize populated")
    if raised is None or not hasattr(raised, "depth") or not hasattr(raised, "maxsize"):
        ok = False
    await interp3.stop()

    # --- 4) DROP_NEWEST discards and logs (checked via plugin hook) -------
    from xstate_statemachine import PluginBase

    dropped = []

    class _Spy(PluginBase):
        def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
            dropped.append((event.type, reason))

    interp4 = Interpreter(
        create_machine(CFG, logic=logic),
        max_queue_size=3,
        overflow_policy=OverflowPolicy.DROP_NEWEST,
    )
    interp4._plugins.append(_Spy())
    await interp4.start()
    for i in range(20):
        await interp4.send("TICK", i=i)
    print(f"OBSERVED DROP_NEWEST: dropped_hook_calls={len(dropped)}, "
          f"queue_depth={interp4.queue_depth}")
    print("EXPECTED some drops recorded, queue_depth <= max_queue_size")
    if not dropped or interp4.queue_depth > 3:
        ok = False
    await interp4.stop()

    # --- 5) SyncInterpreter.queue_depth exists -----------------------------
    sync = SyncInterpreter(create_machine(CFG, logic=MachineLogic(
        actions={"work": lambda i, c, e, a: None}
    ))).start()
    print(f"OBSERVED hasattr(SyncInterpreter, 'queue_depth') = "
          f"{hasattr(sync, 'queue_depth')}, value={getattr(sync, 'queue_depth', None)}")
    print("EXPECTED True, an int")
    if not hasattr(sync, "queue_depth") or not isinstance(sync.queue_depth, int):
        ok = False

    print("RESULT:", "FIXED" if ok else "NOT FIXED (see failing checks above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
