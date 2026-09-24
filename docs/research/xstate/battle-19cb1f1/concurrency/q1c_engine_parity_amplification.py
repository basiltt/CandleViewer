"""Q1c - engine parity for the Q1b amplification, and the sticky question.

Two questions the minimal repro raises:

  1. Does `SyncInterpreter` do the same? (Its budget is the #103/#151
     instance counter the async fix was modelled on.) If the sync engine
     also re-arms per external event, the behaviour is a shared design
     choice; if not, it is an async-only regression.
  2. Once the cycle has TRIPPED, is the state that remains "tripped"
     (cheap: one wasted lap per event) or is a full fresh 1000-lap budget
     handed out on every subsequent external event (expensive)?
"""

from __future__ import annotations

import asyncio
import time

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
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


def mk():
    return create_machine(
        CFG, logic=MachineLogic(actions={"lap": lap, "tick": tick})
    )


def sync_case(n_pokes: int) -> dict:
    LAPS["n"] = 0
    itp = SyncInterpreter(mk())
    itp.start()
    t0 = time.perf_counter()
    itp.send("GO")
    after_go = LAPS["n"]
    per_poke = []
    for _ in range(n_pokes):
        before = LAPS["n"]
        itp.send("POKE")
        per_poke.append(LAPS["n"] - before)
    itp.stop()
    return {
        "engine": "sync",
        "laps_for_GO": after_go,
        "laps_per_subsequent_POKE": per_poke,
        "total_laps": LAPS["n"],
        "wall_s": round(time.perf_counter() - t0, 3),
        "trip_observed": isinstance(itp.last_error, RunawayChainError),
    }


async def async_case(n_pokes: int) -> dict:
    LAPS["n"] = 0
    itp = Interpreter(mk())
    await itp.start()
    t0 = time.perf_counter()
    await asyncio.wait_for(itp.send("GO", wait=True), 20)
    after_go = LAPS["n"]
    per_poke = []
    for _ in range(n_pokes):
        before = LAPS["n"]
        await asyncio.wait_for(itp.send("POKE", wait=True), 20)
        per_poke.append(LAPS["n"] - before)
    trip = isinstance(itp.last_error, RunawayChainError)
    await itp.stop()
    return {
        "engine": "async",
        "laps_for_GO": after_go,
        "laps_per_subsequent_POKE": per_poke,
        "total_laps": LAPS["n"],
        "wall_s": round(time.perf_counter() - t0, 3),
        "trip_observed": trip,
    }


async def main() -> int:
    s = sync_case(5)
    a = await async_case(5)
    # The question: is a *subsequent* external event cheap (<=2 laps, the
    # tripped state) or does it buy a whole fresh budget (~1000 laps)?
    amplifies_async = max(a["laps_per_subsequent_POKE"]) > 100
    amplifies_sync = max(s["laps_per_subsequent_POKE"]) > 100
    emit(
        "q1c_engine_parity_amplification",
        {
            "sync": s,
            "async": a,
            "async_per_event_rebuys_full_budget": amplifies_async,
            "sync_per_event_rebuys_full_budget": amplifies_sync,
            "engines_agree": amplifies_async == amplifies_sync,
            "result": "PASS" if not amplifies_async else "FAIL",
        },
    )
    return 0 if not amplifies_async else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
