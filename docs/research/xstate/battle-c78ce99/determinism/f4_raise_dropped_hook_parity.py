"""F4 - loop-side RAISE refusal fires on_event_dropped(queue_full) exactly
once per refusal (targets #157 reopened fix), under concurrent load.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time

logging.disable(logging.CRITICAL)
LIB = "<workspace>/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from xstate_statemachine import (  # noqa: E402
    Event,
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase  # noqa: E402

CFG = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"EV": {"actions": ["slow"]}}}},
}


def slow(*a):
    time.sleep(0.01)


class Counter(PluginBase):
    def __init__(self):
        self.drops = []

    def on_event_dropped(self, interp, event, reason):
        self.drops.append(reason)


async def main():
    machine = create_machine(CFG, logic=MachineLogic(actions={"slow": slow}))
    interp = Interpreter(
        machine, max_queue_size=4, overflow_policy=OverflowPolicy.RAISE
    )
    await interp.start()

    counter = Counter()
    interp.use(counter)

    accepted = 0
    refused_futures_with_error = 0
    lock = threading.Lock()
    all_futs = []
    futs_lock = threading.Lock()

    def hammer():
        for _ in range(60):
            fut = interp.send_threadsafe(Event("EV"))
            with futs_lock:
                all_futs.append(fut)

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # Give the loop time to drain/refuse everything, then inspect futures.
    await asyncio.sleep(3.0)
    for fut in all_futs:
        try:
            if fut.done():
                exc = fut.exception(timeout=0)
                if exc is not None:
                    refused_futures_with_error += 1
                else:
                    accepted += 1
        except Exception:
            refused_futures_with_error += 1

    await asyncio.sleep(0.3)
    await interp.stop()

    qf_drops = [d for d in counter.drops if d == "queue_full"]
    print("accepted:", accepted)
    print("refused_futures_with_error:", refused_futures_with_error)
    print("queue_full_hook_fires:", len(qf_drops))
    print(
        "parity(refused==hookfires):",
        refused_futures_with_error == len(qf_drops),
    )


if __name__ == "__main__":
    asyncio.run(main())
