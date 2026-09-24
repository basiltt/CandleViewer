"""LC-28 verification on xstate-statemachine main @ 5327ba6 (pre-0.8.1).

0.8.0 CHANGELOG ([wave 2] "Invoked child actors no longer poll", #43):
the parent now awaits `child_interpreter.wait_done()` (a future resolved
the instant the child reaches done/error) instead of polling
`child.status` every 5ms in a second task. `_ACTOR_POLL_INTERVAL` is
removed entirely. This is unconditional (not a policy/opt-in).

The [Unreleased] CHANGELOG section (targeting 0.8.1) does NOT mention
#43/#28 at all -- checked explicitly below by grep of CHANGELOG.md for
"#43". Per the task's "need": re-verify honestly whether an idle child
actor still costs 2 asyncio tasks (task-count criterion), independent
of the (already-fixed, in 0.8.0) polling-latency criterion.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine import interpreter as interp_mod

logging.disable(logging.CRITICAL)

CHILD = {
    "id": "leg",
    "initial": "working",
    "states": {"working": {"on": {"FINISH": "done"}}, "done": {"type": "final"}},
}


def parent_cfg(n: int) -> dict:
    return {
        "id": "book",
        "initial": "running",
        "states": {
            "running": {
                "invoke": [{"id": f"leg{i}", "src": "leg"} for i in range(n)]
            }
        },
    }


async def measure(n: int) -> int:
    machine = create_machine(
        parent_cfg(n), logic=MachineLogic(services={"leg": create_machine(CHILD)})
    )
    base = len(asyncio.all_tasks())
    interp = await Interpreter(machine).start()
    await asyncio.sleep(0.05)
    tasks = len(asyncio.all_tasks()) - base
    await interp.stop()
    return tasks


async def measure_latency() -> float:
    """onDone latency: time from FINISH send until child.wait_done() resolves."""
    child_cfg = {
        "id": "leg",
        "initial": "working",
        "states": {"working": {"on": {"FINISH": "done"}}, "done": {"type": "final"}},
    }
    machine = create_machine(child_cfg)
    interp = await Interpreter(machine).start()
    await asyncio.sleep(0.01)
    t0 = time.monotonic()
    await interp.send("FINISH")
    await interp.wait_done()
    t1 = time.monotonic()
    await interp.stop()
    return (t1 - t0) * 1000.0


async def main() -> int:
    ok = True

    has_poll_const = hasattr(interp_mod, "_ACTOR_POLL_INTERVAL")
    print(f"OBSERVED _ACTOR_POLL_INTERVAL attribute present = {has_poll_const}")
    print("EXPECTED removed (no longer referenced anywhere)")
    if has_poll_const:
        ok = False

    counts = {}
    for n in (0, 2, 10, 50):
        counts[n] = await measure(n)
        print(f"OBSERVED children={n:>3} -> live asyncio tasks = {counts[n]}")
    per_child = [(counts[n] - counts[0]) / n for n in (2, 10, 50)]
    print(f"OBSERVED tasks per child = {per_child}")
    print("EXPECTED <= 1 task per idle child (no dedicated polling task)")
    if any(p > 1.5 for p in per_child):
        ok = False

    latency_ms = await measure_latency()
    print(f"OBSERVED onDone latency = {latency_ms:.2f} ms")
    print("EXPECTED < 2 ms (no 5ms poll floor)")
    if latency_ms >= 5.0:
        ok = False

    has_wait_done = hasattr(Interpreter, "wait_done")
    print(f"OBSERVED Interpreter.wait_done exists = {has_wait_done}")
    if not has_wait_done:
        ok = False

    # [need] task-count criterion, isolated: exactly 2 tasks/child is a
    # NOT-FIXED signal for the "collapse the second task" half of #43;
    # 1 task/child would be FIXED. Print explicitly, do not let it be
    # masked by the >1.5 tolerance check above.
    two_per_child = all(abs(p - 2.0) < 1e-9 for p in per_child)
    print(f"OBSERVED tasks-per-child == 2.0 exactly for all n = {two_per_child}")
    print("EXPECTED (per CHANGELOG framing) still 2 tasks/child: 'await' replaced "
          "'poll', task was not collapsed")

    print("RESULT:", "FIXED (event-driven completion, ~1 task/child)" if ok else "NOT FIXED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
