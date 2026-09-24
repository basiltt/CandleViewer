"""K-4/K-5 probes: send_threadsafe classification, internal= escape hatch.

1. internal=False from INSIDE an action -> does it dodge maxIterations?
2. internal=True from a FOREIGN thread -> bypasses the bounded inbox and
   OverflowPolicy entirely (unbounded internal queue).
3. self-sends-in-flight counter leak when the deliver coroutine never runs.
"""
import asyncio
import threading
import time

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    create_machine,
)
from xstate_statemachine.exceptions import QueueOverflowError, RunawayChainError

CFG = {
    "id": "t",
    "initial": "a",
    "maxIterations": 20,
    "context": {"n": 0},
    "states": {"a": {"on": {"PING": {"target": "a", "actions": ["again"]}}}},
}


async def probe_internal_false_dodge():
    """An action re-triggers itself via send_threadsafe(internal=False)."""
    hits = {"n": 0}

    def again(i, c, e, a):
        hits["n"] += 1
        if hits["n"] < 200:
            i.send_threadsafe("PING", internal=False)

    m = create_machine(CFG, logic=MachineLogic(actions={"again": again}))
    i = Interpreter(m)
    await i.start()
    await i.send("PING")
    await asyncio.sleep(0.4)
    print(f"[1] internal=False from action: hits={hits['n']} "
          f"status={i.status} err={type(i.error).__name__ if i.error else None}")
    print("    -> budget maxIterations=20; dodged" if hits["n"] > 25
          else "    -> budget enforced")
    await i.stop()


async def probe_internal_true_bypasses_backpressure():
    """A FOREIGN producer claims internal=True on a bounded RAISE inbox."""
    cfg = {"id": "b", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
    m = create_machine(cfg, logic=MachineLogic())
    i = Interpreter(m, max_queue_size=2, overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    # stall the loop so nothing drains
    stall = asyncio.Event()

    honest_refused = 0
    forged_ok = 0
    loop = asyncio.get_running_loop()

    def producer():
        nonlocal honest_refused, forged_ok
        for _ in range(50):
            try:
                i.send_threadsafe("X")
            except QueueOverflowError:
                honest_refused += 1
        for _ in range(500):
            try:
                i.send_threadsafe("X", internal=True)
                forged_ok += 1
            except QueueOverflowError:
                pass

    t = threading.Thread(target=producer)
    t.start()
    t.join()
    await asyncio.sleep(0.2)
    print(f"[2] bounded inbox size=2 RAISE: honest refused={honest_refused}, "
          f"forged internal=True accepted={forged_ok}")
    print(f"    internal_queue depth after flush={len(i._internal_queue)} "
          f"in_flight={i._threadsafe_self_sends_in_flight} status={i.status} "
          f"err={type(i.error).__name__ if i.error else None}")
    await i.stop()


def probe_counter_leak():
    """send_threadsafe(internal=True) scheduled on a loop that is closed
    before `_deliver` runs: the in-flight counter never decrements."""

    holder = {}

    async def setup():
        cfg = {"id": "c", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
        m = create_machine(cfg, logic=MachineLogic())
        i = Interpreter(m)
        await i.start()
        holder["i"] = i
        holder["loop"] = asyncio.get_running_loop()
        await asyncio.sleep(0.05)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(setup())
    i = holder["i"]
    # schedule then immediately stop the loop so _deliver never runs
    for _ in range(5):
        i.send_threadsafe("X", internal=True)
    loop.stop()
    print(f"[3] in-flight counter after loop stop: "
          f"{i._threadsafe_self_sends_in_flight} (expected 0)")
    loop.close()


async def main():
    await probe_internal_false_dodge()
    await probe_internal_true_bypasses_backpressure()


if __name__ == "__main__":
    asyncio.run(main())
    probe_counter_leak()
