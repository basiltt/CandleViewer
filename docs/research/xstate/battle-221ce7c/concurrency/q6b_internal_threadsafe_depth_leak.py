"""Q6b - MINIMAL: after a burst of `send_threadsafe(internal=True)` the
async engine's chain depth `_raise_depth` does NOT return to 0 at
quiescence, and stays high indefinitely.

Why it matters: `_raise_depth` is the chain budget counter. If it is left
at N after the burst, the machine has only `maxIterations - N` laps of
self-generated headroom left for the rest of its life -- i.e. a
cross-thread producer using the documented `internal=True` opt-in
silently consumes another machine subsystem's runaway budget.

Measures the depth at quiescence, then after an EXTERNAL event (which is
the documented reset trigger), then proves the practical consequence:
how many laps of a genuine self-generated cycle remain.
"""

from __future__ import annotations

import asyncio

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "q6b",
    "initial": "a",
    "context": {"n": 0},
    "maxIterations": 200,
    "states": {
        "a": {"on": {"OK": "b", "SPIN": "cyc"}},
        "b": {"on": {"BACK": "a", "SPIN": "cyc"}},
        "cyc": {"always": {"target": "cyc2", "actions": ["lap"]}},
        "cyc2": {"always": {"target": "cyc", "actions": ["lap"]}},
    },
}

LAPS = {"n": 0}


def lap(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1


def mk():
    return create_machine(CFG, logic=MachineLogic(actions={"lap": lap}))


async def case(burst: int, internal: bool) -> dict:
    LAPS["n"] = 0
    itp = Interpreter(mk())
    await itp.start()
    for _ in range(burst):
        itp.send_threadsafe("OK", internal=internal)
        itp.send_threadsafe("BACK", internal=internal)
    await asyncio.sleep(1.0)
    d_quiescent = itp._raise_depth
    infl = itp._threadsafe_self_sends_in_flight
    qd = itp.queue_depth
    await asyncio.wait_for(itp.send("OK", wait=True), 5)
    await asyncio.sleep(0.2)
    d_after_external = itp._raise_depth
    # Practical consequence: how much cycle headroom is left?
    await itp.send("SPIN")
    await asyncio.sleep(0.6)
    laps = LAPS["n"]
    await itp.stop()
    return {
        "burst_pairs": burst,
        "internal": internal,
        "queue_depth_at_measure": qd,
        "inflight_at_quiescence": infl,
        "raise_depth_at_quiescence": d_quiescent,
        "raise_depth_after_external_event": d_after_external,
        "laps_available_to_a_real_cycle": laps,
        "maxIterations": 200,
    }


async def main() -> int:
    ext = await case(50, False)
    intl = await case(50, True)
    leaked = intl["raise_depth_at_quiescence"] != 0
    starved = intl["laps_available_to_a_real_cycle"] < ext[
        "laps_available_to_a_real_cycle"
    ]
    emit(
        "q6b_internal_threadsafe_depth_leak",
        {
            "external_baseline": ext,
            "internal_true": intl,
            "depth_not_reset_at_quiescence": leaked,
            "real_cycle_budget_starved": starved,
            "result": "FAIL" if (leaked or starved) else "PASS",
        },
    )
    return 1 if (leaked or starved) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
