"""Group O — action ordering: assign ordering among actions, targetless
action ordering relative to exit/entry, entry/exit around eventless steps,
and context visibility between actions.

SCXML 1.0 §3.13 (order of executable content in a microstep), §4
(<assign>), XState v5 action ordering.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conf_harness import case, run_all  # noqa: E402

from xstate_statemachine import MachineLogic  # noqa: E402


# --------------------------------------------------------------- O-01
@case(
    "O-01",
    "Actions on one transition run in declaration order",
    "SCXML 3.13: executable content runs in document order",
    ["a1", "a2", "a3"],
)
async def o01(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"E": {"actions": ["a1", "a2", "a3"]}}}
        },
    }
    await rig.boot(cfg, MachineLogic(actions=rig.recorders("a1", "a2", "a3")))
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- O-02
@case(
    "O-02",
    "assign is applied in order among plain actions, and a later action "
    "observes the earlier assignment",
    "SCXML 4.3 <assign> mutates the datamodel immediately; subsequent "
    "executable content sees the new value",
    {"log": ["set1", "read=1", "set2", "read=2"], "n": 2},
)
async def o02(rig):
    def set_to(v):
        def fn(i, c, e, a):
            c["n"] = v
            rig.log.append(f"set{v}")

        return fn

    def read(i, c, e, a):
        rig.log.append(f"read={c['n']}")

    cfg = {
        "id": "m",
        "initial": "s",
        "context": {"n": 0},
        "states": {
            "s": {
                "on": {
                    "E": {"actions": ["set1", "read", "set2", "read2"]}
                }
            }
        },
    }
    logic = MachineLogic(
        actions={
            "set1": set_to(1),
            "set2": set_to(2),
            "read": read,
            "read2": read,
        }
    )
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {"log": rig.log, "n": rig.ctx()["n"]}


# --------------------------------------------------------------- O-03
@case(
    "O-03",
    "An entry action observes a context change made by the transition's "
    "own actions",
    "SCXML 3.13: exit, transition content, entry run in sequence against "
    "one datamodel",
    ["trans_set", "entry_read=5"],
)
async def o03(rig):
    def tset(i, c, e, a):
        c["n"] = 5
        rig.log.append("trans_set")

    def eread(i, c, e, a):
        rig.log.append(f"entry_read={c['n']}")

    cfg = {
        "id": "m",
        "initial": "A",
        "context": {"n": 0},
        "states": {
            "A": {"on": {"E": {"target": "B", "actions": ["tset"]}}},
            "B": {"entry": ["eread"]},
        },
    }
    logic = MachineLogic(actions={"tset": tset, "eread": eread})
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- O-04
@case(
    "O-04",
    "An exit action runs BEFORE the transition actions and its context "
    "change is visible to them",
    "SCXML 3.13: the exit set's onexit content precedes the transition's",
    ["exit_set", "trans_read=9"],
)
async def o04(rig):
    def xset(i, c, e, a):
        c["n"] = 9
        rig.log.append("exit_set")

    def tread(i, c, e, a):
        rig.log.append(f"trans_read={c['n']}")

    cfg = {
        "id": "m",
        "initial": "A",
        "context": {"n": 0},
        "states": {
            "A": {"exit": ["xset"], "on": {"E": {"target": "B",
                                                 "actions": ["tread"]}}},
            "B": {},
        },
    }
    logic = MachineLogic(actions={"xset": xset, "tread": tread})
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- O-05
@case(
    "O-05",
    "A targetless transition's actions run with NO exit and NO entry, "
    "even when the state declares both",
    "SCXML 3.13: a targetless transition performs no state change, so "
    "the exit/entry sets are empty",
    ["only_trans"],
)
async def o05(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "entry": ["es"],
                "exit": ["xs"],
                "on": {"E": {"actions": ["only_trans"]}},
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("es", "xs", "only_trans"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- O-06
@case(
    "O-06",
    "A targetless transition on an ANCESTOR does not exit the active "
    "descendant",
    "SCXML 3.13: targetless transitions are internal regardless of the "
    "source state's depth",
    {"ids": ["m.P.a"], "log": ["anc"]},
)
async def o06(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "initial": "a",
                "on": {"E": {"actions": ["anc"]}},
                "states": {"a": {"exit": ["xa"], "entry": ["ea"]}},
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("anc", "xa", "ea"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {"ids": rig.ids(), "log": rig.log}


# --------------------------------------------------------------- O-07
@case(
    "O-07",
    "Entry actions of nested states run outermost-first in a single "
    "entry pass",
    "SCXML 3.9 enterStates: ancestors are entered before descendants",
    ["eP", "ea", "ea1"],
)
async def o07(rig):
    cfg = {
        "id": "m",
        "initial": "Start",
        "states": {
            "Start": {"on": {"E": "#m.P"}},
            "P": {
                "entry": ["eP"],
                "initial": "a",
                "states": {
                    "a": {
                        "entry": ["ea"],
                        "initial": "a1",
                        "states": {"a1": {"entry": ["ea1"]}},
                    }
                },
            },
        },
    }
    logic = MachineLogic(actions=rig.recorders("eP", "ea", "ea1"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- O-08
@case(
    "O-08",
    "Across an eventless hop the ordering is: exit A, trans, entry B, "
    "exit B, always-trans, entry C",
    "SCXML 3.13: each microstep runs its own complete exit/content/entry "
    "sequence; microsteps do not interleave",
    ["xA", "t1", "eB", "xB", "t2", "eC"],
)
async def o08(rig):
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "exit": ["xA"],
                "on": {"E": {"target": "B", "actions": ["t1"]}},
            },
            "B": {
                "entry": ["eB"],
                "exit": ["xB"],
                "always": {"target": "C", "actions": ["t2"]},
            },
            "C": {"entry": ["eC"]},
        },
    }
    logic = MachineLogic(
        actions=rig.recorders("xA", "t1", "eB", "xB", "t2", "eC")
    )
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- O-09
@case(
    "O-09",
    "In a parallel fan-out both regions' transition actions run, "
    "deepest-source-first and each exactly once",
    "SCXML 3.13: every selected transition's content runs once per "
    "microstep",
    {"count_a": 1, "count_b": 1},
)
async def o09(rig):
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
                            "a1": {
                                "on": {
                                    "E": {"target": "a2", "actions": ["ta"]}
                                }
                            },
                            "a2": {},
                        },
                    },
                    "B": {
                        "initial": "b1",
                        "states": {
                            "b1": {
                                "on": {
                                    "E": {"target": "b2", "actions": ["tb"]}
                                }
                            },
                            "b2": {},
                        },
                    },
                },
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("ta", "tb"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {
        "count_a": rig.log.count("ta"),
        "count_b": rig.log.count("tb"),
    }


# --------------------------------------------------------------- O-10
@case(
    "O-10",
    "A transition declared on a shared ANCESTOR of two parallel regions "
    "fires exactly once, not once per region",
    "SCXML 3.13 removeConflictingTransitions: the same transition "
    "selected by several atomic states is executed once",
    {"count": 1},
)
async def o10(rig):
    cfg = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "type": "parallel",
                "on": {"E": {"actions": ["shared"]}},
                "states": {
                    "A": {"initial": "a1", "states": {"a1": {}}},
                    "B": {"initial": "b1", "states": {"b1": {}}},
                },
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("shared"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return {"count": rig.log.count("shared")}


# --------------------------------------------------------------- O-11
@case(
    "O-11",
    "A guard on a shared ancestor transition is evaluated but its "
    "SIDE EFFECTS are not multiplied by the region count",
    "SCXML 5.9: guards are pure predicates. Library memoises per "
    "selection pass (base_interpreter.py:3671) so a shared ancestor's "
    "guard runs once.",
    {"evals": 1},
)
async def o11(rig):
    calls = []

    def g(c, e):
        calls.append(1)
        return True

    cfg = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "type": "parallel",
                "on": {"E": {"guard": "g", "actions": []}},
                "states": {
                    "A": {"initial": "a1", "states": {"a1": {}}},
                    "B": {"initial": "b1", "states": {"b1": {}}},
                    "C": {"initial": "c1", "states": {"c1": {}}},
                },
            }
        },
    }
    await rig.boot(cfg, MachineLogic(guards={"g": g}))
    calls.clear()
    await rig.send("E")
    return {"evals": len(calls)}


# --------------------------------------------------------------- O-12
@case(
    "O-12",
    "`raise` queues an INTERNAL event processed after the current "
    "microstep completes, not inline",
    "SCXML 3.13 / 4.5 <raise>: the event goes on the internal queue and "
    "is taken in the NEXT microstep, after the current one finishes",
    ["t_before", "eB", "on_raised"],
)
async def o12(rig):
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "on": {
                    "E": {
                        "target": "B",
                        "actions": [
                            "t_before",
                            {
                                "type": "raise",
                                "params": {"event": {"type": "R"}},
                            },
                        ],
                    }
                }
            },
            "B": {
                "entry": ["eB"],
                "on": {"R": {"actions": ["on_raised"]}},
            },
        },
    }
    logic = MachineLogic(
        actions=rig.recorders("t_before", "eB", "on_raised")
    )
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- O-13
@case(
    "O-13",
    "Two `raise`d events are processed in the order they were raised",
    "SCXML 3.13: the internal queue is FIFO",
    ["r1", "r2"],
)
async def o13(rig):
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "on": {
                    "E": {
                        "actions": [
                            {
                                "type": "raise",
                                "params": {"event": {"type": "R1"}},
                            },
                            {
                                "type": "raise",
                                "params": {"event": {"type": "R2"}},
                            },
                        ]
                    },
                    "R1": {"actions": ["r1"]},
                    "R2": {"actions": ["r2"]},
                }
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("r1", "r2"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- O-14
@case(
    "O-14",
    "Internal (`raise`d) events are processed BEFORE an already-queued "
    "external event",
    "SCXML 3.13: the internal queue is drained to exhaustion before the "
    "next external event is taken",
    ["internal", "external"],
)
async def o14(rig):
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "on": {
                    "E": {
                        "actions": [
                            {
                                "type": "raise",
                                "params": {"event": {"type": "R"}},
                            }
                        ]
                    },
                    "R": {"actions": ["internal"]},
                    "X": {"actions": ["external"]},
                }
            }
        },
    }
    logic = MachineLogic(actions=rig.recorders("internal", "external"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    if rig.engine == "async":
        # Queue both without awaiting in between so E and X are both
        # pending; R is raised while E is being processed.
        await rig.interp.send("E")
        await rig.interp.send("X")
        await rig.settle(0.2)
    else:
        rig.interp.send_events(["E", "X"])
    return rig.log


# --------------------------------------------------------------- O-15
@case(
    "O-15",
    "Entry actions of a state run before its `always` transition is "
    "evaluated",
    "SCXML 3.13: the microstep completes (entry content included) "
    "before eventless transitions are re-selected",
    ["eB", "t"],
)
async def o15(rig):
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {"on": {"E": "B"}},
            "B": {"entry": ["eB"], "always": {"target": "C",
                                              "actions": ["t"]}},
            "C": {},
        },
    }
    logic = MachineLogic(actions=rig.recorders("eB", "t"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- O-16
@case(
    "O-16",
    "Machine `entry` on the root and the initial state's entry run "
    "outermost-first at start()",
    "SCXML 3.2/3.9: the initial configuration is entered as an ordinary "
    "entry pass from the root down",
    ["root", "first"],
)
async def o16(rig):
    cfg = {
        "id": "m",
        "entry": ["root"],
        "initial": "A",
        "states": {"A": {"entry": ["first"]}},
    }
    await rig.boot(cfg, MachineLogic(actions=rig.recorders("root", "first")))
    return rig.log


if __name__ == "__main__":
    run_all("o_ordering")
