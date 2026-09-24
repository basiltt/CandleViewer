"""D-concurrency-2 (minimal): an event parked on a full BLOCK inbox is
discarded with NO `on_event_dropped` hook when the interpreter stops.

Every other loss path in the engine is attributable:

  * inbox full under DROP_NEWEST -> on_event_dropped(reason="queue_full")
    (interpreter.py:853-863)
  * send to a stopped/done/errored machine ->
    on_event_dropped(reason="not_running") (interpreter.py:790-811)
  * runaway chain -> on_event_dropped(reason="chain_budget")

The BLOCK release path is the exception. `_enqueue_blocking`
(interpreter.py:819-833) leaves its loop when `status != "running"` and
calls only `self._fail_receipt(...)`. With `wait=True` the caller learns
via an `InterpreterStoppedError` receipt. With the ordinary
fire-and-forget `await interp.send("X")` there is no receipt, so
`_fail_receipt` is a no-op: the coroutine returns `None` -- indistinguishable
from a successful enqueue -- and no plugin, log line or counter records the
loss.

A load-shedding dashboard built on `on_event_dropped` therefore reports
zero drops while events are being dropped, and an `await send()` that
returns normally cannot be trusted to mean "accepted".

Root cause: interpreter.py:823-828 -- the `status != "running"` branch of
`_enqueue_blocking` reports through the receipt only; it never calls
`plugin.on_event_dropped(self, event_obj, ...)` and never logs.

Run:
    python d2_block_stop_silent_drop.py
"""

from __future__ import annotations

import asyncio

from common import Accountant, counter_machine
from xstate_statemachine import Interpreter
from xstate_statemachine.models import OverflowPolicy

CAP = 4
N_BLOCKED = 5


async def main() -> int:
    acc = Accountant()
    interp = Interpreter(
        counter_machine(), max_queue_size=CAP, overflow_policy=OverflowPolicy.BLOCK
    )
    interp.use(acc)
    await interp.start()

    # Fill the inbox to capacity without giving the run loop a turn.
    for _ in range(CAP):
        await interp.send("PING")
    assert interp.queue_depth == CAP, interp.queue_depth

    outcomes: list[str] = []

    async def blocked_producer(k: int) -> None:
        # Plain fire-and-forget await: the documented ordinary usage.
        try:
            await interp.send("PING")
            outcomes.append(f"{k}: send() returned normally")
        except Exception as exc:  # noqa: BLE001
            outcomes.append(f"{k}: {type(exc).__name__}: {exc}")

    tasks = [asyncio.create_task(blocked_producer(k)) for k in range(N_BLOCKED)]
    await asyncio.sleep(0)  # let each reach the spin in _enqueue_blocking

    await interp.stop()  # no drain
    await asyncio.gather(*tasks, return_exceptions=True)

    print(f"inbox cap              : {CAP}")
    print(f"producers parked        : {N_BLOCKED}")
    print(f"processed (hook)        : {len(acc.received)}")
    print(f"on_event_dropped events : {acc.dropped}")
    print("producer outcomes       :")
    for o in outcomes:
        print("   ", o)

    silent = N_BLOCKED - len(acc.dropped)
    print(
        f"\nblocked events lost with NO on_event_dropped hook: {silent}/{N_BLOCKED}"
    )
    print("RESULT:", "PASS" if silent == 0 else "FAIL (silent loss)")
    return 0 if silent == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
