"""Group T — eventless (always) transitions, transient states, after:0,
done.state for compound and parallel states, final output.

SCXML 1.0 §3.13 (eventless transitions run in the same macrostep),
§3.7 (final / done.state.*), XState v5 `always` and `output`.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conf_harness import case, run_all  # noqa: E402

from xstate_statemachine import MachineLogic  # noqa: E402


# --------------------------------------------------------------- T-01
@case(
    "T-01",
    "Eventless chain settles within one macrostep (a -> b -> c)",
    "SCXML 3.13: after each microstep the engine re-evaluates eventless "
    "transitions until none is enabled; XState v5 `always`",
    ["m.c"],
)
async def t01(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"always": "b"},
            "b": {"always": "c"},
            "c": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    return rig.ids()


# --------------------------------------------------------------- T-02
@case(
    "T-02",
    "Eventless guard re-evaluated after each microstep: assign in a "
    "transition unblocks the next always",
    "SCXML 3.13: eventless transitions are re-selected after every "
    "microstep, so a datamodel change made in microstep N is visible in "
    "microstep N+1",
    {"ids": ["m.done"], "n": 3},
)
async def t02(rig):
    def _bump(i, c, e, a):
        c["n"] += 1

    cfg = {
        "id": "m",
        "initial": "loop",
        "context": {"n": 0},
        "states": {
            "loop": {
                "always": [
                    {"target": "done", "guard": "at3"},
                    {
                        "target": "loop",
                        "reenter": True,
                        "actions": ["bump"],
                    },
                ]
            },
            "done": {},
        },
    }
    logic = MachineLogic(
        guards={"at3": lambda c, e: c["n"] >= 3},
        actions={"bump": _bump},
    )
    await rig.boot(cfg, logic)
    return {"ids": rig.ids(), "n": rig.ctx()["n"]}


# --------------------------------------------------------------- T-03
@case(
    "T-03",
    "Eventless transition fires immediately after an event transition, "
    "in the same macrostep (caller never observes the transient state)",
    "SCXML 3.13 macrostep = event microstep followed by eventless "
    "microsteps until stable",
    ["m.c"],
)
async def t03(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"on": {"E": "b"}},
            "b": {"always": "c"},
            "c": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- T-04
@case(
    "T-04",
    "Transient state entry/exit actions run even though it is never "
    "observable",
    "SCXML 3.8/3.9: onentry and onexit run for every state entered, "
    "including states left in the same macrostep",
    ["eb", "xb"],
)
async def t04(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"on": {"E": "b"}},
            "b": {"entry": ["eb"], "exit": ["xb"], "always": "c"},
            "c": {},
        },
    }
    logic = MachineLogic(actions=rig.recorders("eb", "xb"))
    await rig.boot(cfg, logic)
    rig.log.clear()
    await rig.send("E")
    return rig.log


# --------------------------------------------------------------- T-05
@case(
    "T-05",
    "Eventless transition with a false guard does not fire; machine "
    "rests in the state",
    "SCXML 3.13: an eventless transition whose cond is false is not "
    "enabled",
    ["m.b"],
)
async def t05(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"on": {"E": "b"}},
            "b": {"always": {"target": "c", "guard": "never"}},
            "c": {},
        },
    }
    logic = MachineLogic(guards={"never": lambda c, e: False})
    await rig.boot(cfg, logic)
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- T-06
@case(
    "T-06",
    "after:0 fires as a delayed event, NOT as an eventless transition: "
    "it is a separate macrostep",
    "XState v5: `after: {0: ...}` schedules a delayed event with delay 0; "
    "it is not `always`. It must still settle without external input.",
    ["m.b"],
)
async def t06(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"after": {0: "b"}},
            "b": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.sleep(0.1)
    return rig.ids()


# --------------------------------------------------------------- T-07
@case(
    "T-07",
    "after:0 chain of three states settles",
    "XState v5 after:0; SCXML <send delay='0'> is queued to the external "
    "queue and processed in a later macrostep",
    ["m.d"],
)
async def t07(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"after": {0: "b"}},
            "b": {"after": {0: "c"}},
            "c": {"after": {0: "d"}},
            "d": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.sleep(0.25)
    return rig.ids()


# --------------------------------------------------------------- T-08
@case(
    "T-08",
    "Leaving a state cancels its pending `after` timer",
    "SCXML 6.2.2 / XState v5: delayed sends owned by a state are "
    "cancelled when the state is exited",
    ["m.other"],
)
async def t08(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"after": {120: "late"}, "on": {"E": "other"}},
            "other": {},
            "late": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    await rig.sleep(0.3)
    return rig.ids()


# --------------------------------------------------------------- T-09
@case(
    "T-09",
    "done.state.<compound> fires when the compound state reaches a final "
    "child, triggering onDone",
    "SCXML 3.7: entering a <final> child generates done.state.<parent>",
    ["m.after"],
)
async def t09(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "initial": "a",
                "onDone": "after",
                "states": {
                    "a": {"on": {"E": "fin"}},
                    "fin": {"type": "final"},
                },
            },
            "after": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- T-10
@case(
    "T-10",
    "done.state.<parallel> fires only when EVERY region is in a final "
    "state (not on the first)",
    "SCXML 3.7: for a <parallel>, done.state is generated when all of "
    "its children are in final states",
    {"after_one": ["m.P.A.fin", "m.P.B.b1"], "after_both": ["m.after"]},
)
async def t10(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "type": "parallel",
                "onDone": "#m.after",
                "states": {
                    "A": {
                        "initial": "a1",
                        "states": {
                            "a1": {"on": {"FA": "fin"}},
                            "fin": {"type": "final"},
                        },
                    },
                    "B": {
                        "initial": "b1",
                        "states": {
                            "b1": {"on": {"FB": "fin"}},
                            "fin": {"type": "final"},
                        },
                    },
                },
            },
            "after": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("FA")
    one = rig.ids()
    await rig.send("FB")
    return {"after_one": one, "after_both": rig.ids()}


# --------------------------------------------------------------- T-11
@case(
    "T-11",
    "done.state payload carries the final state's `output`",
    "SCXML 3.7 <donedata>; XState v5 final `output` becomes "
    "event.output/data on done.state.*",
    {"code": 42},
)
async def t11(rig):
    seen = {}

    def grab(i, c, e, a):
        seen["data"] = getattr(e, "data", None)

    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "initial": "a",
                "onDone": {"target": "#m.after", "actions": ["grab"]},
                "states": {
                    "a": {"on": {"E": "fin"}},
                    "fin": {"type": "final", "output": {"code": 42}},
                },
            },
            "after": {},
        },
    }
    await rig.boot(cfg, MachineLogic(actions={"grab": grab}))
    await rig.send("E")
    return seen.get("data")


# --------------------------------------------------------------- T-12
@case(
    "T-12",
    "Top-level final state completes the machine: status 'done' and "
    "machine output resolved",
    "SCXML 3.7: entering a top-level final state terminates the session; "
    "XState v5 status 'done' with machine output",
    {"status": "done", "output": {"ok": True}},
)
async def t12(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "output": {"ok": True},
        "states": {
            "a": {"on": {"E": "fin"}},
            "fin": {"type": "final"},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return {
        "status": rig.interp.status,
        "output": rig.interp.output,
    }


# --------------------------------------------------------------- T-13
@case(
    "T-13",
    "A final state's own `output` reaches machine output when the "
    "machine declares none",
    "XState v5: without a machine-level output, the top-level final "
    "state's output is the machine output",
    {"v": 9},
)
async def t13(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"on": {"E": "fin"}},
            "fin": {"type": "final", "output": {"v": 9}},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.interp.output


# --------------------------------------------------------------- T-14
@case(
    "T-14",
    "A stopped/done machine accepts no further transitions",
    "SCXML 3.7: after the session terminates no further events are "
    "processed",
    {"status": "done", "ids_unchanged": True},
)
async def t14(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"on": {"E": "fin"}},
            "fin": {"type": "final"},
            "never": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    before = rig.ids()
    try:
        await rig.send("E")
    except Exception:  # noqa: BLE001
        pass
    return {
        "status": rig.interp.status,
        "ids_unchanged": rig.ids() == before,
    }


# --------------------------------------------------------------- T-15
@case(
    "T-15",
    "onDone on a parallel state does not fire when only one region has "
    "a final state at all",
    "SCXML 3.7: all regions must be final; a region with no final state "
    "can never satisfy the condition",
    ["m.P.A.fin", "m.P.B.b1"],
)
async def t15(rig):
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "type": "parallel",
                "onDone": "#m.after",
                "states": {
                    "A": {
                        "initial": "a1",
                        "states": {
                            "a1": {"on": {"FA": "fin"}},
                            "fin": {"type": "final"},
                        },
                    },
                    "B": {"initial": "b1", "states": {"b1": {}}},
                },
            },
            "after": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("FA")
    return rig.ids()


# --------------------------------------------------------------- T-16
@case(
    "T-16",
    "Nested done: inner compound completes -> its final state is the "
    "outer's final -> outer done.state fires",
    "SCXML 3.7 recursive done computation",
    ["m.end"],
)
async def t16(rig):
    cfg = {
        "id": "m",
        "initial": "Outer",
        "states": {
            "Outer": {
                "initial": "Inner",
                "onDone": "#m.end",
                "states": {
                    "Inner": {
                        "initial": "i1",
                        "onDone": "#m.Outer.ofin",
                        "states": {
                            "i1": {"on": {"E": "ifin"}},
                            "ifin": {"type": "final"},
                        },
                    },
                    "ofin": {"type": "final"},
                },
            },
            "end": {},
        },
    }
    await rig.boot(cfg, MachineLogic())
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- T-17
@case(
    "T-17",
    "`always` on an ancestor is evaluated for the active leaf",
    "SCXML 3.13: eventless transitions are selected by the same "
    "upward-walk rule as evented ones",
    ["m.out"],
)
async def t17(rig):
    def _yes(i, c, e, a):
        c["go"] = True

    cfg = {
        "id": "m",
        "initial": "P",
        "context": {"go": False},
        "states": {
            "P": {
                "initial": "a",
                "always": {"target": "#m.out", "guard": "go"},
                "states": {
                    "a": {"on": {"E": {"actions": ["yes"]}}}
                },
            },
            "out": {},
        },
    }
    logic = MachineLogic(
        guards={"go": lambda c, e: c["go"]},
        actions={"yes": _yes},
    )
    await rig.boot(cfg, logic)
    await rig.send("E")
    return rig.ids()


# --------------------------------------------------------------- T-18
@case(
    "T-18",
    "Eventless self-loop without progress is bounded, not an infinite "
    "hang (engine must terminate)",
    "SCXML 3.13 note: an unconditional eventless self-loop is a "
    "non-terminating macrostep; a production engine must bound it. "
    "Library documents maxIterations / RunawayChainError.",
    {"terminated": True},
)
async def t18(rig):
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"always": {"target": "a", "reenter": True}},
        },
    }
    try:
        await rig.boot(cfg, MachineLogic())
        return {"terminated": True}
    except Exception:  # noqa: BLE001
        return {"terminated": True}


if __name__ == "__main__":
    run_all("t_eventless_done")
