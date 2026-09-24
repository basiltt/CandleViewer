"""F1 — async chain budget under 16 concurrent external senders (targets #166/#120).

Claim under test: the per-macrostep settle budget on Interpreter is reset ONLY
by an external event starting its step; a self-generated chain (always-loop)
must still trip RunawayChainError even while 16 threads are hammering
send_threadsafe() concurrently (external traffic must not silently "refresh"
the budget and mask a real runaway).
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time

logging.disable(logging.CRITICAL)
LIB = "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from xstate_statemachine import Event, Interpreter, MachineLogic, create_machine  # noqa: E402

# A machine with an unconditional `always` self-loop (n increments forever).
CONFIG = {
    "id": "chainvext",
    "initial": "loop",
    "context": {"n": 0},
    "states": {
        "loop": {
            "entry": ["bump"],
            "always": [{"target": "loop", "reenter": True}],
            "on": {"PING": {"actions": ["noop"]}},
        }
    },
}


def bump(interp, ctx, ev):
    ctx["n"] = ctx.get("n", 0) + 1


def noop(interp, ctx, ev):
    ctx["ext"] = ctx.get("ext", 0) + 1


async def main():
    logic = MachineLogic(actions={"bump": bump, "noop": noop})
    machine = create_machine(CONFIG, logic=logic)
    interp = Interpreter(machine, max_queue_size=100000)
    await interp.start()

    stop_flag = threading.Event()
    accepted = {"n": 0}
    lock = threading.Lock()

    def hammer():
        while not stop_flag.is_set():
            try:
                interp.send_threadsafe(Event("PING"))
                with lock:
                    accepted["n"] += 1
            except Exception:
                pass
            time.sleep(0)

    threads = [threading.Thread(target=hammer, daemon=True) for _ in range(16)]
    for t in threads:
        t.start()

    # Give the external hammer a moment to start racing the self-chain.
    start = time.time()
    tripped = False
    while time.time() - start < 15:
        if interp.last_error is not None:
            tripped = True
            break
        await asyncio.sleep(0.05)

    stop_flag.set()
    for t in threads:
        t.join(timeout=2)

    print("tripped:", tripped)
    print("last_error:", type(interp.last_error).__name__ if interp.last_error else None)
    print("external_accepted (approx):", accepted["n"])
    print("ctx_ext:", interp.context.get("ext"))
    await interp.stop()


if __name__ == "__main__":
    asyncio.run(main())
