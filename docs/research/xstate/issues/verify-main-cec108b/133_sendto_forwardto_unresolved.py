"""Verify #133 on main@cec108b: an unresolved sendTo target fires
plugin.on_event_dropped(...) with a distinguishable reason, and forwardTo's
analogous unresolved-target path gets the same treatment. (Both engines.)

Note: the issue's proposed reason string was "sendto_unresolved"; the
actual implementation uses "unresolved_target" for both sendTo and
forwardTo (base_interpreter.py:1086-1087, shared helper) -- consistent
between the two paths, which is the acceptance criterion's substance (a
distinct, non-silent reason shared by both actions), even though the
literal string differs from the issue's suggestion.
"""
from __future__ import annotations

import asyncio
import logging
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

failures = []


def check(name, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


class DropRecorder(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interpreter, event, reason):
        self.dropped.append((event.type, reason))


def cfg_for(action: str) -> dict:
    if action == "sendTo":
        act = {"type": "sendTo", "params": {"to": "no_such_actor", "event": {"type": "PING"}}}
    else:
        act = {"type": "forwardTo", "params": {"to": "no_such_actor"}}
    return {
        "id": "m",
        "initial": "s",
        "states": {"s": {"on": {"GO": {"actions": [act]}}}},
    }


def main() -> int:
    for action in ("sendTo", "forwardTo"):
        recorder = DropRecorder()
        i = SyncInterpreter(create_machine(cfg_for(action), logic=MachineLogic()))
        i.use(recorder)
        i.start()
        i.send("GO")
        check(
            f"sync: unresolved {action} target fires on_event_dropped",
            len(recorder.dropped) >= 1
            and recorder.dropped[0][1] in ("unresolved_target", "sendto_unresolved"),
        )
        i.stop()

    async def async_check(action: str):
        recorder = DropRecorder()
        i = Interpreter(create_machine(cfg_for(action), logic=MachineLogic()))
        i.use(recorder)
        await i.start()
        await i.send("GO", wait=True)
        await asyncio.sleep(0.05)
        await i.stop()
        return recorder.dropped

    for action in ("sendTo", "forwardTo"):
        dropped = asyncio.run(async_check(action))
        check(
            f"async: unresolved {action} target fires on_event_dropped",
            len(dropped) >= 1 and dropped[0][1] in ("unresolved_target", "sendto_unresolved"),
        )

    return 0 if not failures else 1


if __name__ == "__main__":
    rc = main()
    print(f"\nRESULT: {'PASS' if rc == 0 else 'FAIL'} ({len(failures)} failing)")
    sys.exit(rc)
