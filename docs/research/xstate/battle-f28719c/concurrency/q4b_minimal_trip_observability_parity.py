"""Q4b - MINIMAL: async engine bounds the rollback/invoke cycle but the
trip is NOT observable, while the sync engine reports it.

From the Q4 fuzz: for `rollback` and `invoke_cycle` shapes, both engines
terminate (no livelock -- the round-6 headline holds), but
`SyncInterpreter.last_error` is a `RunawayChainError` and
`Interpreter.last_error` is `None` on the same config. An operator
polling `last_error` to detect a runaway sees the async machine as
healthy while it burns `maxIterations` laps per external event.

Deterministic, both engines, prints lap counts so the work is visible.
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


def svc_ok(i, ctx, e):  # noqa: ANN001
    return {"v": 1}


def cfg(shape: str, iters: int) -> dict:
    if shape == "rollback":
        states = {
            "ver": {
                "invoke": {
                    "src": "ok",
                    "onDone": {"target": "back", "actions": ["act"]},
                    "onError": {"target": "back", "actions": ["act"]},
                }
            },
            "back": {"always": {"target": "ver", "actions": ["act"]}},
        }
    else:  # invoke_cycle
        states = {
            "ver": {
                "invoke": {
                    "src": "ok",
                    "onDone": {"target": "arm", "actions": ["act"]},
                    "onError": {"target": "arm"},
                }
            },
            "arm": {"always": {"target": "ver", "actions": ["act"]}},
        }
    return {
        "id": "q4b",
        "initial": "ver",
        "context": {"n": 0},
        "maxIterations": iters,
        "states": states,
    }


def mk(c: dict):
    return create_machine(
        c,
        logic=MachineLogic(actions={"act": act}, services={"ok": svc_ok}),
    )


async def one(shape: str, iters: int) -> dict:
    LAPS["n"] = 0
    a = Interpreter(mk(cfg(shape, iters)))
    await asyncio.wait_for(a.start(), 10)
    await asyncio.sleep(0.4)
    a_laps = LAPS["n"]
    a_trip = isinstance(a.last_error, RunawayChainError)
    a_err = repr(a.last_error)
    await a.stop()

    LAPS["n"] = 0
    s = SyncInterpreter(mk(cfg(shape, iters)))
    s.start()
    s_laps = LAPS["n"]
    s_trip = isinstance(s.last_error, RunawayChainError)
    s_err = repr(s.last_error)
    s.stop()
    return {
        "shape": shape,
        "maxIterations": iters,
        "async_laps": a_laps,
        "async_trip_observable": a_trip,
        "async_last_error": a_err[:110],
        "sync_laps": s_laps,
        "sync_trip_observable": s_trip,
        "sync_last_error": s_err[:110],
        "parity": a_trip == s_trip,
    }


async def main() -> int:
    rows = []
    for shape in ("rollback", "invoke_cycle"):
        for iters in (50, 200, 1000):
            rows.append(await one(shape, iters))
    bad = [r for r in rows if not r["parity"]]
    emit(
        "q4b_minimal_trip_observability_parity",
        {
            "rows": rows,
            "parity_violations": bad,
            "violation_count": len(bad),
            "result": "FAIL" if bad else "PASS",
        },
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
