"""J1 -- ReentrantWaitError matrix (round-11 #219), both engines.

Cases:
  self:          action awaits self.send(X, wait=True) on its own interp -> refused
  ensure_future: action does asyncio.ensure_future(interp.send(X, wait=True))
                 -> allowed (receipt handed out, awaited after the step)
  after-fired:   an `after` handler awaits wait=True on its own interp -> refused
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import ReentrantWaitError

RESULT = {}


def _cfg(after=False):
    if after:
        states = {
            "a": {"after": {10: {"target": "b", "actions": ["selfwait"]}}},
            "b": {},
        }
    else:
        states = {
            "a": {"on": {"GO": {"target": "b", "actions": ["selfwait"]}}},
            "b": {},
        }
    return {"id": "rw", "initial": "a", "states": states}


async def case_self_async():
    box = {}

    async def selfwait(i, c, e, a):
        try:
            await i.send("PING", wait=True)
            box["r"] = "no-error"
        except ReentrantWaitError as ex:
            box["r"] = type(ex).__name__

    machine = create_machine(_cfg(), logic=MachineLogic(actions={"selfwait": selfwait}))
    clock = SimulatedClock()
    interp = Interpreter(machine, clock=clock)
    await interp.start()
    await interp.send("GO", wait=True)
    await interp.stop()
    return box.get("r")


def case_self_sync():
    box = {}

    def selfwait(i, c, e, a):
        try:
            i.send("PING", wait=True)
            box["r"] = "no-error"
        except ReentrantWaitError as ex:
            box["r"] = type(ex).__name__

    machine = create_machine(_cfg(), logic=MachineLogic(actions={"selfwait": selfwait}))
    clock = SimulatedClock()
    interp = SyncInterpreter(machine, clock=clock)
    interp.start()
    interp.send("GO", wait=True)
    interp.stop()
    return box.get("r")


async def case_ensure_future_async():
    box = {}

    async def selfwait(i, c, e, a):
        box["fut"] = asyncio.ensure_future(i.send("PING", wait=True))

    machine = create_machine(_cfg(), logic=MachineLogic(actions={"selfwait": selfwait}))
    clock = SimulatedClock()
    interp = Interpreter(machine, clock=clock)
    await interp.start()
    await interp.send("GO", wait=True)
    if "fut" not in box:
        await interp.stop()
        return "action-not-fired"
    r = await box["fut"]
    await interp.stop()
    return "no-error" if r is not None else "none"


async def case_after_async():
    box = {}

    async def selfwait(i, c, e, a):
        try:
            await i.send("PING", wait=True)
            box["r"] = "no-error"
        except ReentrantWaitError as ex:
            box["r"] = type(ex).__name__

    machine = create_machine(_cfg(after=True), logic=MachineLogic(actions={"selfwait": selfwait}))
    clock = SimulatedClock()
    interp = Interpreter(machine, clock=clock)
    await interp.start()
    await clock.increment(10)
    for _ in range(5):
        await asyncio.sleep(0)
    await interp.stop()
    return box.get("r")


def main():
    RESULT["self_async"] = asyncio.run(case_self_async())
    RESULT["self_sync"] = case_self_sync()
    RESULT["ensure_future_async"] = asyncio.run(case_ensure_future_async())
    RESULT["after_fired_async"] = asyncio.run(case_after_async())
    for k, v in RESULT.items():
        print(f"{k:22s}: {v}")
    ok = (
        RESULT["self_async"] == "ReentrantWaitError"
        and RESULT["self_sync"] == "ReentrantWaitError"
        and RESULT["ensure_future_async"] == "no-error"
        and RESULT["after_fired_async"] == "ReentrantWaitError"
    )
    print("VERDICT PASS" if ok else "VERDICT FAIL")


if __name__ == "__main__":
    main()
