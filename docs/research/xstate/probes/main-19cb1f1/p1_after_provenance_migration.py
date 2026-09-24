"""P1 (O-1/O-2): #203 `after` now matches only engine-minted AfterEvent.

Q1: a v2 snapshot record written by a PRE-#195 library (kind="after", no
    "engine" flag) restores as a public AfterEvent -> does it still drive
    the `after` transition it was persisted for?
Q2: does a genuine round-trip (persist from this library) still fire?
Q3: SimulatedClock-driven `after` still fires (engine mint path intact)?

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else (
    r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref"
    r"/xstate-statemachine/src"
)
sys.path.insert(0, SRC)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.events import restore_event  # noqa: E402

CFG = {
    "id": "t",
    "initial": "wait",
    "states": {
        "wait": {"after": {60000: {"target": "late"}}},
        "late": {},
    },
}


def _mk():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def q1_legacy_v2_record():
    # A record as a pre-#195 (0.8.0) writer would have produced it:
    # kind is recorded, but there is no "engine": true flag.
    rec = {"kind": "after", "type": "after.60000.t.wait", "scheduled_for": 1.0}
    ev = restore_event(rec)
    i = Interpreter(_mk())
    await i.start()
    before = list(i.current_state_ids)
    i.send(ev)
    await asyncio.sleep(0.15)
    after = list(i.current_state_ids)
    await i.stop()
    return type(ev).__name__, before, after


async def q2_genuine_roundtrip():
    from xstate_statemachine.events import persist_event

    try:
        from xstate_statemachine.events import engine_after

        mint = engine_after("after.60000.t.wait", 1.0, 1.0)
    except ImportError:  # pre-#195 library
        from xstate_statemachine.events import AfterEvent

        mint = AfterEvent("after.60000.t.wait", 1.0, 1.0)
    rec = persist_event(mint)
    ev = restore_event(json.loads(json.dumps(rec)))
    i = Interpreter(_mk())
    await i.start()
    i.send(ev)
    await asyncio.sleep(0.15)
    out = list(i.current_state_ids)
    await i.stop()
    return rec, type(ev).__name__, out


async def q3_simulated_clock():
    from xstate_statemachine import SimulatedClock

    clk = SimulatedClock()
    i = Interpreter(_mk(), clock=clk)
    await i.start()
    maybe = clk.increment(61000)
    if asyncio.iscoroutine(maybe) or asyncio.isfuture(maybe):
        await maybe
    await asyncio.sleep(0.15)
    out = list(i.current_state_ids)
    await i.stop()
    return out


if __name__ == "__main__":
    print("SRC:", SRC)
    print("Q1 legacy-v2 after record :", _run(q1_legacy_v2_record()))
    print("Q2 genuine round-trip     :", _run(q2_genuine_roundtrip()))
    print("Q3 SimulatedClock         :", _run(q3_simulated_clock()))
