# -*- coding: utf-8 -*-
"""Round-6 #166/#167/#168 soak-relevant attack.

Under soak-like concurrent load (multiple external senders hammering a
single machine while it self-generates completions via `always` +
rollback-reentry), confirm:
  (a) the async engine's per-macrostep settle budget is reset ONLY by an
      external event beginning its step, not by the mere passage of
      external sends interleaving with an in-progress chain;
  (b) a genuinely unbounded self-generated chain still trips
      (RunawayChainError observable via last_error), it is not silently
      starved-of-budget-forever by concurrent external traffic;
  (c) 16 concurrent external senders cannot themselves be mistaken for
      "the chain", and cannot indefinitely re-arm/reset the chain's trip.

This is a soak-style repeated-trials attack (many iterations, small
machine) rather than a single unit-test repro.
"""
from __future__ import annotations

import asyncio
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError

# A machine with a same-target self-loop ("always" cond false keeps it put,
# but an internal event handler re-raises itself) -- a bounded self-chain
# built from raise_self, capped by maxIterations so a design bug shows as
# EITHER "never trips" (bad: infinite loop / livelock) OR "trips too early"
# (bad: external sends wrongly charged/counted).
CONFIG = {
    "id": "chain",
    "initial": "spinning",
    "context": {"n": 0},
    "states": {
        "spinning": {
            "on": {
                "TICK": {"actions": ["bump_and_reraise"]},
                "EXTERNAL": {"actions": ["noop"]},
            },
        },
    },
}


def bump_and_reraise(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1
    # Self-generated re-entry -- an unconditional cycle. Should be charged
    # to the chain budget and trip via maxIterations, regardless of how
    # many concurrent externals are in flight.
    interp.send({"type": "TICK"})


def noop(interp, ctx, event, action_def):  # noqa: ANN001
    pass


ACTIONS = {"bump_and_reraise": bump_and_reraise, "noop": noop}


async def one_trial(n_external_senders: int) -> dict:
    logic = MachineLogic(actions=dict(ACTIONS))
    machine = create_machine(dict(CONFIG), logic=logic)
    interp = Interpreter(machine, max_queue_size=4096)
    await interp.start()

    stop = asyncio.Event()

    async def external_sender():
        while not stop.is_set():
            try:
                interp.send({"type": "EXTERNAL"})
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0)

    senders = [asyncio.create_task(external_sender()) for _ in range(n_external_senders)]

    t0 = time.perf_counter()
    tripped = False
    try:
        await asyncio.wait_for(interp.send({"type": "TICK"}, wait=True), timeout=5.0)
    except asyncio.TimeoutError:
        pass
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, RunawayChainError) or "Runaway" in repr(exc):
            tripped = True
    dt = time.perf_counter() - t0

    # Poll last_error briefly -- the trip may land asynchronously relative
    # to the send() that started the chain.
    for _ in range(50):
        if getattr(interp, "last_error", None) is not None:
            tripped = True
            break
        await asyncio.sleep(0.05)

    stop.set()
    for t in senders:
        t.cancel()
    await asyncio.gather(*senders, return_exceptions=True)
    await interp.stop(drain=False, timeout=1.0)

    return {
        "n_external_senders": n_external_senders,
        "tripped": tripped,
        "last_error": repr(getattr(interp, "last_error", None)),
        "n_reached": interp.context.get("n"),
        "dt_s": round(dt, 3),
    }


async def main():
    results = []
    for n_ext in (0, 1, 4, 16):
        r = await one_trial(n_ext)
        print(r)
        results.append(r)

    all_tripped = all(r["tripped"] for r in results)
    print("ALL_TRIPPED:", all_tripped)
    if not all_tripped:
        print("DEFECT CANDIDATE: chain did not trip under concurrent external load")


if __name__ == "__main__":
    asyncio.run(main())
