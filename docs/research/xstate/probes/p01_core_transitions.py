"""Probe suite A: entry/exit ordering, self-transitions, guard fallthrough,
eventless (always) transitions, wildcards, unknown events.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import probe, run_all  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)

SETTLE = 0.08


def recorder(log: List[str]):
    def make(name: str):
        def fn(interp, ctx, evt, adef):  # noqa: ANN001
            log.append(name)

        return fn

    return make


def acts(log: List[str], names: List[str]) -> Dict[str, Any]:
    mk = recorder(log)
    return {n: mk(n) for n in names}


async def boot(cfg, logic):
    return await Interpreter(create_machine(cfg, logic=logic)).start()


# ---------------------------------------------------------------- A1
@probe(
    "A1",
    "Exit/entry order across nested compound -> parallel target",
    ["xA1", "xA", "eB", "eP", "ep1", "eQ", "eq1"],
)
async def a1():
    log: List[str] = []
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "entry": ["eA"],
                "exit": ["xA"],
                "initial": "A1",
                "states": {
                    "A1": {
                        "entry": ["eA1"],
                        "exit": ["xA1"],
                        "on": {"GO": {"target": "#m.B"}},
                    }
                },
            },
            "B": {
                "entry": ["eB"],
                "type": "parallel",
                "states": {
                    "P": {
                        "entry": ["eP"],
                        "initial": "p1",
                        "states": {"p1": {"entry": ["ep1"]}},
                    },
                    "Q": {
                        "entry": ["eQ"],
                        "initial": "q1",
                        "states": {"q1": {"entry": ["eq1"]}},
                    },
                },
            },
        },
    }
    logic = MachineLogic(
        actions=acts(
            log, ["eA", "xA", "eA1", "xA1", "eB", "eP", "ep1", "eQ", "eq1"]
        )
    )
    i = await boot(cfg, logic)
    log.clear()
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    await i.stop()
    return log


# ---------------------------------------------------------------- A2
@probe(
    "A2",
    "Transition action ordering: exit -> transition action -> entry",
    ["xA", "tAct", "eB"],
)
async def a2():
    log: List[str] = []
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "entry": ["eA"],
                "exit": ["xA"],
                "on": {"GO": {"target": "B", "actions": ["tAct"]}},
            },
            "B": {"entry": ["eB"]},
        },
    }
    logic = MachineLogic(actions=acts(log, ["eA", "xA", "tAct", "eB"]))
    i = await boot(cfg, logic)
    log.clear()
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    await i.stop()
    return log


# ---------------------------------------------------------------- A3
@probe(
    "A3",
    "Self-transition with an explicit target but no `reenter` is treated as "
    "INTERNAL (XState v5 would re-enter: exit+action+entry)",
    ["xA", "tAct", "eA"],
)
async def a3():
    log: List[str] = []
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "entry": ["eA"],
                "exit": ["xA"],
                "on": {"GO": {"target": "A", "actions": ["tAct"]}},
            }
        },
    }
    logic = MachineLogic(actions=acts(log, ["eA", "xA", "tAct"]))
    i = await boot(cfg, logic)
    log.clear()
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    await i.stop()
    return log


# ---------------------------------------------------------------- A4
@probe(
    "A4",
    "Internal self-transition (no target) does NOT re-run entry/exit",
    ["tAct"],
)
async def a4():
    log: List[str] = []
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "entry": ["eA"],
                "exit": ["xA"],
                "on": {"GO": {"actions": ["tAct"]}},
            }
        },
    }
    logic = MachineLogic(actions=acts(log, ["eA", "xA", "tAct"]))
    i = await boot(cfg, logic)
    log.clear()
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    await i.stop()
    return log


# ---------------------------------------------------------------- A5
@probe(
    "A5",
    "Relative '.child' target syntax resolves and re-enters the child",
    ["xA1", "eA1"],
)
async def a5():
    log: List[str] = []
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "entry": ["eA"],
                "exit": ["xA"],
                "initial": "A1",
                "on": {"GO": {"target": ".A1", "internal": True}},
                "states": {"A1": {"entry": ["eA1"], "exit": ["xA1"]}},
            }
        },
    }
    logic = MachineLogic(actions=acts(log, ["eA", "xA", "eA1", "xA1"]))
    i = await boot(cfg, logic)
    log.clear()
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    await i.stop()
    return log


# ---------------------------------------------------------------- A6
@probe(
    "A6",
    "Guarded fallthrough: correct branch chosen, but are later guards still "
    "evaluated (side-effect leakage)?",
    {"state": ["m.second"], "calls": ["g1", "g2"]},
)
async def a6():
    calls: List[str] = []

    def g1(c, e):  # noqa: ANN001
        calls.append("g1")
        return False

    def g2(c, e):  # noqa: ANN001
        calls.append("g2")
        return True

    def g3(c, e):  # noqa: ANN001
        calls.append("g3")
        return True

    cfg = {
        "id": "m",
        "initial": "start",
        "states": {
            "start": {
                "on": {
                    "GO": [
                        {"target": "first", "guard": "g1"},
                        {"target": "second", "guard": "g2"},
                        {"target": "third", "guard": "g3"},
                    ]
                }
            },
            "first": {},
            "second": {},
            "third": {},
        },
    }
    logic = MachineLogic(guards={"g1": g1, "g2": g2, "g3": g3})
    i = await boot(cfg, logic)
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return {"state": st, "calls": calls}


# ---------------------------------------------------------------- A7
@probe(
    "A7",
    "All guards false -> no transition, state unchanged, no error",
    {"state": ["m.start"], "running": True},
)
async def a7():
    cfg = {
        "id": "m",
        "initial": "start",
        "states": {
            "start": {
                "on": {
                    "GO": [
                        {"target": "a", "guard": "no"},
                        {"target": "b", "guard": "no"},
                    ]
                }
            },
            "a": {},
            "b": {},
        },
    }
    logic = MachineLogic(guards={"no": lambda c, e: False})
    i = await boot(cfg, logic)
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    out = {"state": sorted(i.current_state_ids), "running": i.is_running}
    await i.stop()
    return out


# ---------------------------------------------------------------- A8
@probe(
    "A8",
    "Eventless 'always' chain with guards settles to terminal state",
    ["m.done"],
)
async def a8():
    cfg = {
        "id": "m",
        "initial": "s0",
        "context": {"n": 0},
        "states": {
            "s0": {"on": {"GO": "s1"}},
            "s1": {"always": {"target": "s2", "guard": "yes"}},
            "s2": {"always": [{"target": "done", "guard": "yes"}]},
            "done": {},
        },
    }
    logic = MachineLogic(guards={"yes": lambda c, e: True})
    i = await boot(cfg, logic)
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


# ---------------------------------------------------------------- A9
@probe(
    "A9",
    "Infinite 'always' loop (A<->B unguarded): bounded, interpreter survives",
    {"terminated": True, "alive_after": True},
)
async def a9():
    cfg = {
        "id": "m",
        "initial": "idle",
        "states": {
            "idle": {"on": {"GO": "A"}},
            "A": {"always": {"target": "B"}},
            "B": {"always": {"target": "A"}},
        },
    }
    i = await boot(cfg, MachineLogic())
    terminated = True
    try:
        await asyncio.wait_for(i.send("GO"), timeout=5.0)
        await asyncio.sleep(0.3)
    except asyncio.TimeoutError:
        terminated = False
    alive = i.is_running
    try:
        await i.stop()
    except Exception:  # noqa: BLE001
        pass
    return {"terminated": terminated, "alive_after": alive}


# ---------------------------------------------------------------- A10
@probe(
    "A10",
    "'always' whose fallback targets its OWN state: should loop until the "
    "guard flips",
    {"state": ["m.done"], "n": 5},
)
async def a10():
    def inc(i, c, e, a):  # noqa: ANN001
        c["n"] += 1

    cfg = {
        "id": "m",
        "initial": "idle",
        "context": {"n": 0},
        "states": {
            "idle": {"on": {"GO": "loop"}},
            "loop": {
                "entry": ["inc"],
                "always": [
                    {"target": "done", "guard": "enough"},
                    {"target": "loop"},
                ],
            },
            "done": {},
        },
    }
    logic = MachineLogic(
        actions={"inc": inc}, guards={"enough": lambda c, e: c["n"] >= 5}
    )
    i = await boot(cfg, logic)
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    out = {"state": sorted(i.current_state_ids), "n": i.context["n"]}
    await i.stop()
    return out


# ---------------------------------------------------------------- A11
@probe("A11", "Wildcard '*' event handler catches unmatched events", ["m.caught"])
async def a11():
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"KNOWN": "known", "*": "caught"}},
            "known": {},
            "caught": {},
        },
    }
    i = await boot(cfg, MachineLogic())
    await i.send("SOMETHING_ELSE")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


# ---------------------------------------------------------------- A12
@probe(
    "A12",
    "Explicit handler beats wildcard for a matching event",
    ["m.known"],
)
async def a12():
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"*": "caught", "KNOWN": "known"}},
            "known": {},
            "caught": {},
        },
    }
    i = await boot(cfg, MachineLogic())
    await i.send("KNOWN")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


# ---------------------------------------------------------------- A13
@probe(
    "A13",
    "Partial wildcard 'order.*' prefix matching",
    ["m.matched"],
)
async def a13():
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"order.*": "matched"}},
            "matched": {},
        },
    }
    i = await boot(cfg, MachineLogic())
    await i.send("order.filled")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


# ---------------------------------------------------------------- A14
@probe(
    "A14",
    "Unknown event with no handler is silently ignored (no raise, still running)",
    {"state": ["m.s"], "running": True, "raised": None},
)
async def a14():
    cfg = {"id": "m", "initial": "s", "states": {"s": {"on": {"X": "t"}}, "t": {}}}
    i = await boot(cfg, MachineLogic())
    raised = None
    try:
        await i.send("TOTALLY_UNKNOWN")
        await asyncio.sleep(SETTLE)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    out = {
        "state": sorted(i.current_state_ids),
        "running": i.is_running,
        "raised": raised,
    }
    await i.stop()
    return out


# ---------------------------------------------------------------- A15
@probe(
    "A15",
    "Parallel region: event handled independently in each region",
    ["m.P.A.a2", "m.P.B.b2"],
)
async def a15():
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "type": "parallel",
                "states": {
                    "A": {
                        "initial": "a1",
                        "states": {"a1": {"on": {"E": "a2"}}, "a2": {}},
                    },
                    "B": {
                        "initial": "b1",
                        "states": {"b1": {"on": {"E": "b2"}}, "b2": {}},
                    },
                },
            }
        },
    }
    i = await boot(cfg, MachineLogic())
    await i.send("E")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


# ---------------------------------------------------------------- A16
@probe(
    "A16",
    "Child transition takes precedence over conflicting ancestor handler",
    ["m.A.child_target"],
)
async def a16():
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "initial": "A1",
                "on": {"E": "B"},
                "states": {
                    "A1": {"on": {"E": "child_target"}},
                    "child_target": {},
                },
            },
            "B": {},
        },
    }
    i = await boot(cfg, MachineLogic())
    await i.send("E")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


# ---------------------------------------------------------------- A17
@probe(
    "A17",
    "Self-transition WITH reenter:True does re-run exit+entry (the workaround)",
    ["xA", "tAct", "eA"],
)
async def a17():
    log: List[str] = []
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "entry": ["eA"],
                "exit": ["xA"],
                "on": {
                    "GO": {
                        "target": "A",
                        "actions": ["tAct"],
                        "reenter": True,
                    }
                },
            }
        },
    }
    logic = MachineLogic(actions=acts(log, ["eA", "xA", "tAct"]))
    i = await boot(cfg, logic)
    log.clear()
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    await i.stop()
    return log


# ---------------------------------------------------------------- A18
@probe(
    "A18",
    "A '.child' relative target that does NOT exist is silently ignored "
    "(no error, no transition)",
    {"state": ["m.A.A1"], "running": True, "raised": None},
)
async def a18():
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "initial": "A1",
                "on": {"GO": {"target": ".does_not_exist"}},
                "states": {"A1": {}, "A2": {}},
            }
        },
    }
    i = await boot(cfg, MachineLogic())
    raised = None
    try:
        await i.send("GO")
        await asyncio.sleep(SETTLE)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    out = {
        "state": sorted(i.current_state_ids),
        "running": i.is_running,
        "raised": raised,
    }
    await i.stop()
    return out


# ---------------------------------------------------------------- A19
@probe(
    "A19",
    "'always' ping-pong between two DISTINCT states with a flipping guard "
    "does converge (contrast with A10)",
    {"state": ["m.done"], "n": 5},
)
async def a19():
    def inc(i, c, e, a):  # noqa: ANN001
        c["n"] += 1

    cfg = {
        "id": "m",
        "initial": "idle",
        "context": {"n": 0},
        "states": {
            "idle": {"on": {"GO": "A"}},
            "A": {
                "entry": ["inc"],
                "always": [
                    {"target": "done", "guard": "enough"},
                    {"target": "B"},
                ],
            },
            "B": {"always": {"target": "A"}},
            "done": {},
        },
    }
    logic = MachineLogic(
        actions={"inc": inc}, guards={"enough": lambda c, e: c["n"] >= 5}
    )
    i = await boot(cfg, logic)
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    out = {"state": sorted(i.current_state_ids), "n": i.context["n"]}
    await i.stop()
    return out


# ---------------------------------------------------------------- A20
@probe(
    "A20",
    "A guard that RAISES is swallowed and treated as False (silent)",
    {"state": ["m.fallback"], "raised": None},
)
async def a20():
    def boom(c, e):  # noqa: ANN001
        raise ValueError("guard exploded")

    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "GO": [
                        {"target": "primary", "guard": "boom"},
                        {"target": "fallback"},
                    ]
                }
            },
            "primary": {},
            "fallback": {},
        },
    }
    logic = MachineLogic(guards={"boom": boom})
    i = await boot(cfg, logic)
    raised = None
    try:
        await i.send("GO")
        await asyncio.sleep(SETTLE)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    out = {"state": sorted(i.current_state_ids), "raised": raised}
    await i.stop()
    return out


if __name__ == "__main__":
    run_all("01_core_transitions")
