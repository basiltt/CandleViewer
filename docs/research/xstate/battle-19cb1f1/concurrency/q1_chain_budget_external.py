"""Q1 - chain/settle budget under concurrent EXTERNAL senders.

Round-6 made the async settle budget per-macrostep ON THE INSTANCE, reset
only when an external event begins its step. The attack: while a machine
is burning a self-generated `always` cycle, 16 threads/tasks hammer it
with external events. If an external arrival resets the bound mid-chain,
the runaway becomes unbounded under load -- exactly when it matters.

Asserted:
  A1 the chain/settle trip IS observed (last_error is RunawayChainError)
  A2 the trip happens within a bounded number of laps even with 16
     concurrent external senders running throughout
  A3 the machine survives: still answers an event after the trip
"""

from __future__ import annotations

import asyncio
import threading
import time

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.exceptions import RunawayChainError

LAPS = {"n": 0}

# `always` ping-pong: a self-generated cycle with no external input.
CFG = {
    "id": "spin",
    "initial": "idle",
    "context": {"n": 0},
    "strict": False,
    "states": {
        "idle": {"on": {"GO": {"target": "a"}, "POKE": {"actions": ["tick"]}}},
        "a": {"always": {"target": "b", "actions": ["lap"]}},
        "b": {"always": {"target": "a", "actions": ["lap"]}},
    },
}


def lap(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1


def tick(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] += 1


def machine():
    return create_machine(
        CFG, logic=MachineLogic(actions={"lap": lap, "tick": tick})
    )


async def run(n_senders: int) -> dict:
    LAPS["n"] = 0
    itp = Interpreter(machine())
    await itp.start()

    stop = threading.Event()
    sent = {"n": 0}

    def producer() -> None:
        while not stop.is_set():
            try:
                itp.send_threadsafe("POKE")
                sent["n"] += 1
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.001)

    threads = [
        threading.Thread(target=producer, daemon=True)
        for _ in range(n_senders)
    ]
    for t in threads:
        t.start()
    await asyncio.sleep(0.05)  # let the storm reach steady state

    t0 = time.perf_counter()
    await itp.send("GO")
    # Watchdog: if the bound is defeated the laps never stop.
    tripped = False
    while time.perf_counter() - t0 < 10.0:
        await asyncio.sleep(0.05)
        if isinstance(itp.last_error, RunawayChainError):
            tripped = True
            break
    wall = time.perf_counter() - t0
    laps_at_trip = LAPS["n"]

    stop.set()
    for t in threads:
        t.join(timeout=1)
    await asyncio.sleep(0.2)
    laps_after = LAPS["n"]

    # A3: still usable?
    alive = None
    try:
        r = await asyncio.wait_for(itp.send("POKE", wait=True), 3)
        alive = f"receipt changed={r.changed} error={r.error!r}"
    except Exception as exc:  # noqa: BLE001
        alive = f"raised {type(exc).__name__}"
    status = itp.status
    await itp.stop()
    return {
        "senders": n_senders,
        "external_sent": sent["n"],
        "tripped": tripped,
        "laps_at_trip": laps_at_trip,
        "laps_after_settling": laps_after,
        "seconds_to_trip": round(wall, 3),
        "still_alive": alive,
        "status": status,
    }


async def main() -> int:
    res = {}
    for n in (0, 16):
        res[f"senders_{n}"] = await run(n)
    quiet = res["senders_0"]
    loud = res["senders_16"]
    ok = (
        quiet["tripped"]
        and loud["tripped"]
        and loud["laps_at_trip"] <= quiet["laps_at_trip"] * 5 + 100
        and loud["laps_after_settling"] == loud["laps_at_trip"]
    )
    emit(
        "q1_chain_budget_external",
        {
            **res,
            "A1_trip_observed_both": quiet["tripped"] and loud["tripped"],
            "A2_bound_not_reset_by_external": ok,
            "result": "PASS" if ok else "FAIL",
        },
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
