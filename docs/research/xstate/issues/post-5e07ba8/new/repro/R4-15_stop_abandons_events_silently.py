# -*- coding: utf-8 -*-
"""R4-15: events abandoned by `stop()` are lost with no `on_event_dropped`
and no log -- both a fire-and-forget send parked on a full BLOCK inbox, and
events merely queued under the default `drain=False`.

Standalone: no harness import.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine
from xstate_statemachine.models import OverflowPolicy

CONFIG = {
    "id": "counter",
    "initial": "idle",
    "context": {"n": 0},
    "strict": True,
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "states": {
        "idle": {"on": {"PING": {"actions": ["bump"]}, "STOPME": {"target": "over"}}},
        "over": {"type": "final"},
    },
}


def bump(interpreter, ctx, event, action_def):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


def counter_machine():
    return create_machine(CONFIG, logic=MachineLogic(actions={"bump": bump}))


class Accountant(PluginBase):
    def __init__(self) -> None:
        self.dropped = []

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        self.dropped.append((event.type, reason))


CAP = 4
N_BLOCKED = 5


async def scenario_block_stop() -> int:
    """A full BLOCK inbox: 5 fire-and-forget sends parked, then stop()."""
    acc = Accountant()
    interp = Interpreter(
        counter_machine(), max_queue_size=CAP, overflow_policy=OverflowPolicy.BLOCK
    )
    interp.use(acc)
    await interp.start()

    for _ in range(CAP):
        await interp.send("PING")
    assert interp.queue_depth == CAP, interp.queue_depth

    outcomes = []

    async def blocked_producer(k: int) -> None:
        try:
            await interp.send("PING")
            outcomes.append(f"{k}: send() returned normally")
        except Exception as exc:  # noqa: BLE001
            outcomes.append(f"{k}: {type(exc).__name__}: {exc}")

    tasks = [asyncio.create_task(blocked_producer(k)) for k in range(N_BLOCKED)]
    await asyncio.sleep(0)  # let each reach the spin in _enqueue_blocking

    await interp.stop()  # no drain
    await asyncio.gather(*tasks, return_exceptions=True)

    silent = N_BLOCKED - len(acc.dropped)
    print(f"[BLOCK]   producers parked={N_BLOCKED} on_event_dropped={acc.dropped}")
    for o in outcomes:
        print("   ", o)
    print(f"[BLOCK]   silent losses: {silent}/{N_BLOCKED}")
    return silent


async def scenario_default_drain_false() -> int:
    """Default drain=False: events queued but never processed by stop()."""
    acc = Accountant()
    cfg2 = {"id": "m_stop_pending", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
    machine = create_machine(cfg2, logic=MachineLogic())
    interp = Interpreter(machine)
    interp.use(acc)
    await interp.start()
    for i in range(5):
        interp.send(f"X{i}", wait=False)
    pending_before = len(interp.pending_events)
    await interp.stop()
    silent = pending_before - len(acc.dropped)
    print(f"[DRAIN=F] pending_events before stop={pending_before} on_event_dropped={acc.dropped}")
    print(f"[DRAIN=F] silent losses: {silent}/{pending_before}")
    return silent


async def main() -> int:
    s1 = await scenario_block_stop()
    s2 = await scenario_default_drain_false()
    print("EXPECTED: both scenarios fire on_event_dropped for every abandoned event (silent losses = 0).")
    ok = s1 == 0 and s2 == 0
    print("RESULT:", "PASS" if ok else "FAIL (stop() abandons events with no drop hook)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
