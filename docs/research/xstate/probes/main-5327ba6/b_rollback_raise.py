"""B — rollback withdrawing `raise`d events (#27), hostile shapes.

B1  raise from the ENTRY action of a partially-entered nested+parallel
    target, then a LATER entry action fails -> are ALL raises from that
    action list withdrawn?
B2  a raise from an EARLIER, successful transition in the same macrostep
    must NOT be withdrawn by a later transition's rollback.
B3  raise in an EXIT action, then a transition action fails.
B4  raise + raise + fail: both withdrawn, count correct.
B5  raise inside a CHILD ACTOR's action while the PARENT rolls back --
    the child's own queue must be untouched.
B6  targetless/internal self-transition: raise then fail.
B7  rollback un-counts the raise from the runaway budget (no false trip).
B8  "fail" policy: same withdrawal as "rollback".
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _h  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)

SEEN: list = []


def _seen(tag):
    def act(i, c, e, a):
        SEEN.append(tag)

    return act


def boom(i, c, e, a):
    raise RuntimeError("boom")


# --------------------------------------------------------------- B1
@_h.probe(
    "B1",
    "raise in entry of parallel region A, region B entry fails -> raise withdrawn",
    {"seen": [], "state": ["p.idle"]},
)
async def b1():
    SEEN.clear()
    cfg = {
        "id": "p",
        "initial": "idle",
        "context": {},
        "actionErrorPolicy": "rollback",
        "states": {
            "idle": {"on": {"GO": "work", "PING": {"actions": ["notePing"]}}},
            "work": {
                "type": "parallel",
                "states": {
                    "ra": {
                        "initial": "x",
                        "states": {
                            "x": {
                                "entry": [
                                    {"type": "raise", "params": {"event": "PING"}}
                                ]
                            }
                        },
                    },
                    "rb": {
                        "initial": "y",
                        "states": {"y": {"entry": ["boom"]}},
                    },
                },
            },
        },
    }
    m = create_machine(
        cfg, logic=MachineLogic(actions={"boom": boom, "notePing": _seen("PING")})
    )
    i = Interpreter(m)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.15)
    out = {"seen": list(SEEN), "state": sorted(i.current_state_ids)}
    await i.stop()
    return out


# --------------------------------------------------------------- B2
@_h.probe(
    "B2",
    "raise from an EARLIER transition survives a LATER transition's rollback",
    {"seen": ["EARLY"], "ok": True},
)
async def b2():
    SEEN.clear()
    cfg = {
        "id": "e",
        "initial": "a",
        "context": {},
        "actionErrorPolicy": "rollback",
        "states": {
            "a": {
                "on": {
                    "GO": {
                        "target": "b",
                        "actions": [{"type": "raise", "params": {"event": "EARLY"}}],
                    }
                }
            },
            "b": {
                "on": {
                    "EARLY": {"target": "c", "actions": ["noteEarly"]},
                }
            },
            "c": {"entry": ["boom"], "on": {"EARLY": {"actions": ["noteEarly"]}}},
        },
    }
    m = create_machine(
        cfg,
        logic=MachineLogic(actions={"boom": boom, "noteEarly": _seen("EARLY")}),
    )
    i = Interpreter(m)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.15)
    out = {"seen": list(SEEN), "ok": "e.b" in i.current_state_ids}
    await i.stop()
    return out


# --------------------------------------------------------------- B3
@_h.probe("B3", "raise in EXIT action, transition action then fails", {"seen": [], "state": ["x.a"]})
async def b3():
    SEEN.clear()
    cfg = {
        "id": "x",
        "initial": "a",
        "context": {},
        "actionErrorPolicy": "rollback",
        "states": {
            "a": {
                "exit": [{"type": "raise", "params": {"event": "PING"}}],
                "on": {
                    "GO": {"target": "b", "actions": ["boom"]},
                    "PING": {"actions": ["notePing"]},
                },
            },
            "b": {"on": {"PING": {"actions": ["notePing"]}}},
        },
    }
    m = create_machine(
        cfg, logic=MachineLogic(actions={"boom": boom, "notePing": _seen("PING")})
    )
    i = Interpreter(m)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.15)
    out = {"seen": list(SEEN), "state": sorted(i.current_state_ids)}
    await i.stop()
    return out


# --------------------------------------------------------------- B4
@_h.probe("B4", "two raises then a failing action: both withdrawn", {"seen": [], "state": ["y.a"]})
async def b4():
    SEEN.clear()
    cfg = {
        "id": "y",
        "initial": "a",
        "context": {},
        "actionErrorPolicy": "rollback",
        "states": {
            "a": {
                "on": {
                    "GO": {
                        "target": "b",
                        "actions": [
                            {"type": "raise", "params": {"event": "P1"}},
                            {"type": "raise", "params": {"event": "P2"}},
                            "boom",
                        ],
                    },
                    "P1": {"actions": ["n1"]},
                    "P2": {"actions": ["n2"]},
                }
            },
            "b": {"on": {"P1": {"actions": ["n1"]}, "P2": {"actions": ["n2"]}}},
        },
    }
    m = create_machine(
        cfg,
        logic=MachineLogic(
            actions={"boom": boom, "n1": _seen("P1"), "n2": _seen("P2")}
        ),
    )
    i = Interpreter(m)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.15)
    out = {"seen": list(SEEN), "state": sorted(i.current_state_ids)}
    await i.stop()
    return out


# --------------------------------------------------------------- B6
@_h.probe(
    "B6",
    "targetless self-transition: raise then fail -> withdrawn",
    {"seen": [], "n": 0},
)
async def b6():
    SEEN.clear()
    cfg = {
        "id": "z",
        "initial": "a",
        "context": {"n": 0},
        "actionErrorPolicy": "rollback",
        "states": {
            "a": {
                "on": {
                    "GO": {
                        "actions": [
                            "bump",
                            {"type": "raise", "params": {"event": "PING"}},
                            "boom",
                        ]
                    },
                    "PING": {"actions": ["notePing"]},
                }
            }
        },
    }

    def bump(i, c, e, a):
        c["n"] += 1

    m = create_machine(
        cfg,
        logic=MachineLogic(
            actions={"boom": boom, "bump": bump, "notePing": _seen("PING")}
        ),
    )
    i = Interpreter(m)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.15)
    out = {"seen": list(SEEN), "n": i.context["n"]}
    await i.stop()
    return out


# --------------------------------------------------------------- B7
@_h.probe(
    "B7",
    "500 rollbacks each withdrawing a raise: no false runaway trip",
    {"delivered": 500},
)
async def b7():
    cfg = {
        "id": "w",
        "initial": "a",
        "context": {"ok": 0},
        "actionErrorPolicy": "rollback",
        "states": {
            "a": {
                "on": {
                    "BAD": {
                        "actions": [{"type": "raise", "params": {"event": "PING"}}, "boom"]
                    },
                    "GOOD": {"actions": ["bump"]},
                    "PING": {},
                }
            }
        },
    }

    def bump(i, c, e, a):
        c["ok"] += 1

    m = create_machine(cfg, logic=MachineLogic(actions={"boom": boom, "bump": bump}))
    i = Interpreter(m)
    await i.start()
    for _ in range(500):
        await i.send("BAD")
        await i.send("GOOD")
    await asyncio.sleep(0.5)
    out = {"delivered": i.context["ok"]}
    await i.stop()
    return out


# --------------------------------------------------------------- B8
@_h.probe("B8", "'fail' policy withdraws the raise too", {"seen": [], "status": "stopped"})
async def b8():
    SEEN.clear()
    cfg = {
        "id": "f",
        "initial": "a",
        "context": {},
        "actionErrorPolicy": "fail",
        "states": {
            "a": {
                "on": {
                    "GO": {
                        "actions": [{"type": "raise", "params": {"event": "PING"}}, "boom"]
                    },
                    "PING": {"actions": ["notePing"]},
                }
            }
        },
    }
    m = create_machine(
        cfg, logic=MachineLogic(actions={"boom": boom, "notePing": _seen("PING")})
    )
    i = Interpreter(m)
    await i.start()
    try:
        await i.send("GO")
    except Exception:
        pass
    await asyncio.sleep(0.2)
    out = {"seen": list(SEEN), "status": i.status}
    try:
        await i.stop()
    except Exception:
        pass
    return out


if __name__ == "__main__":
    _h.main("b_rollback_raise")
