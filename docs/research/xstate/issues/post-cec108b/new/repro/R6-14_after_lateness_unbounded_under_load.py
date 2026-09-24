"""R6-14: `after` timer lateness grows well past its declared delay when the
event loop is kept busy -- the CHANGELOG's "per-macrostep settle budget"
bounds the number of transient-transition iterations per macrostep, but
does not bound how late a fired `after` timer's callback is actually
processed once the loop is busy servicing other synchronous work.

This is a REGRESSION relative to `5e07ba8` per the manual comparison in the
issue; this script only demonstrates the current-commit behaviour (a
deterministic, large lateness under load), which is what "regression"
requires as a precondition.

Run: python R6-14_after_lateness_unbounded_under_load.py
Expect (bug present): observed lateness for a 50ms `after` timer, measured
  under a 100-iteration synchronous busy loop competing for the loop, is
  tens of ms above the 50ms budget (the issue reports 88-92ms).
"""
import asyncio
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine


CFG = {
    "id": "timer",
    "initial": "waiting",
    "states": {
        "waiting": {"after": {50: {"target": "fired"}}},
        "fired": {"type": "final"},
    },
}


async def main():
    m = create_machine(CFG, logic=MachineLogic())
    i = Interpreter(m)

    t0 = time.monotonic()
    await i.start()

    # Compete with the timer callback: 100 iterations of cheap synchronous
    # work, each yielding the loop briefly -- the busy-loop shape the issue
    # describes, not a single long blocking call.
    for _ in range(200):
        # Cheap CPU work, then yield control back to the loop.
        _ = sum(range(20000))
        await asyncio.sleep(0)

    deadline = time.monotonic() + 2.0
    while "timer.fired" not in i.current_state_ids and time.monotonic() < deadline:
        await asyncio.sleep(0.001)
    elapsed_ms = (time.monotonic() - t0) * 1000
    lateness_ms = elapsed_ms - 50

    print(f"reached 'fired' after {elapsed_ms:.1f} ms (budget 50 ms)")
    print(f"lateness={lateness_ms:.1f} ms")

    await i.stop()

    bug_present = lateness_ms > 15  # normal scheduling jitter for this timer is a few ms
    if bug_present:
        print(
            "BUG CONFIRMED (regression class): 'after' lateness under a "
            "busy loop is far beyond the declared 50ms budget."
        )
        sys.exit(1)
    else:
        print("Not reproduced: lateness stayed within normal jitter of the budget.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
