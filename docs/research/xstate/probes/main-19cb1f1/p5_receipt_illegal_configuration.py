"""P5 (#208): can the new "refuse ok over illegal configuration" produce a
FALSE error receipt on a legitimate machine?

#208 adds: at receipt-resolution time, if the step ended `running` with
`_configuration_is_legal()` false, the receipt reports an error instead of
`ok`. Legality is recursive (every parallel region must have an active,
legal leaf). The risk is a legitimate chart whose settled configuration the
legality test does not accept -- a receipt that says "no legal
configuration" for a step that did exactly what the chart says.

Q1: plain parallel machine, an event that transitions in ONE region only --
    does every receipt still report ok?
Q2: parallel with a region in a `final` child (onDone-reached) -- ok?
Q3: a targetless `always` guard chart + parallel, 40 events -- any false
    error receipts?
Q4: control -- the genuinely torn case (`maxIterations` cut) still reports
    an error, i.e. the belt-and-braces path is reachable at all.

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

PAR = {
    "id": "par",
    "type": "parallel",
    "states": {
        "r1": {
            "initial": "a",
            "states": {"a": {"on": {"L": "b"}}, "b": {"on": {"L": "a"}}},
        },
        "r2": {
            "initial": "x",
            "states": {"x": {"on": {"R": "y"}}, "y": {"on": {"R": "x"}}},
        },
    },
}

PAR_FINAL = {
    "id": "pf",
    "type": "parallel",
    "states": {
        "r1": {
            "initial": "a",
            "states": {"a": {"on": {"DONE1": "d"}}, "d": {"type": "final"}},
        },
        "r2": {
            "initial": "x",
            "states": {"x": {"on": {"DONE2": "e"}}, "e": {"type": "final"}},
        },
    },
}

GUARDED = {
    "id": "g",
    "type": "parallel",
    "context": {"n": 0},
    "states": {
        "r1": {
            "initial": "a",
            "states": {
                "a": {"on": {"L": "b"}},
                "b": {"always": [{"target": "a", "guard": "even"}]},
            },
        },
        "r2": {"initial": "x", "states": {"x": {"on": {"L": {}}}}},
    },
}


def _mk(cfg, **kw):
    return create_machine(json.loads(json.dumps(cfg)), **kw)


async def _receipts(cfg, events, logic=None):
    i = Interpreter(_mk(cfg, logic=logic or MachineLogic()))
    await i.start()
    out = []
    for ev in events:
        r = await i.send(ev, wait=True)
        out.append((ev, r.error is None,
                    None if r.error is None else type(r.error).__name__))
    await i.stop()
    return out


async def q1():
    return await _receipts(PAR, ["L", "R", "L", "R", "L", "R"])


async def q2():
    return await _receipts(PAR_FINAL, ["DONE1", "DONE2"])


async def q3():
    bump = {"n": 0}

    def even(c, e):
        bump["n"] += 1
        return bump["n"] % 2 == 0

    rs = await _receipts(
        GUARDED, ["L"] * 40, logic=MachineLogic(guards={"even": even})
    )
    bad = [r for r in rs if not r[1]]
    return len(rs), len(bad), bad[:3]


async def q4_control():
    cfg = {
        "id": "cut",
        "initial": "a",
        "maxIterations": 3,
        "states": {
            "a": {
                "on": {
                    "GO": {
                        "target": "a",
                        "actions": [
                            {"type": "raise", "params": {"event": "GO"}}
                        ],
                    }
                }
            }
        },
    }
    i = Interpreter(_mk(cfg, logic=MachineLogic()))
    await i.start()
    r = await i.send("GO", wait=True)
    await i.stop()
    return r.error is None, type(r.error).__name__


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


if __name__ == "__main__":
    print("SRC:", SRC)
    print("Q1 parallel one-region     :", _run(q1()))
    print("Q2 parallel finals         :", _run(q2()))
    print("Q3 guarded always x40      :", _run(q3()))
    print("Q4 control (real cut)      :", _run(q4_control()))
