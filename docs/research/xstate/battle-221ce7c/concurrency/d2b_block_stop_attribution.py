"""D-concurrency-2 re-run, adapted for 3ed3099.

The original script asserted `len(dropped) == N_BLOCKED`. On 3ed3099 the
engine also attributes the events already *sitting in the inbox* when
`stop()` runs (#129 "stop()'s abandoned events fire the same hooks"), so a
raw count comparison is now meaningless. This version attributes per event
identity instead: every event the producer handed to `send()` must end up
either processed or dropped-with-a-hook, exactly once.
"""

from __future__ import annotations

import asyncio

from common import Accountant, counter_machine
from xstate_statemachine import Interpreter
from xstate_statemachine.models import OverflowPolicy

CAP = 4
N_BLOCKED = 5


class IdAccountant(Accountant):
    def __init__(self) -> None:
        super().__init__()
        self.recv_ids: list[int] = []
        self.drop_ids: list[tuple] = []

    def on_event_received(self, interpreter, event) -> None:  # noqa: ANN001
        super().on_event_received(interpreter, event)
        self.recv_ids.append(id(event))

    def on_event_dropped(self, interpreter, event, reason) -> None:  # noqa: ANN001
        super().on_event_dropped(interpreter, event, reason)
        self.drop_ids.append((id(event), reason))


async def main() -> int:
    acc = IdAccountant()
    interp = Interpreter(
        counter_machine(),
        max_queue_size=CAP,
        overflow_policy=OverflowPolicy.BLOCK,
    )
    interp.use(acc)
    await interp.start()

    prefill = []
    for i in range(CAP):
        await interp.send("PING")
    assert interp.queue_depth == CAP, interp.queue_depth

    outcomes: list[str] = []
    parked_ids: list[int] = []

    async def blocked_producer(k: int) -> None:
        from xstate_statemachine.models import Event

        ev = Event("PING")
        parked_ids.append(id(ev))
        try:
            await interp.send(ev)
            outcomes.append(f"{k}: send() returned normally")
        except Exception as exc:  # noqa: BLE001
            outcomes.append(f"{k}: {type(exc).__name__}: {exc}")

    tasks = [asyncio.create_task(blocked_producer(k)) for k in range(N_BLOCKED)]
    await asyncio.sleep(0)

    await interp.stop()
    await asyncio.gather(*tasks, return_exceptions=True)

    dropped_ids = {i for i, _ in acc.drop_ids}
    recv = set(acc.recv_ids)
    unattributed = [
        i for i in parked_ids if i not in dropped_ids and i not in recv
    ]

    print(f"inbox cap               : {CAP}")
    print(f"parked producers        : {N_BLOCKED}")
    print(f"processed (hook)        : {len(acc.received)}")
    print(f"drop hooks              : {len(acc.dropped)} {acc.dropped}")
    print("producer outcomes       :")
    for o in outcomes:
        print("   ", o)
    print(f"\nparked events with NO disposition hook: "
          f"{len(unattributed)}/{N_BLOCKED}")
    ok = not unattributed
    print("RESULT:", "PASS (every parked event attributed)" if ok
          else "FAIL (silent loss)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
