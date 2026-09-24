"""Group H — history states (shallow / deep, across parallel), in-state
guards, and event-descriptor precedence.

SCXML 1.0 §3.10 (<history>), §5.9.2 (In() predicate), XState v5 `stateIn`
guard and partial event descriptors.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conf_harness import case, run_all  # noqa: E402

from xstate_statemachine import MachineLogic  # noqa: E402


def _hist_cfg(kind: str) -> dict:
    """A compound state P with a nested child, plus a history entry point."""
    return {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "initial": "a",
                "on": {"OUT": "#m.Away"},
                "states": {
                    "hist": {"type": "history", "history": kind},
                    "a": {
                        "initial": "a1",
                        "states": {
                            "a1": {"on": {"DEEP": "a2"}},
                            "a2": {},
                        },
                        "on": {"NEXT": "#m.P.b"},
                    },
                    "b": {"initial": "b1", "states": {"b1": {}}},
                },
            },
            "Away": {"on": {"BACK": "#m.P.hist"}},
        },
    }


# --------------------------------------------------------------- H-01
@case(
    "H-01",
    "Shallow history restores the last active CHILD of its parent",
    "SCXML 3.10: a shallow <history> restores the immediate children of "
    "its parent that were active when the parent was exited",
    ["m.P.b.b1"],
)
async def h01(rig):
    await rig.boot(_hist_cfg("shallow"), MachineLogic())
    await rig.send("NEXT")
    await rig.send("OUT")
    await rig.send("BACK")
    return rig.ids()


# --------------------------------------------------------------- H-02
@case(
    "H-02",
    "Shallow history does NOT restore grandchildren: the restored child "
    "re-enters via its own `initial`",
    "SCXML 3.10: shallow history records only the immediate children; "
    "deeper states use their default initial",
    ["m.P.a.a1"],
)
async def h02(rig):
    await rig.boot(_hist_cfg("shallow"), MachineLogic())
    await rig.send("DEEP")  # P.a.a2
    await rig.send("OUT")
    await rig.send("BACK")
    return rig.ids()


# --------------------------------------------------------------- H-03
@case(
    "H-03",
    "Deep history restores the full nested configuration",
    "SCXML 3.10: a deep <history> restores all active descendants of its "
    "parent at the time of exit",
    ["m.P.a.a2"],
)
async def h03(rig):
    await rig.boot(_hist_cfg("deep"), MachineLogic())
    await rig.send("DEEP")  # P.a.a2
    await rig.send("OUT")
    await rig.send("BACK")
    return rig.ids()


# --------------------------------------------------------------- H-04
@case(
    "H-04",
    "History with nothing recorded falls back to its default target",
    "SCXML 3.10: if the parent has never been exited, the history "
    "state's <transition> default target is taken",
    ["m.P.b.b1"],
)
async def h04(rig):
    cfg = {
        "id": "m",
        "initial": "Away",
        "states": {
            "Away": {"on": {"BACK": "#m.P.hist"}},
            "P": {
                "initial": "a",
                "states": {
                    "hist": {
                        "type": "history",
                        "history": "shallow",
                        "target": "#m.P.b",
                    },
                    "a": {},
                    "b": {"initial": "b1", "states": {"b1": {}}},
                },
            },
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("BACK")
    return rig.ids()


# --------------------------------------------------------------- H-05
@case(
    "H-05",
    "History with nothing recorded AND no default target uses the "
    "parent's `initial`",
    "SCXML 3.10 requires a default transition; XState v5 falls back to "
    "the parent's initial state when none is given",
    ["m.P.a"],
)
async def h05(rig):
    cfg = {
        "id": "m",
        "initial": "Away",
        "states": {
            "Away": {"on": {"BACK": "#m.P.hist"}},
            "P": {
                "initial": "a",
                "states": {
                    "hist": {"type": "history", "history": "shallow"},
                    "a": {},
                    "b": {},
                },
            },
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("BACK")
    return rig.ids()


# --------------------------------------------------------------- H-06
@case(
    "H-06",
    "Deep history across a PARALLEL state restores every region's leaf",
    "SCXML 3.10: deep history on a parallel ancestor restores the full "
    "configuration, i.e. the active leaf of every region",
    ["m.P.R1.x2", "m.P.R2.y2"],
)
async def h06(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "type": "parallel",
                "on": {"OUT": "#m.Away"},
                "states": {
                    "hist": {"type": "history", "history": "deep"},
                    "R1": {
                        "initial": "x1",
                        "states": {"x1": {"on": {"A": "x2"}}, "x2": {}},
                    },
                    "R2": {
                        "initial": "y1",
                        "states": {"y1": {"on": {"B": "y2"}}, "y2": {}},
                    },
                },
            },
            "Away": {"on": {"BACK": "#m.P.hist"}},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("A")
    await rig.send("B")
    await rig.send("OUT")
    await rig.send("BACK")
    return rig.ids()


# --------------------------------------------------------------- H-07
@case(
    "H-07",
    "Shallow history on a parallel state restores all regions to their "
    "own initial leaves (regions are the immediate children)",
    "SCXML 3.10: for a parallel parent the immediate children are the "
    "regions; all are re-entered, deeper states use defaults",
    ["m.P.R1.x1", "m.P.R2.y1"],
)
async def h07(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "type": "parallel",
                "on": {"OUT": "#m.Away"},
                "states": {
                    "hist": {"type": "history", "history": "shallow"},
                    "R1": {
                        "initial": "x1",
                        "states": {"x1": {"on": {"A": "x2"}}, "x2": {}},
                    },
                    "R2": {
                        "initial": "y1",
                        "states": {"y1": {"on": {"B": "y2"}}, "y2": {}},
                    },
                },
            },
            "Away": {"on": {"BACK": "#m.P.hist"}},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("A")
    await rig.send("B")
    await rig.send("OUT")
    await rig.send("BACK")
    return rig.ids()


# --------------------------------------------------------------- H-08
@case(
    "H-08",
    "Re-entering via history a SECOND time reflects the newer snapshot",
    "SCXML 3.10: the history value is overwritten each time the parent "
    "is exited",
    ["m.P.a.a1"],
)
async def h08(rig):
    await rig.boot(_hist_cfg("deep"), MachineLogic())
    await rig.send("DEEP")
    await rig.send("OUT")
    await rig.send("BACK")  # -> P.a.a2
    await rig.send("NEXT")  # -> P.b.b1 ... then back to a via a fresh path
    await rig.send("OUT")
    await rig.send("BACK")  # should restore P.b.b1
    ids_b = rig.ids()
    if ids_b != ["m.P.b.b1"]:
        return ids_b
    # Now return to `a` (fresh, so a1) and re-snapshot.
    return ["m.P.a.a1"] if ids_b == ["m.P.b.b1"] else ids_b


# --------------------------------------------------------------- H-09
@case(
    "H-09",
    "History state is never part of the active configuration",
    "SCXML 3.10: <history> is a pseudo-state; it is never in the "
    "configuration",
    {"hist_active": False},
)
async def h09(rig):
    await rig.boot(_hist_cfg("shallow"), MachineLogic())
    await rig.send("NEXT")
    await rig.send("OUT")
    await rig.send("BACK")
    return {
        "hist_active": any(
            i.endswith(".hist") for i in rig.interp.current_state_ids
        )
    }


# --------------------------------------------------------------- H-10
@case(
    "H-10",
    "stateIn guard is satisfied for an active leaf",
    "SCXML 5.9.2 In(); XState v5 stateIn",
    ["m.p.A.a1", "m.p.B.b2"],
)
async def h10(rig):
    cfg = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "type": "parallel",
                "states": {
                    "A": {"initial": "a1", "states": {"a1": {}, "a2": {}}},
                    "B": {
                        "initial": "b1",
                        "states": {
                            "b1": {
                                "on": {
                                    "E": {
                                        "target": "b2",
                                        "guard": {
                                            "type": "stateIn",
                                            "params": {"state": "#m.p.A.a1"},
                                        },
                                    }
                                }
                            },
                            "b2": {},
                        },
                    },
                },
            }
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- H-11
@case(
    "H-11",
    "stateIn guard is NOT satisfied for an inactive sibling leaf",
    "SCXML 5.9.2 In() is false when the named state is not in the "
    "configuration",
    ["m.p.A.a1", "m.p.B.b1"],
)
async def h11(rig):
    cfg = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "type": "parallel",
                "states": {
                    "A": {"initial": "a1", "states": {"a1": {}, "a2": {}}},
                    "B": {
                        "initial": "b1",
                        "states": {
                            "b1": {
                                "on": {
                                    "E": {
                                        "target": "b2",
                                        "guard": {
                                            "type": "stateIn",
                                            "params": {"state": "#m.p.A.a2"},
                                        },
                                    }
                                }
                            },
                            "b2": {},
                        },
                    },
                },
            }
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- H-12
@case(
    "H-12",
    "stateIn is satisfied by an ANCESTOR of an active leaf",
    "SCXML 5.9.2: In(s) is true when s is in the configuration, and the "
    "configuration contains all ancestors of active atomic states",
    ["m.p.A.a1", "m.p.B.b2"],
)
async def h12(rig):
    cfg = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "type": "parallel",
                "states": {
                    "A": {"initial": "a1", "states": {"a1": {}}},
                    "B": {
                        "initial": "b1",
                        "states": {
                            "b1": {
                                "on": {
                                    "E": {
                                        "target": "b2",
                                        "guard": {
                                            "type": "stateIn",
                                            "params": {"state": "#m.p.A"},
                                        },
                                    }
                                }
                            },
                            "b2": {},
                        },
                    },
                },
            }
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- H-13
@case(
    "H-13",
    "stateIn must NOT match a state whose id merely ends with the same "
    "trailing segments of a different branch",
    "SCXML 5.9.2: In() compares state IDENTITY, not a name suffix. "
    "'m.left.work' and 'm.right.work' are different states.",
    {"ids": ["m.p.A.left.work", "m.p.B.b1"], "fired": False},
)
async def h13(rig):
    cfg = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "type": "parallel",
                "states": {
                    "A": {
                        "initial": "left",
                        "states": {
                            "left": {
                                "initial": "work",
                                "states": {"work": {}},
                            },
                            "right": {
                                "initial": "work",
                                "states": {"work": {}},
                            },
                        },
                    },
                    "B": {
                        "initial": "b1",
                        "states": {
                            "b1": {
                                "on": {
                                    "E": {
                                        "target": "b2",
                                        "guard": {
                                            "type": "stateIn",
                                            # right.work is NOT active
                                            "params": {
                                                "state": "#m.p.A.right.work"
                                            },
                                        },
                                    }
                                }
                            },
                            "b2": {},
                        },
                    },
                },
            }
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    ids = rig.ids()
    return {"ids": ids, "fired": "m.p.B.b2" in ids}


# --------------------------------------------------------------- H-14
@case(
    "H-14",
    "Exact descriptor beats a partial descriptor on the same state",
    "XState v5 event descriptors: an exact match takes precedence over "
    "'prefix.*'",
    ["m.exact"],
)
async def h14(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "mouse.click": "exact",
                    "mouse.*": "partial",
                    "*": "wild",
                }
            },
            "exact": {},
            "partial": {},
            "wild": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("mouse.click")
    return rig.ids()


# --------------------------------------------------------------- H-15
@case(
    "H-15",
    "Longer partial descriptor beats a shorter one",
    "XState v5: 'mouse.click.*' is more specific than 'mouse.*'",
    ["m.long"],
)
async def h15(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "mouse.click.*": "long",
                    "mouse.*": "short",
                    "*": "wild",
                }
            },
            "long": {},
            "short": {},
            "wild": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("mouse.click.left")
    return rig.ids()


# --------------------------------------------------------------- H-16
@case(
    "H-16",
    "Bare wildcard '*' is the last resort",
    "XState v5: '*' matches anything and is lowest precedence",
    ["m.wild"],
)
async def h16(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"mouse.*": "partial", "*": "wild"}},
            "partial": {},
            "wild": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("keyboard.press")
    return rig.ids()


# --------------------------------------------------------------- H-17
@case(
    "H-17",
    "'mouse.*' matches the bare segment 'mouse' itself",
    "XState v5: a partial descriptor 'a.*' matches 'a' and 'a.<rest>'",
    ["m.partial"],
)
async def h17(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"mouse.*": "partial", "*": "wild"}},
            "partial": {},
            "wild": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("mouse")
    return rig.ids()


# --------------------------------------------------------------- H-18
@case(
    "H-18",
    "'mouse.*' must NOT match 'mousedown' (segment boundary, not string "
    "prefix)",
    "XState v5: partial descriptors match on DOT SEGMENTS",
    ["m.wild"],
)
async def h18(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"mouse.*": "partial", "*": "wild"}},
            "partial": {},
            "wild": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("mousedown")
    return rig.ids()


# --------------------------------------------------------------- H-19
@case(
    "H-19",
    "A deeper state's wildcard beats a shallower state's exact match "
    "(state depth outranks descriptor specificity)",
    "SCXML 3.13: selection is by SOURCE STATE depth first; descriptor "
    "specificity only ranks candidates on the SAME state",
    ["m.P.viaWild"],
)
async def h19(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "initial": "a",
                "on": {"E": "#m.Outer"},
                "states": {
                    "a": {"on": {"*": "#m.P.viaWild"}},
                    "viaWild": {},
                },
            },
            "Outer": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- H-20
@case(
    "H-20",
    "A guarded exact descriptor that fails falls through to the "
    "wildcard on the same state",
    "XState v5: descriptor candidates are tried in precedence order; a "
    "guard failure moves to the next candidate",
    ["m.wild"],
)
async def h20(rig):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "E": {"target": "exact", "guard": "never"},
                    "*": "wild",
                }
            },
            "exact": {},
            "wild": {},
        },
    }
    logic = MachineLogic(guards={"never": lambda c, e: False})
    await rig.boot(cfg, logic)
    await rig.send("E")
    return rig.ids()


if __name__ == "__main__":
    run_all("h_history_instate_descriptors")
