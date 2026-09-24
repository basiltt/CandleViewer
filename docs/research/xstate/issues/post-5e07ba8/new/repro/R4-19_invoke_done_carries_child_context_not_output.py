# -*- coding: utf-8 -*-
"""R4-19: an invoked child's `output` is discarded; `done.invoke` carries the
child's private `context` instead.

`interpreter.py` (async) and `sync_interpreter.py` (sync) both build
`DoneEvent(data=child.context)`. XState v5 delivers the child's resolved
`output` on `done.invoke.<id>`. The result is a double defect: the computed
result is silently lost, and the child's full internal context leaks to the
parent.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

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


def cap(interp, ctx, event, action_def):  # noqa: ANN001
    seen["data"] = event.data


def parent(engine_child):
    return create_machine(
        PARENT,
        logic=MachineLogic(actions={"cap": cap}, services={"kidm": engine_child}),
    )


async def main() -> int:
    expected = {"code": 7}

    i = Interpreter(parent(create_machine(CHILD, logic=MachineLogic())))
    await i.start()
    await asyncio.sleep(0.4)
    async_data = seen.get("data")
    await i.stop()

    seen.clear()
    s = SyncInterpreter(parent(create_machine(CHILD, logic=MachineLogic())))
    s.start()
    sync_data = seen.get("data")

    print("OBSERVED: async done.invoke.kid data = %r" % (async_data,))
    print("OBSERVED: sync  done.invoke.kid data = %r" % (sync_data,))
    print("EXPECTED: both = %r (the child's declared final `output`), and the "
          "child's private context key 'secret_api_key' must NOT appear."
          % (expected,))

    leaked = [
        name
        for name, d in (("async", async_data), ("sync", sync_data))
        if isinstance(d, dict) and "secret_api_key" in d
    ]
    if leaked:
        print("OBSERVED: child private context LEAKED on:", ", ".join(leaked))

    ok = async_data == expected and sync_data == expected
    print("RESULT:", "PASS" if ok else "FAIL (child output discarded)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
