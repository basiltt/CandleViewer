"""NEW ATTACK (round-cec108b, track=determinism): internal=True forgery.

#150 classifies a threadsafe send as "internal" (self-issued, charged to the
machine's own maxIterations chain budget, delivered via the *unbounded*
internal queue) either by auto-detection (`_issued_from_own_action`) or by an
explicit `internal=True` override the docstring says a plain
`threading.Thread` should pass when it is relaying an action's own re-trigger.

Attack: a plain OS thread that is NOT relaying anything -- just a hostile /
buggy external producer -- passes `internal=True` on every call. Questions:
  (a) does this let it bypass the bounded inbox / QueueOverflowError(RAISE)
      backpressure entirely (an external flood using the "internal" lane)?
  (b) does it corrupt maxIterations accounting (chain never appears to end,
      or ends early, because externally-arriving traffic is now counted as
      self-generated)?
  (c) is the event actually delivered / not silently dropped?

This is a forgery of the *contract*, not a language-level security hole --
`internal` is a caller-supplied bool with no verification. The question is
whether the engine's own invariants (bounded inbox under RAISE, budget
disconnected from the deliberately-labelled real self-sends) survive it.
"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "battle-3ed3099", "determinism"))
from xstate_statemachine import (  # noqa: E402
    Interpreter,
    create_machine,
    MachineLogic,
    OverflowPolicy,
    QueueOverflowError,
)

CFG = {
    "id": "forge",
    "context": {"n": 0},
    "maxIterations": 100000,
    "initial": "a",
    "states": {
        "a": {
            "on": {
                "PING": {"actions": ["bump"]},
            }
        }
    },
}


def bump(i, c, e, a):
    c["n"] += 1


async def main():
    out = {}

    # (a) bypass bounded inbox under RAISE via internal=True forgery
    m = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    i = Interpreter(
        m,
        max_queue_size=8,
        overflow_policy=OverflowPolicy.RAISE,
    )
    await i.start()

    raised = 0
    delivered_futs = []

    def hostile_thread(n):
        nonlocal raised
        for k in range(n):
            try:
                fut = i.send_threadsafe("PING", internal=True)
                delivered_futs.append(fut)
            except QueueOverflowError:
                raised += 1

    t = threading.Thread(target=hostile_thread, args=(200,))
    t.start()
    # NOTE: t.join() here would block the event loop thread itself (this
    # coroutine runs ON the loop), starving the _deliver() coroutines the
    # thread's own futures are waiting on -- classic same-thread deadlock.
    # Poll instead so the loop keeps turning.
    while t.is_alive():
        await asyncio.sleep(0.01)

    wrapped = [asyncio.wrap_future(f) for f in delivered_futs]
    if wrapped:
        await asyncio.wait(wrapped, timeout=10)

    # drain: this machine never reaches a terminal state, so just give the
    # loop enough turns to process everything queued, then stop.
    for _ in range(2000):
        await asyncio.sleep(0)

    snap = i.get_persisted_snapshot()
    out["a_bypassed_inbox_bound"] = {
        "sent": 200,
        "raised_QueueOverflowError": raised,
        "context_n": snap.get("context", {}).get("n"),
    }
    await i.stop()

    print("== (a) internal=True bypass of bounded inbox (RAISE) ==")
    for k, v in out["a_bypassed_inbox_bound"].items():
        print(f"   {k:30s}: {v}")

    return out


if __name__ == "__main__":
    asyncio.run(main())
