"""P4 (#204): invoke deferral -- ordering, settle-trip, history/parallel.

#204 defers `invoke` arming to the end of the macrostep (SCXML 6.1
statesToInvoke). Probes the seams:

Q1 #171 contract: does `await start()` still return with the initial
   configuration's children registered/addressable (send to child works)?
Q2 settle-budget trip BEFORE arming: a spinning `always` trips
   RunawayChainError inside the settle. The arming call sits after the
   loop, so the state is active -- is its invoke armed, or is the machine
   parked in an invoking state with nothing running (the #207 shape,
   reached by a different road)?
Q3 invoke in a state reached by the INITIAL descent only (no always at
   all): armed exactly once, both engines?
Q4 parallel re-entry: a state invoked, exited and RE-entered within one
   macrostep -- one arm or two?

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
    SyncInterpreter,
    create_machine,
)

CHILD = {
    "id": "kid",
    "initial": "idle",
    "states": {"idle": {"on": {"POKE": "hit"}}, "hit": {}},
}


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


async def q1_start_children_registered():
    cfg = {
        "id": "p",
        "initial": "a",
        "states": {"a": {"invoke": [{"id": "kid", "src": "kidm"}]}},
    }
    child = create_machine(json.loads(json.dumps(CHILD)), logic=MachineLogic())
    i = Interpreter(
        create_machine(cfg, logic=MachineLogic(services={"kidm": child}))
    )
    await i.start()
    names = sorted(getattr(i, "_actors", {}) or {})
    # #171: a poke right after start() must reach the child.
    await i._deliver(i, i._prepare_event("___probe___"), None, None)
    actors = getattr(i, "_actors", {}) or {}
    kid = next(
        (v for k, v in actors.items() if k.split(":")[-1] == "kid"), None
    )
    reached = None
    if kid is not None:
        kid.send("POKE")
        await asyncio.sleep(0.15)
        reached = list(kid.current_state_ids)
    await i.stop()
    return names, reached


def _settle_trip_cfg(limit=3):
    return {
        "id": "spin",
        "initial": "a",
        "maxIterations": limit,
        "states": {
            "a": {"always": {"target": "b"}},
            "b": {
                "invoke": [{"id": "k", "src": "svc"}],
                "always": {"target": "a"},
            },
        },
    }


def _svc_logic(kind, calls):
    def s(i, c, e):
        calls.append(1)
        return 1

    async def a(i, c, e):
        calls.append(1)
        await asyncio.sleep(0)
        return 1

    return MachineLogic(services={"svc": a if kind == "async def" else s})


async def q2_settle_trip_then_arm(kind):
    calls = []
    i = Interpreter(
        create_machine(_settle_trip_cfg(), logic=_svc_logic(kind, calls))
    )
    await i.start()
    await asyncio.sleep(0.3)
    out = (
        len(calls),
        sorted(i.current_state_ids),
        type(i.last_error).__name__,
        i.has_dormant_invocations,
        [(p.state_id, p.invoke_id) for p in i.pending_invocations()],
    )
    await i.stop()
    return out


def q2_sync(kind):
    calls = []
    i = SyncInterpreter(
        create_machine(_settle_trip_cfg(), logic=_svc_logic(kind, calls))
    )
    i.start()
    return (
        len(calls),
        sorted(i.current_state_ids),
        type(i.last_error).__name__,
        i.has_dormant_invocations,
        [(p.state_id, p.invoke_id) for p in i.pending_invocations()],
    )


async def q3_initial_descent(kind):
    cfg = {
        "id": "d",
        "initial": "a",
        "states": {"a": {"invoke": [{"id": "k", "src": "svc"}]}},
    }
    calls = []
    i = Interpreter(create_machine(cfg, logic=_svc_logic(kind, calls)))
    await i.start()
    await asyncio.sleep(0.2)
    n = len(calls)
    await i.stop()

    calls2 = []
    s = SyncInterpreter(
        create_machine(
            json.loads(json.dumps(cfg)), logic=_svc_logic("def", calls2)
        )
    )
    s.start()
    return n, len(calls2)


if __name__ == "__main__":
    print("SRC:", SRC)
    print("Q1 start() children        :", _run(q1_start_children_registered()))
    for k in ("def", "async def"):
        print(f"Q2 settle-trip async [{k:9}]:", _run(q2_settle_trip_then_arm(k)))
    print("Q2 settle-trip sync [def  ]:", q2_sync("def"))
    print("Q3 initial descent (a,s)   :", _run(q3_initial_descent("def")))
