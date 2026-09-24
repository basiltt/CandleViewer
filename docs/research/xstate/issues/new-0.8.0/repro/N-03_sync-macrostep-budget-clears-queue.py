"""N-03 repro: the `SyncInterpreter` macrostep budget still discards legitimate
external events -- the two engines do not agree.

The 0.8.0 CHANGELOG says:

    "SyncInterpreter: replayed deferred events no longer count against the
     macrostep runaway budget ... The async engine already behaved correctly;
     the two now agree."

They do not. `_process_event_queue` still does `processed += 1` for *every*
event and, once `max_iterations` (default 1000) is exceeded, calls
`self._event_queue.clear()` -- silently discarding every remaining queued event.
`replay_credit` exempts only replayed deferred events, not ordinary external
ones. Batch more than 1000 plain external events through `send_events()` and the
tail vanishes with no exception and no return value to inspect.

The async `Interpreter` processes all N through the identical call.

Observed on 0.8.0, same machine, same logic, `send_events([...])`:

    batch    sync seen    async seen
      999          999           999
     1001         1000          1001
     1501         1000          1501
     3000         1000          3000

Exit 1 while the defect is present, 0 once it is fixed.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

N = 1501
BUDGET = 1000  # SyncInterpreter._process_event_queue max_iterations default

CFG = {
    "id": "bud",
    "initial": "a",
    "context": {"seen": 0},
    "states": {"a": {"on": {"T": {"target": "a", "actions": ["bump"], "reenter": True}}}},
}


def _logic() -> MachineLogic:
    def bump(_interp, ctx, _event, _action):
        ctx["seen"] = ctx.get("seen", 0) + 1

    return MachineLogic(actions={"bump": bump})


def sync_seen() -> tuple[int, int]:
    interp = SyncInterpreter(create_machine(CFG, logic=_logic()))
    interp.start()
    interp.send_events(["T"] * N)
    seen, depth = interp.context.get("seen", 0), interp.queue_depth
    try:
        interp.stop()
    except Exception:  # noqa: BLE001 - teardown must not mask the result
        pass
    return seen, depth


async def async_seen() -> tuple[int, int]:
    interp = Interpreter(create_machine(CFG, logic=_logic()))
    await interp.start()
    await interp.send_events(["T"] * N)
    try:
        await asyncio.wait_for(interp.stop(drain=True), timeout=30.0)
    except Exception:  # noqa: BLE001
        pass
    return interp.context.get("seen", 0), 0


async def main() -> int:
    s, s_depth = sync_seen()
    a, _ = await async_seen()

    print(f"OBSERVED events batched via send_events : {N}")
    print(f"OBSERVED SyncInterpreter processed      : {s}  (queue_depth after: {s_depth})")
    print(f"OBSERVED Interpreter (async) processed  : {a}")
    print(f"EXPECTED both engines processed         : {N}")

    if a == N and s < N:
        lost = N - s
        print(
            f"OBSERVED lost silently by sync engine   : {lost} "
            f"(budget={BUDGET}; queue cleared, no exception, no signal)"
        )
        print("RESULT: DEFECT REPRODUCED")
        return 1
    if a == N and s == N:
        print("RESULT: NOT REPRODUCED (fixed)")
        return 0
    print("RESULT: INCONCLUSIVE - the async control did not process every event")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
