"""P6 (#209): is the seed's new SETTLE standing more permissive than before?

#209 extends the seed's "user standing" to the settle budget: when the
first engine completion after `start()` consumes `_seed_pending`, the async
run loop now also resets `_settle_iterations = 0` and `_settle_tripped =
False`. That is one extra free settle budget the engine did not grant at
f28719c. #103 / #151 are exactly the class of finding where a settle budget
that restarts is a hang.

Q1: an `always` spin FED BY an invoke completion (the #166 shape) --
    total settle work before the trip, and does it still terminate?
Q2: the pure `always` spin with no invoke (no seed completion at all) --
    unchanged control.
Q3: a spin whose FIRST completion arrives late (async def service): does
    the late reset hand the spin a second full budget?
Q4: does the machine still come to rest (status, no hang) in every case?

Watchdog: each case bounded to <= 3 s of sampling.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import sys
import time

SRC = sys.argv[1] if len(sys.argv) > 1 else (
    r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref"
    r"/xstate-statemachine/src"
)
sys.path.insert(0, SRC)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

LIMIT = 6


def _always_into_invoke(limit=LIMIT):
    # #166 shape: `always` into an invoking state; the service's completion
    # re-delivers and re-settles.
    return {
        "id": "s",
        "initial": "a",
        "maxIterations": limit,
        "states": {
            "a": {"always": {"target": "b"}},
            "b": {
                "invoke": [
                    {"id": "k", "src": "svc", "onDone": {"target": "a"}}
                ]
            },
        },
    }


PURE_SPIN = {
    "id": "p",
    "initial": "a",
    "maxIterations": LIMIT,
    "states": {
        "a": {"always": {"target": "b"}},
        "b": {"always": {"target": "a"}},
    },
}


def _logic(kind, calls):
    def s(i, c, e):
        calls.append(1)
        return 1

    async def a(i, c, e):
        await asyncio.sleep(0.05)  # completion lands LATE, on an idle loop
        calls.append(1)
        return 1

    return MachineLogic(services={"svc": a if kind == "async def" else s})


def _mk(cfg, logic=None):
    return create_machine(
        json.loads(json.dumps(cfg)), logic=logic or MachineLogic()
    )


async def q_async(cfg, kind, seconds=3.0):
    calls = []
    i = Interpreter(_mk(cfg, _logic(kind, calls)))
    await i.start()
    plateau, stable, deadline = -1, 0, time.monotonic() + seconds
    while stable < 6 and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        if len(calls) == plateau:
            stable += 1
        else:
            plateau, stable = len(calls), 0
    out = (
        plateau,
        i.status,
        type(i.last_error).__name__,
        sorted(i.current_state_ids),
        stable >= 6,  # converged, not still climbing
    )
    await i.stop()
    return out


def q_sync(cfg):
    calls = []
    i = SyncInterpreter(_mk(cfg, _logic("def", calls)))
    i.start()
    return len(calls), i.status, type(i.last_error).__name__


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


if __name__ == "__main__":
    print("SRC:", SRC, "limit:", LIMIT)
    for k in ("def", "async def"):
        print(
            f"Q1/Q3 always->invoke [{k:9}]:",
            _run(q_async(_always_into_invoke(), k)),
        )
    print("Q1 sync always->invoke     :", q_sync(_always_into_invoke()))
    print("Q2 pure always spin async  :", _run(q_async(PURE_SPIN, "def", 1.5)))
    print("Q2 pure always spin sync   :", q_sync(PURE_SPIN))
