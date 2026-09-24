"""Standalone recheck of #218 (timer handle leak on fire/cancel), both engines.
Run from neutral cwd C:/Users/basil with the library's venv-main python.
"""
import asyncio
import json
import sys

sys.path.insert(0, r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "leak",
    "initial": "up",
    "states": {
        "up": {
            "entry": [{"type": "raise", "params": {"event": "BEAT", "delay": 10}}, "beat"],
            "on": {"BEAT": "down"},
        },
        "down": {
            "entry": [{"type": "raise", "params": {"event": "BEAT", "delay": 10}}, "beat"],
            "on": {"BEAT": "up"},
        },
    },
}


def mk(**kw):
    return create_machine(json.loads(json.dumps(CFG)), **kw)


def sync_check():
    n = {"beats": 0}
    logic = MachineLogic(actions={"beat": lambda i, c, e, a: n.__setitem__("beats", n["beats"] + 1)})
    clock = SimulatedClock()
    s = SyncInterpreter(mk(logic=logic), clock=clock)
    s.start()
    for _ in range(200):
        clock.increment(10)
    held = sum(len(v) for v in s._timer_handles.values())
    s.stop()
    print("SYNC beats=", n["beats"], "held=", held)
    assert n["beats"] >= 150
    assert held <= 1, f"leak: {held}"


async def async_check():
    n = {"beats": 0}
    logic = MachineLogic(actions={"beat": lambda i, c, e, a: n.__setitem__("beats", n["beats"] + 1)})
    clock = SimulatedClock()
    i = await Interpreter(mk(logic=logic), clock=clock).start()
    for _ in range(200):
        await clock.increment(10)
    held = sum(len(v) for v in i._timer_handles.values())
    await i.stop()
    print("ASYNC beats=", n["beats"], "held=", held)
    assert n["beats"] >= 150
    assert held <= 1, f"leak: {held}"


def sync_cancel_check():
    cfg = {
        "id": "c",
        "initial": "a",
        "states": {
            "a": {
                "entry": [{"type": "raise", "params": {"event": "X", "delay": 500, "id": "k"}}],
                "on": {"CUT": {"actions": [{"type": "cancel", "params": {"sendId": "k"}}]}},
            }
        },
    }
    clock = SimulatedClock()
    s = SyncInterpreter(create_machine(json.loads(json.dumps(cfg))), clock=clock)
    s.start()
    held_before = sum(len(v) for v in s._timer_handles.values())
    s.send({"type": "CUT"})
    held_after = sum(len(v) for v in s._timer_handles.values())
    s.stop()
    print("SYNC cancel: before=", held_before, "after=", held_after)
    assert held_before == 1
    assert held_after == 0


async def async_cancel_check():
    cfg = {
        "id": "c",
        "initial": "a",
        "states": {
            "a": {
                "entry": [{"type": "raise", "params": {"event": "X", "delay": 500, "id": "k"}}],
                "on": {"CUT": {"actions": [{"type": "cancel", "params": {"sendId": "k"}}]}},
            }
        },
    }
    clock = SimulatedClock()
    i = await Interpreter(create_machine(json.loads(json.dumps(cfg))), clock=clock).start()
    held_before = sum(len(v) for v in i._timer_handles.values())
    await i.send({"type": "CUT"}, wait=True)
    held_after = sum(len(v) for v in i._timer_handles.values())
    await i.stop()
    print("ASYNC cancel: before=", held_before, "after=", held_after)
    assert held_before == 1
    assert held_after == 0


if __name__ == "__main__":
    sync_check()
    asyncio.run(async_check())
    sync_cancel_check()
    asyncio.run(async_cancel_check())
    print("ALL OK")
