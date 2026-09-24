"""Probe suite B: invoke lifecycle, done.invoke / done.state output,
error.platform propagation, invoke cancellation on state exit,
delayed (after) transitions and their cancellation, history states.
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

SETTLE = 0.1


async def boot(cfg, logic):
    return await Interpreter(create_machine(cfg, logic=logic)).start()


# ---------------------------------------------------------------- B1
@probe(
    "B1",
    "invoke success -> done.invoke.<id> carries service return value in event.data",
    {"state": ["m.ok"], "data": {"filled": 42}},
)
async def b1():
    seen: Dict[str, Any] = {}

    async def svc(interp, ctx, evt):  # noqa: ANN001
        await asyncio.sleep(0.01)
        return {"filled": 42}

    def capture(i, c, e, a):  # noqa: ANN001
        seen["data"] = e.data

    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {
                    "id": "job",
                    "src": "svc",
                    "onDone": {"target": "ok", "actions": ["capture"]},
                }
            },
            "ok": {},
        },
    }
    logic = MachineLogic(actions={"capture": capture}, services={"svc": svc})
    i = await boot(cfg, logic)
    await asyncio.sleep(0.2)
    out = {"state": sorted(i.current_state_ids), "data": seen.get("data")}
    await i.stop()
    return out


# ---------------------------------------------------------------- B2
@probe(
    "B2",
    "invoke failure -> error.platform.<id> handled by onError, data is the exception",
    {"state": ["m.failed"], "err": "boom", "type": "RuntimeError"},
)
async def b2():
    seen: Dict[str, Any] = {}

    async def svc(interp, ctx, evt):  # noqa: ANN001
        raise RuntimeError("boom")

    def capture(i, c, e, a):  # noqa: ANN001
        seen["err"] = str(e.data)
        seen["type"] = type(e.data).__name__

    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {
                    "id": "job",
                    "src": "svc",
                    "onError": {"target": "failed", "actions": ["capture"]},
                }
            },
            "failed": {},
        },
    }
    logic = MachineLogic(actions={"capture": capture}, services={"svc": svc})
    i = await boot(cfg, logic)
    await asyncio.sleep(0.2)
    out = {
        "state": sorted(i.current_state_ids),
        "err": seen.get("err"),
        "type": seen.get("type"),
    }
    await i.stop()
    return out


# ---------------------------------------------------------------- B3
@probe(
    "B3",
    "invoke failure with NO onError: interpreter must enter status 'error' "
    "rather than silently idling as 'running'",
    {"status": "error", "is_running": False},
)
async def b3():
    async def svc(interp, ctx, evt):  # noqa: ANN001
        raise RuntimeError("unhandled")

    cfg = {
        "id": "m",
        "initial": "run",
        "states": {"run": {"invoke": {"id": "job", "src": "svc"}}, "other": {}},
    }
    logic = MachineLogic(services={"svc": svc})
    i = await boot(cfg, logic)
    await asyncio.sleep(0.2)
    out = {"status": i.status, "is_running": i.is_running}
    try:
        await i.stop()
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------------------------------------------------------------- B4
@probe(
    "B4",
    "invoke is cancelled mid-await when its state is exited by an external event",
    {"cancelled": True, "completed": False, "state": ["m.b"]},
)
async def b4():
    flags = {"cancelled": False, "completed": False}

    async def svc(interp, ctx, evt):  # noqa: ANN001
        try:
            await asyncio.sleep(5.0)
            flags["completed"] = True
            return "done"
        except asyncio.CancelledError:
            flags["cancelled"] = True
            raise

    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {"id": "job", "src": "svc", "onDone": "done_s"},
                "on": {"ABORT": "b"},
            },
            "b": {},
            "done_s": {},
        },
    }
    logic = MachineLogic(services={"svc": svc})
    i = await boot(cfg, logic)
    await asyncio.sleep(0.05)
    await i.send("ABORT")
    await asyncio.sleep(0.2)
    out = {
        "cancelled": flags["cancelled"],
        "completed": flags["completed"],
        "state": sorted(i.current_state_ids),
    }
    await i.stop()
    return out


# ---------------------------------------------------------------- B5
@probe(
    "B5",
    "Cancelled invoke does NOT deliver a late done.invoke event after exit",
    {"late_done": False},
)
async def b5():
    flags = {"late_done": False}

    async def svc(interp, ctx, evt):  # noqa: ANN001
        await asyncio.sleep(0.15)
        return "late"

    def mark(i, c, e, a):  # noqa: ANN001
        flags["late_done"] = True

    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {
                    "id": "job",
                    "src": "svc",
                    "onDone": {"target": "done_s", "actions": ["mark"]},
                },
                "on": {"ABORT": "b"},
            },
            "b": {"on": {"*": {"actions": ["mark"]}}},
            "done_s": {},
        },
    }
    logic = MachineLogic(actions={"mark": mark}, services={"svc": svc})
    i = await boot(cfg, logic)
    await asyncio.sleep(0.02)
    await i.send("ABORT")
    await asyncio.sleep(0.35)
    out = {"late_done": flags["late_done"]}
    await i.stop()
    return out


# ---------------------------------------------------------------- B6
@probe(
    "B6",
    "onDone of a compound state fires when its child reaches a final state",
    ["m.after"],
)
async def b6():
    cfg = {
        "id": "m",
        "initial": "work",
        "states": {
            "work": {
                "initial": "w1",
                "onDone": "after",
                "states": {
                    "w1": {"on": {"FIN": "w2"}},
                    "w2": {"type": "final"},
                },
            },
            "after": {},
        },
    }
    i = await boot(cfg, MachineLogic())
    await i.send("FIN")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


# ---------------------------------------------------------------- B7
@probe(
    "B7",
    "Parallel onDone fires only when ALL regions reach final",
    {"after_one": ["m.P.A.af", "m.P.B.b1"], "after_both": ["m.after"]},
)
async def b7():
    cfg = {
        "id": "m",
        "initial": "P",
        "states": {
            "P": {
                "type": "parallel",
                "onDone": "after",
                "states": {
                    "A": {
                        "initial": "a1",
                        "states": {
                            "a1": {"on": {"FA": "af"}},
                            "af": {"type": "final"},
                        },
                    },
                    "B": {
                        "initial": "b1",
                        "states": {
                            "b1": {"on": {"FB": "bf"}},
                            "bf": {"type": "final"},
                        },
                    },
                },
            },
            "after": {},
        },
    }
    i = await boot(cfg, MachineLogic())
    await i.send("FA")
    await asyncio.sleep(SETTLE)
    one = sorted(i.current_state_ids)
    await i.send("FB")
    await asyncio.sleep(SETTLE)
    both = sorted(i.current_state_ids)
    await i.stop()
    return {"after_one": one, "after_both": both}


# ---------------------------------------------------------------- B8
@probe(
    "B8",
    "final state 'output' is surfaced on the done.state event data",
    {"state": ["m.after"], "data": {"code": 7}},
)
async def b8():
    seen: Dict[str, Any] = {}

    def cap(i, c, e, a):  # noqa: ANN001
        seen["data"] = getattr(e, "data", None)

    cfg = {
        "id": "m",
        "initial": "work",
        "states": {
            "work": {
                "initial": "w1",
                "onDone": {"target": "after", "actions": ["cap"]},
                "states": {
                    "w1": {"on": {"FIN": "w2"}},
                    "w2": {"type": "final", "output": {"code": 7}},
                },
            },
            "after": {},
        },
    }
    logic = MachineLogic(actions={"cap": cap})
    i = await boot(cfg, logic)
    await i.send("FIN")
    await asyncio.sleep(SETTLE)
    out = {"state": sorted(i.current_state_ids), "data": seen.get("data")}
    await i.stop()
    return out


# ---------------------------------------------------------------- B9
@probe("B9", "after (delayed) transition fires on time", ["m.late"])
async def b9():
    cfg = {
        "id": "m",
        "initial": "wait",
        "states": {
            "wait": {"after": {100: "late"}},
            "late": {},
        },
    }
    i = await boot(cfg, MachineLogic())
    await asyncio.sleep(0.3)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


# ---------------------------------------------------------------- B10
@probe(
    "B10",
    "after timer is cancelled when the state is exited before it fires",
    {"state": ["m.other"], "fired": False},
)
async def b10():
    flags = {"fired": False}

    def mark(i, c, e, a):  # noqa: ANN001
        flags["fired"] = True

    cfg = {
        "id": "m",
        "initial": "wait",
        "states": {
            "wait": {
                "after": {150: {"target": "late", "actions": ["mark"]}},
                "on": {"SKIP": "other"},
            },
            "late": {"entry": ["mark"]},
            "other": {"on": {"*": {"actions": ["mark"]}}},
        },
    }
    logic = MachineLogic(actions={"mark": mark})
    i = await boot(cfg, logic)
    await asyncio.sleep(0.02)
    await i.send("SKIP")
    await asyncio.sleep(0.35)
    out = {"state": sorted(i.current_state_ids), "fired": flags["fired"]}
    await i.stop()
    return out


# ---------------------------------------------------------------- B11
@probe(
    "B11",
    "after timer restarts (not resumes) on re-entry to the same state",
    {"state": ["m.wait"], "fired": False},
)
async def b11():
    flags = {"fired": False}

    def mark(i, c, e, a):  # noqa: ANN001
        flags["fired"] = True

    cfg = {
        "id": "m",
        "initial": "wait",
        "states": {
            "wait": {
                "after": {200: {"target": "late", "actions": ["mark"]}},
                "on": {"BOUNCE": "mid"},
            },
            "mid": {"always": "wait"},
            "late": {},
        },
    }
    logic = MachineLogic(actions={"mark": mark})
    i = await boot(cfg, logic)
    await asyncio.sleep(0.15)
    await i.send("BOUNCE")  # re-enter wait; timer should restart at 0
    await asyncio.sleep(0.12)  # total 0.27 > 200ms but only 0.12 since re-entry
    out = {"state": sorted(i.current_state_ids), "fired": flags["fired"]}
    await i.stop()
    return out


# ---------------------------------------------------------------- B12
@probe(
    "B12",
    "Shallow history restores the immediate child (A1) and then A1's own "
    "INITIAL descendant, discarding the deep leaf 'y'",
    ["m.A.A1.x"],
)
async def b12():
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "initial": "A1",
                "states": {
                    "A1": {
                        "initial": "x",
                        "states": {
                            "x": {"on": {"DEEP": "y"}},
                            "y": {},
                        },
                        "on": {"OUT": "#m.B"},
                    },
                    "hist": {"type": "history", "history": "shallow"},
                },
            },
            "B": {"on": {"BACK": "#m.A.hist"}},
        },
    }
    i = await boot(cfg, MachineLogic())
    await i.send("DEEP")
    await asyncio.sleep(SETTLE)
    await i.send("OUT")
    await asyncio.sleep(SETTLE)
    await i.send("BACK")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


# ---------------------------------------------------------------- B13
@probe("B13", "Deep history restores the full nested leaf", ["m.A.A1.y"])
async def b13():
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "initial": "A1",
                "states": {
                    "A1": {
                        "initial": "x",
                        "states": {"x": {"on": {"DEEP": "y"}}, "y": {}},
                        "on": {"OUT": "#m.B"},
                    },
                    "hist": {"type": "history", "history": "deep"},
                },
            },
            "B": {"on": {"BACK": "#m.A.hist"}},
        },
    }
    i = await boot(cfg, MachineLogic())
    await i.send("DEEP")
    await asyncio.sleep(SETTLE)
    await i.send("OUT")
    await asyncio.sleep(SETTLE)
    await i.send("BACK")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


# ---------------------------------------------------------------- B14
@probe(
    "B14",
    "History with no prior visit falls back to the parent's initial state",
    ["m.A.A1.x"],
)
async def b14():
    cfg = {
        "id": "m",
        "initial": "B",
        "states": {
            "A": {
                "initial": "A1",
                "states": {
                    "A1": {"initial": "x", "states": {"x": {}, "y": {}}},
                    "hist": {"type": "history", "history": "deep"},
                },
            },
            "B": {"on": {"GO": "#m.A.hist"}},
        },
    }
    i = await boot(cfg, MachineLogic())
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    st = sorted(i.current_state_ids)
    await i.stop()
    return st


if __name__ == "__main__":
    run_all("02_invoke_timers_history")
