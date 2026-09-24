# -*- coding: utf-8 -*-
"""Verify #109 on 3ed3099: `done.invoke.<id>` must carry the invoked child's
declared final-state `output`, not its private `context`, on BOTH engines.

Acceptance criteria (from issue #109 body + CHANGELOG [Unreleased]):
  1. When an invoked child reaches a `final` state that declares `output`,
     the parent's `done.invoke.<id>` event's `.data` must equal that
     declared `output` -- on the ASYNC engine (`Interpreter`).
  2. Same, on the SYNC engine (`SyncInterpreter`).
  3. The child's private context (e.g. a secret key not part of `output`)
     must NOT leak into `.data` -- this was the "double defect": lost
     result AND leaked private state.
  4. The parent must still reach its `onDone` target (the payload fix must
     not break the normal success path).

Exits 0 only if all criteria pass.
"""
from __future__ import annotations

import asyncio
import logging
import time

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

logging.disable(logging.CRITICAL)

CHILD = {
    "id": "kid",
    "initial": "w",
    "context": {"secret_api_key": "sk-PRIVATE", "ctxkey": 1},
    "states": {
        "w": {"always": "fin"},
        "fin": {"type": "final", "output": {"code": 7}},
    },
}
PARENT = {
    "id": "m",
    "initial": "run",
    "states": {
        "run": {
            "invoke": {
                "id": "kid",
                "src": "kidm",
                "onDone": {"target": "done", "actions": ["cap"]},
            }
        },
        "done": {},
    },
}

seen = {}


def cap(interp, ctx, event, action_def):
    seen["data"] = event.data


def parent(engine_child):
    return create_machine(
        PARENT,
        logic=MachineLogic(actions={"cap": cap}, services={"kidm": engine_child}),
    )


async def async_run():
    seen.clear()
    i = Interpreter(parent(create_machine(CHILD, logic=MachineLogic())))
    await i.start()
    await asyncio.sleep(0.4)
    data = seen.get("data")
    reached_done = "m.done" in i.current_state_ids
    await i.stop()
    return data, reached_done


def sync_run():
    seen.clear()
    s = SyncInterpreter(parent(create_machine(CHILD, logic=MachineLogic())))
    s.start()
    for _ in range(50):
        if s.value == "done":
            break
        s.tick()
        time.sleep(0.01)
    data = seen.get("data")
    reached_done = s.value == "done"
    s.stop()
    return data, reached_done


def main() -> int:
    expected = {"code": 7}
    failures = []

    async_data, async_done = asyncio.run(async_run())
    print(f"async: data={async_data!r} reached_done={async_done}")
    if async_data != expected:
        failures.append(f"criterion 1 FAILED: async data={async_data!r} != {expected!r}")
    if not async_done:
        failures.append("criterion 4 FAILED (async): parent did not reach onDone target")
    if isinstance(async_data, dict) and "secret_api_key" in async_data:
        failures.append("criterion 3 FAILED (async): child's private context leaked")

    sync_data, sync_done = sync_run()
    print(f"sync:  data={sync_data!r} reached_done={sync_done}")
    if sync_data != expected:
        failures.append(f"criterion 2 FAILED: sync data={sync_data!r} != {expected!r}")
    if not sync_done:
        failures.append("criterion 4 FAILED (sync): parent did not reach onDone target")
    if isinstance(sync_data, dict) and "secret_api_key" in sync_data:
        failures.append("criterion 3 FAILED (sync): child's private context leaked")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL CRITERIA PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
