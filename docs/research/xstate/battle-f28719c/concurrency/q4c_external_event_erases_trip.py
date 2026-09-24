"""Q4c - the real mechanism behind the Q4 engine disagreement:
on the async engine an EXTERNAL event ERASES the RunawayChainError from
`last_error`; on the sync engine the trip evidence survives.

Sequence (identical on both engines):
  1. start a machine with a self-generated cycle  -> it trips
  2. read last_error                              -> RunawayChainError
  3. send ONE unrelated external event
  4. read last_error again

Async: step 4 reads None. Sync: step 4 still reads RunawayChainError.
Because step 3 also re-buys a full `maxIterations` budget (see q1c), a
machine driven by any external traffic burns maxIterations laps per
event while `last_error` reads clean the whole time.
"""

from __future__ import annotations

import asyncio

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import RunawayChainError

LAPS = {"n": 0}


def act(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1


def nop(i, ctx, e, ad):  # noqa: ANN001
    pass


def svc_ok(i, ctx, e):  # noqa: ANN001
    return {"v": 1}


CFG = {
    "id": "q4c",
    "initial": "ver",
    "context": {"n": 0},
    "maxIterations": 200,
    "states": {
        "ver": {
            "invoke": {
                "src": "ok",
                "onDone": {"target": "back", "actions": ["act"]},
                "onError": {"target": "back", "actions": ["act"]},
            },
            "on": {"PING": {"actions": ["nop"]}},
        },
        "back": {
            "always": {"target": "ver", "actions": ["act"]},
            "on": {"PING": {"actions": ["nop"]}},
        },
    },
}


def mk():
    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={"act": act, "nop": nop}, services={"ok": svc_ok}
        ),
    )


def label(err) -> str:  # noqa: ANN001
    if err is None:
        return "None"
    return type(err).__name__


async def main() -> int:
    LAPS["n"] = 0
    a = Interpreter(mk())
    await asyncio.wait_for(a.start(), 10)
    await asyncio.sleep(0.5)
    a_before = label(a.last_error)
    a_laps_before = LAPS["n"]
    await asyncio.wait_for(a.send("PING", wait=True), 15)
    await asyncio.sleep(0.3)
    a_after = label(a.last_error)
    a_laps_after = LAPS["n"]
    await a.stop()

    LAPS["n"] = 0
    s = SyncInterpreter(mk())
    s.start()
    s_before = label(s.last_error)
    s_laps_before = LAPS["n"]
    s.send("PING")
    s_after = label(s.last_error)
    s_laps_after = LAPS["n"]
    s.stop()

    erased = a_before == "RunawayChainError" and a_after == "None"
    emit(
        "q4c_external_event_erases_trip",
        {
            "async": {
                "last_error_after_trip": a_before,
                "laps_before_PING": a_laps_before,
                "last_error_after_one_external_PING": a_after,
                "laps_after_PING": a_laps_after,
                "laps_bought_by_one_external_event":
                    a_laps_after - a_laps_before,
            },
            "sync": {
                "last_error_after_trip": s_before,
                "laps_before_PING": s_laps_before,
                "last_error_after_one_external_PING": s_after,
                "laps_after_PING": s_laps_after,
                "laps_bought_by_one_external_event":
                    s_laps_after - s_laps_before,
            },
            "async_erases_trip_evidence": erased,
            "sync_erases_trip_evidence": (
                s_before == "RunawayChainError" and s_after == "None"
            ),
            "engines_agree": a_after == s_after,
            "result": "FAIL" if erased else "PASS",
        },
    )
    return 1 if erased else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
