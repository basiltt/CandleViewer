"""L-10 probe: #169's root-only refusal, and the bounded child wait.

(a) Root refusal now fires on "in flight" alone -> a snapshot taken from
    inside an entry action is refused on both engines. Verify.
(b) The bounded wait on a CHILD (`_await_settled_for_snapshot`) is a
    `time.sleep(0.0005)` spin with a deadline. On the ASYNC engine that
    spin runs on the event loop thread -- so if the mid-step child is an
    ASYNC child on the SAME loop, the sleep blocks the very loop that
    would let the child finish: the wait can never succeed and always
    burns the full deadline. Measure the wall time.
"""

import asyncio
import time

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import SnapshotMidStepError

CONFIG_A = {
    "id": "p10a",
    "initial": "a",
    "context": {"qty": 0},
    "states": {
        "a": {"on": {"FILL": {"target": "filled"}}},
        "filled": {"entry": ["snap_from_entry"]},
    },
}


def main_sync() -> None:
    seen = {}

    def snap_from_entry(interp, ctx, ev, action_def):  # noqa: ANN001
        try:
            interp.get_persisted_snapshot()
            seen["r"] = "RETURNED A SNAPSHOT"
        except SnapshotMidStepError:
            seen["r"] = "refused (SnapshotMidStepError)"
        except Exception as exc:  # noqa: BLE001
            seen["r"] = f"{type(exc).__name__}"

    m = create_machine(
        CONFIG_A, logic=MachineLogic(actions={"snap_from_entry": snap_from_entry})
    )
    i = SyncInterpreter(m)
    i.start()
    i.send("FILL")
    print(f"(a) sync  entry-action snapshot: {seen.get('r')}")
    i.stop()


async def main_async() -> None:
    seen = {}

    async def snap_from_entry(interp, ctx, ev, action_def):  # noqa: ANN001
        try:
            interp.get_persisted_snapshot()
            seen["r"] = "RETURNED A SNAPSHOT"
        except SnapshotMidStepError:
            seen["r"] = "refused (SnapshotMidStepError)"
        except Exception as exc:  # noqa: BLE001
            seen["r"] = f"{type(exc).__name__}"

    m = create_machine(
        CONFIG_A, logic=MachineLogic(actions={"snap_from_entry": snap_from_entry})
    )
    i = Interpreter(m)
    await i.start()
    await i.send("FILL", wait=True)
    print(f"(a) async entry-action snapshot: {seen.get('r')}")
    await i.stop()


# ---- (b) the child bounded wait, measured -------------------------------
CHILD = {
    "id": "kid",
    "initial": "k",
    "states": {"k": {"on": {"SPIN": {"target": "k2", "actions": ["slow"]}}},
               "k2": {}},
}
PARENT = {
    "id": "p10b",
    "initial": "up",
    "states": {"up": {"invoke": {"src": "kid", "id": "kid"}}},
}


async def main_child_wait() -> None:
    async def slow(interp, ctx, ev, action_def):  # noqa: ANN001
        await asyncio.sleep(0.5)  # child is mid-step for 500 ms

    child = create_machine(CHILD, logic=MachineLogic(actions={"slow": slow}))
    parent = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    p = Interpreter(parent)
    await p.start()
    kid = next(iter(p._actors.values()))
    kid.send("SPIN")           # fire-and-forget: child enters its macrostep
    await asyncio.sleep(0.05)  # let it get in flight
    t0 = time.monotonic()
    try:
        p.get_persisted_snapshot()
        out = "snapshot returned"
    except Exception as exc:  # noqa: BLE001
        out = f"{type(exc).__name__}"
    dt = time.monotonic() - t0
    print(f"(b) parent snapshot over a mid-step ASYNC child: {out} "
          f"after {dt*1000:.0f} ms of loop-blocking spin")
    print(
        "(b) VERDICT:",
        "BOUNDED WAIT SPINS ON THE LOOP THREAD (child cannot progress)"
        if dt > 0.05
        else "returned promptly",
    )
    try:
        await asyncio.wait_for(p.stop(), timeout=3)
    except Exception:  # noqa: BLE001
        print("(b) stop() timed out")


main_sync()
asyncio.run(main_async())
asyncio.run(main_child_wait())
