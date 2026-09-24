"""Q1b - MINIMAL repro of the Q1 finding.

One single external event, delivered periodically, is enough to reset the
per-macrostep settle budget on `Interpreter`, so an `always` cycle that
trips at lap 1000 when left alone runs FOREVER when any external traffic
exists. The machine livelocks: the run loop never yields a settled step,
`send(wait=True)` never resolves, `stop()` is the only exit.

Watchdog-bounded (25 s). A timeout IS the observed result.
"""

from __future__ import annotations

import asyncio
import time

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError

LAPS = {"n": 0}

CFG = {
    "id": "spin",
    "initial": "idle",
    "context": {"n": 0},
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


async def case(pokes: int, period: float) -> dict:
    LAPS["n"] = 0
    itp = Interpreter(
        create_machine(
            CFG, logic=MachineLogic(actions={"lap": lap, "tick": tick})
        )
    )
    await itp.start()

    async def poker() -> None:
        for _ in range(pokes):
            await itp.send("POKE")
            await asyncio.sleep(period)

    t0 = time.perf_counter()
    pk = asyncio.create_task(poker())
    await itp.send("GO")

    samples = []
    tripped_at = None
    while time.perf_counter() - t0 < 6.0:
        await asyncio.sleep(0.5)
        samples.append(LAPS["n"])
        if tripped_at is None and isinstance(
            itp.last_error, RunawayChainError
        ):
            tripped_at = LAPS["n"]
        if len(samples) >= 3 and samples[-1] == samples[-3]:
            break  # laps stopped growing -> really settled
    pk.cancel()
    try:
        await pk
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass

    still_spinning = len(samples) >= 2 and samples[-1] > samples[-2]
    wedged = None
    try:
        await asyncio.wait_for(itp.send("POKE", wait=True), 3)
        wedged = False
    except asyncio.TimeoutError:
        wedged = True
    try:
        await asyncio.wait_for(itp.stop(), 5)
        stopped = "ok"
    except asyncio.TimeoutError:
        stopped = "HUNG"
    return {
        "external_pokes": pokes,
        "poke_period_s": period,
        "lap_samples_per_0.5s": samples,
        "first_trip_at_lap": tripped_at,
        "still_spinning_at_end": still_spinning,
        "send_wait_true_wedged": wedged,
        "stop": stopped,
    }


async def main() -> int:
    res = {
        "baseline_no_external": await case(0, 1.0),
        "one_poke_per_100ms": await case(60, 0.1),
        "one_poke_per_1s": await case(6, 1.0),
    }
    base = res["baseline_no_external"]
    bad = [
        k
        for k, v in res.items()
        if k != "baseline_no_external"
        and (v["still_spinning_at_end"] or v["send_wait_true_wedged"])
    ]
    emit(
        "q1b_minimal_budget_reset",
        {
            **res,
            "baseline_trips": base["first_trip_at_lap"] is not None,
            "cases_livelocked_by_external_traffic": bad,
            "result": "FAIL" if bad else "PASS",
        },
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
