"""F5 - entry/exit-action snapshot refusal at NESTED and PARALLEL states
(targets #169, which the library's own tests exercise only at root level).

Attack: take get_persisted_snapshot() from inside entry/exit actions at
(a) a nested child two levels deep, (b) inside a parallel region's entry,
(c) inside an EXIT action (not just entry), on both engines. Any ACCEPTED
result while context is mid-write (i.e. context not yet reflecting the
in-progress write) would mean a torn snapshot escapes at these windows too.
"""
from __future__ import annotations

import logging
import sys

logging.disable(logging.CRITICAL)
LIB = "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from xstate_statemachine import (  # noqa: E402
    MachineLogic,
    SnapshotMidStepError,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.interpreter import Interpreter  # noqa: E402
import asyncio  # noqa: E402

# Nested + parallel machine: 'top' -> parallel regions r1/r2; r1 has a
# compound child 'mid' -> 'deep' two levels down.
CFG = {
    "id": "np",
    "type": "parallel",
    "context": {"qty": 0, "flag": 0},
    "states": {
        "r1": {
            "initial": "idle",
            "states": {
                "idle": {"on": {"GO": "mid"}},
                "mid": {
                    "initial": "midA",
                    "states": {
                        "midA": {"on": {"DEEPER": "deep"}},
                        "deep": {
                            "entry": ["enter_deep"],
                            "exit": ["exit_deep"],
                            "on": {"LEAVE": "midA"},
                        },
                    },
                },
            },
        },
        "r2": {
            "initial": "waiting",
            "states": {
                "waiting": {"on": {"GO": "active"}},
                "active": {"entry": ["enter_r2active"]},
            },
        },
    },
}

results = {}


def enter_deep(i, c, e, a=None):
    c["qty"] = 1
    try:
        i.get_persisted_snapshot()
        results["deep_entry"] = "ACCEPTED"
    except SnapshotMidStepError:
        results["deep_entry"] = "REFUSED"
    c["qty"] = 999


def exit_deep(i, c, e, a=None):
    c["flag"] = 1
    try:
        i.get_persisted_snapshot()
        results["deep_exit"] = "ACCEPTED"
    except SnapshotMidStepError:
        results["deep_exit"] = "REFUSED"
    c["flag"] = 888


def enter_r2active(i, c, e, a=None):
    c["qty"] = 2
    try:
        i.get_persisted_snapshot()
        results["r2_entry"] = "ACCEPTED"
    except SnapshotMidStepError:
        results["r2_entry"] = "REFUSED"
    c["qty"] = 777


def run_sync():
    global results
    results = {}
    logic = MachineLogic(
        actions={
            "enter_deep": enter_deep,
            "exit_deep": exit_deep,
            "enter_r2active": enter_r2active,
        }
    )
    s = SyncInterpreter(create_machine(CFG, logic=logic)).start()
    s.send("GO")  # both regions transition; r1->mid.midA, r2->active (fires enter_r2active)
    s.send("DEEPER")  # r1.mid: midA -> deep (fires enter_deep)
    s.send("LEAVE")  # r1.mid: deep -> midA (fires exit_deep)
    return dict(results), dict(s.context)


async def run_async():
    global results
    results = {}
    logic = MachineLogic(
        actions={
            "enter_deep": enter_deep,
            "exit_deep": exit_deep,
            "enter_r2active": enter_r2active,
        }
    )
    i = Interpreter(create_machine(CFG, logic=logic))
    await i.start()
    await i.send("GO", wait=True)
    await i.send("DEEPER", wait=True)
    await i.send("LEAVE", wait=True)
    out = (dict(results), dict(i.context))
    await i.stop()
    return out


if __name__ == "__main__":
    sync_results, sync_ctx = run_sync()
    print("SYNC results:", sync_results)
    print("SYNC final ctx:", sync_ctx)

    async_results, async_ctx = asyncio.run(run_async())
    print("ASYNC results:", async_results)
    print("ASYNC final ctx:", async_ctx)

    all_refused = all(v == "REFUSED" for v in sync_results.values()) and all(
        v == "REFUSED" for v in async_results.values()
    )
    print("ALL_REFUSED (both engines, all 3 windows):", all_refused)
