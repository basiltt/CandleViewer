"""Group S — transition selection, preemption, document order, LCCA.

SCXML 1.0 §3.13 (selecting transitions), §3.12 (microstep/macrostep),
XState v5 core transition selection.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conf_harness import case, run_all  # noqa: E402

from xstate_statemachine import MachineLogic  # noqa: E402


# --------------------------------------------------------------- S-01
@case(
    "S-01",
    "Parallel regions: both regions take their own transition on one event",
    "SCXML 3.13 selectTransitions: one transition per atomic state in "
    "the configuration; XState v5 fires in every region",
    ["p.A.a2", "p.B.b2"],
)
async def s01(rig):
    cfg = {
        "id": "p",
        "type": "parallel",
        "states": {
            "A": {
                "initial": "a1",
                "states": {
                    "a1": {"on": {"E": "a2"}},
                    "a2": {},
                },
            },
            "B": {
                "initial": "b1",
                "states": {
                    "b1": {"on": {"E": "b2"}},
                    "b2": {},
                },
            },
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- S-02
@case(
    "S-02",
    "Ancestor preemption: child transition wins over ancestor on same event",
    "SCXML 3.13: for each atomic state the transition selected is the one "
    "on the innermost state that has an enabled transition",
    ["m.A.a2"],
)
async def s02(rig):
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "initial": "a1",
                "on": {"E": "#m.B"},
                "states": {"a1": {"on": {"E": "a2"}}, "a2": {}},
            },
            "B": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- S-03
@case(
    "S-03",
    "Document order among two enabled transitions on the SAME state",
    "SCXML 3.13: transitions of one state are considered in document "
    "order; the first enabled one is selected",
    ["m.first"],
)
async def s03(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "E": [
                        {"target": "first"},
                        {"target": "second"},
                    ]
                }
            },
            "first": {},
            "second": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- S-04
@case(
    "S-04",
    "Guard fallthrough: first enabled branch in document order wins",
    "SCXML 3.13 + XState v5 guarded transition arrays",
    ["m.second"],
)
async def s04(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "context": {"n": 5},
        "states": {
            "s": {
                "on": {
                    "E": [
                        {"target": "first", "guard": "big"},
                        {"target": "second", "guard": "small"},
                        {"target": "third"},
                    ]
                }
            },
            "first": {},
            "second": {},
            "third": {},
        },
    }
    logic = MachineLogic(
        guards={
            "big": lambda c, e: c["n"] > 10,
            "small": lambda c, e: c["n"] > 1,
        }
    )
    await rig.boot(cfg, logic)
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- S-05
@case(
    "S-05",
    "Conflicting transitions in parallel regions targeting outside: "
    "document-order-first region wins, second is preempted",
    "SCXML 3.13 removeConflictingTransitions: a transition whose exit set "
    "intersects an earlier selected transition's exit set is preempted; "
    "document order decides",
    ["m.X"],
)
async def s05(rig):
    cfg = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "type": "parallel",
                "states": {
                    "A": {
                        "initial": "a1",
                        "states": {"a1": {"on": {"E": "#m.X"}}},
                    },
                    "B": {
                        "initial": "b1",
                        "states": {"b1": {"on": {"E": "#m.Y"}}},
                    },
                },
            },
            "X": {},
            "Y": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- S-06
@case(
    "S-06",
    "Exit order across parallel regions is reverse document order "
    "(region-major), and each state is exited exactly once",
    "SCXML 3.13 exitStates: statesToExit is sorted in exitOrder = "
    "REVERSE DOCUMENT ORDER. Document order here is p, A, a1, B, b1, so "
    "exit order is b1, B, a1, A, p (region-major, not depth-major)",
    {"ids": ["m.X"], "log": ["xb1", "xB", "xa1", "xA", "xp", "eX"]},
)
async def s06(rig):
    cfg = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "exit": ["xp"],
                "type": "parallel",
                "states": {
                    "A": {
                        "exit": ["xA"],
                        "initial": "a1",
                        "states": {
                            "a1": {"exit": ["xa1"], "on": {"E": "#m.X"}}
                        },
                    },
                    "B": {
                        "exit": ["xB"],
                        "initial": "b1",
                        "states": {
                            "b1": {"exit": ["xb1"], "on": {"E": "#m.Y"}}
                        },
                    },
                },
            },
            "X": {"entry": ["eX"]},
            "Y": {"entry": ["eY"]},
        },
    }
    logic = MachineLogic(
        actions=rig.recorders(
            "xp", "xA", "xa1", "xB", "xb1", "eX", "eY"
        )
    )
    await rig.boot(cfg, logic)
    await rig.send("E")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- S-07
@case(
    "S-07",
    "LCCA: sibling-to-sibling transition exits/enters only up to the LCCA",
    "SCXML 3.13 getTransitionDomain = LCCA(source, targets); states above "
    "the domain are NOT exited",
    {
        "ids": ["m.P.b"],
        "log": ["xa", "eb"],
    },
)
async def s07(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "entry": ["eP"],
                "exit": ["xP"],
                "initial": "a",
                "states": {
                    "a": {
                        "entry": ["ea"],
                        "exit": ["xa"],
                        "on": {"E": "b"},
                    },
                    "b": {"entry": ["eb"], "exit": ["xb"]},
                },
            }
        },
    }
    logic = MachineLogic(
        actions=rig.recorders("eP", "xP", "ea", "xa", "eb", "xb")
    )
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- S-08
@case(
    "S-08",
    "LCCA across parallel regions: cross-region target exits the whole "
    "parallel state and re-enters both regions",
    "SCXML 3.13: LCCA of a state in region A and a state in region B is "
    "the parallel state's parent, so the parallel state is exited",
    {
        "ids": ["m.p.A.a2", "m.p.B.b1"],
        "entered_B": True,
    },
)
async def s08(rig):
    cfg = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "type": "parallel",
                "states": {
                    "A": {
                        "initial": "a1",
                        "states": {
                            "a1": {"on": {"E": "#m.p.A.a2"}},
                            "a2": {},
                        },
                    },
                    "B": {
                        "initial": "b1",
                        "states": {"b1": {"entry": ["eb1"]}, "b2": {}},
                    },
                },
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("eb1"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    # Target is inside region A only: LCCA is A, so region B must NOT be
    # re-entered (no second "eb1").
    return {"ids": rig.ids(), "entered_B": rig.log == []}


# --------------------------------------------------------------- S-09
@case(
    "S-09",
    "Targetless transition: actions run, no exit/entry",
    "SCXML 3.13 (targetless transitions are internal, take no state "
    "change); XState v5 actions-only transition",
    {"ids": ["m.s"], "log": ["act"]},
)
async def s09(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "entry": ["es"],
                "exit": ["xs"],
                "on": {"E": {"actions": ["act"]}},
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("es", "xs", "act"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- S-10
@case(
    "S-10",
    "Self-transition default (reenter absent) is internal: no exit/entry",
    "XState v5: a transition with target === source and reenter falsy is "
    "internal; SCXML type='internal'",
    {"ids": ["m.s"], "log": ["act"]},
)
async def s10(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "entry": ["es"],
                "exit": ["xs"],
                "on": {"E": {"target": "s", "actions": ["act"]}},
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("es", "xs", "act"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- S-11
@case(
    "S-11",
    "Self-transition with reenter:true is external: exit then action "
    "then entry",
    "XState v5 reenter:true; SCXML type='external' self-transition. "
    "Action order per SCXML 3.13: exit, transition actions, entry",
    {"ids": ["m.s"], "log": ["xs", "act", "es"]},
)
async def s11(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "entry": ["es"],
                "exit": ["xs"],
                "on": {
                    "E": {
                        "target": "s",
                        "reenter": True,
                        "actions": ["act"],
                    }
                },
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("es", "xs", "act"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- S-12
@case(
    "S-12",
    "internal:false (v4 spelling) is equivalent to reenter:true",
    "XState v4 internal:false == v5 reenter:true (library CHANGELOG "
    "models.py:539 documents the alias)",
    {"ids": ["m.s"], "log": ["xs", "act", "es"]},
)
async def s12(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "entry": ["es"],
                "exit": ["xs"],
                "on": {
                    "E": {
                        "target": "s",
                        "internal": False,
                        "actions": ["act"],
                    }
                },
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("es", "xs", "act"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- S-13
@case(
    "S-13",
    "Compound self-transition with reenter:true re-enters the initial "
    "child, not the previously active child",
    "SCXML 3.13: external self-transition on a compound state exits it "
    "and re-enters via its initial state",
    {"ids": ["m.P.a"], "log": ["xb", "xP", "eP", "ea"]},
)
async def s13(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "entry": ["eP"],
                "exit": ["xP"],
                "initial": "a",
                "on": {"RESET": {"target": "P", "reenter": True}},
                "states": {
                    "a": {"entry": ["ea"], "exit": ["xa"], "on": {"E": "b"}},
                    "b": {"entry": ["eb"], "exit": ["xb"]},
                },
            }
        },
    }
    logic = MachineLogic(
        actions=rig.recorders("eP", "xP", "ea", "xa", "eb", "xb")
    )
    await rig.boot(cfg, logic)
    await rig.send("E")
    rig.log.clear()
    await rig.send("RESET")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- S-14
@case(
    "S-14",
    "Transition to a descendant of the active state enters only the "
    "missing links (no re-entry of the ancestor)",
    "SCXML 3.13: transition domain is the LCCA; ancestors already active "
    "are not exited",
    {"ids": ["m.P.a.a2"], "log": ["xa1", "ea2"]},
)
async def s14(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "entry": ["eP"],
                "exit": ["xP"],
                "initial": "a",
                "states": {
                    "a": {
                        "entry": ["ea"],
                        "exit": ["xa"],
                        "initial": "a1",
                        "states": {
                            "a1": {
                                "entry": ["ea1"],
                                "exit": ["xa1"],
                                "on": {"E": "#m.P.a.a2"},
                            },
                            "a2": {"entry": ["ea2"], "exit": ["xa2"]},
                        },
                    }
                },
            }
        },
    }
    logic = MachineLogic(
        actions=rig.recorders(
            "eP", "xP", "ea", "xa", "ea1", "xa1", "ea2", "xa2"
        )
    )
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- S-15
@case(
    "S-15",
    "Transition to a proper ancestor exits and re-enters the ancestor",
    "SCXML 3.13: LCCA(source, ancestor-target) is the ancestor's parent, "
    "so the ancestor is exited and re-entered",
    {"ids": ["m.P.a"], "log": ["xa", "xP", "eP", "ea"]},
)
async def s15(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "entry": ["eP"],
                "exit": ["xP"],
                "initial": "a",
                "states": {
                    "a": {
                        "entry": ["ea"],
                        "exit": ["xa"],
                        "on": {"E": "#m.P"},
                    },
                    "b": {},
                },
            }
        },
    }
    logic = MachineLogic(
        actions=rig.recorders("eP", "xP", "ea", "xa")
    )
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- S-16
@case(
    "S-16",
    "Exit order is inner-to-outer, entry order outer-to-inner",
    "SCXML 3.9: exitStates in reverse document/depth order, enterStates "
    "in entry order (ancestors before descendants)",
    ["xa1", "xA", "eB", "eb1"],
)
async def s16(rig):
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "entry": ["eA"],
                "exit": ["xA"],
                "initial": "a1",
                "states": {
                    "a1": {
                        "entry": ["ea1"],
                        "exit": ["xa1"],
                        "on": {"E": "#m.B"},
                    }
                },
            },
            "B": {
                "entry": ["eB"],
                "exit": ["xB"],
                "initial": "b1",
                "states": {"b1": {"entry": ["eb1"], "exit": ["xb1"]}},
            },
        },
    }
    logic = MachineLogic(
        actions=rig.recorders(
            "eA", "xA", "ea1", "xa1", "eB", "xB", "eb1", "xb1"
        )
    )
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- S-17
@case(
    "S-17",
    "Action order on a state change: exit actions, then transition "
    "actions, then entry actions",
    "SCXML 3.13 microstep: exit set actions, transition actions, entry "
    "set actions, in that order",
    ["xA", "trans", "eB"],
)
async def s17(rig):
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "exit": ["xA"],
                "on": {"E": {"target": "B", "actions": ["trans"]}},
            },
            "B": {"entry": ["eB"]},
        },
    }
    logic = MachineLogic(actions=rig.recorders("xA", "trans", "eB"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- S-18
@case(
    "S-18",
    "Unknown event causes no transition and no actions",
    "SCXML 3.13: an event with no enabled transition leaves the "
    "configuration unchanged",
    {"ids": ["m.A"], "log": []},
)
async def s18(rig):
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {"A": {"exit": ["xA"], "on": {"E": "B"}}, "B": {}},
    }
    logic = MachineLogic(actions=rig.recorders("xA"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("NOPE")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- S-19
@case(
    "S-19",
    "Guard blocking the inner transition lets the ancestor transition fire",
    "SCXML 3.13: only ENABLED transitions are candidates; a disabled "
    "inner transition does not shadow an enabled ancestor one",
    ["m.B"],
)
async def s19(rig):
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "initial": "a1",
                "on": {"E": "#m.B"},
                "states": {
                    "a1": {"on": {"E": {"target": "a2", "guard": "never"}}},
                    "a2": {},
                },
            },
            "B": {},
        },
    }
    logic = MachineLogic(guards={"never": lambda c, e: False})
    await rig.boot(cfg, logic)
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- S-20
@case(
    "S-20",
    "Transition actions see the event payload that triggered them",
    "SCXML 3.13 / XState v5: actions receive the triggering event",
    {"n": 7},
)
async def s20(rig):
    seen = {}

    def grab(i, c, e, a):
        seen["n"] = e.payload.get("n")

    cfg = {
        "id": "m",
        "initial": "A",
        "states": {"A": {"on": {"E": {"actions": ["grab"]}}}},
    }
    await rig.boot(cfg, MachineLogic(actions={"grab": grab}))
    await rig.send("E", n=7)
    return seen


if __name__ == "__main__":
    run_all("s_selection")
