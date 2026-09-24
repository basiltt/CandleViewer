"""R5-14 repro: a user-supplied action named `spawn_*` is never called.

`_execute_actions` routes any action whose type starts with `spawn_` /
`spawn_blocking_` to the built-in spawn resolver BEFORE consulting
`machine.logic.actions` -- unlike every other built-in name (`log`,
`assign`, ...), which is resolved only when the user has NOT supplied an
action of the same name. So `spawn_*` is the one prefix that silently
steals a name out of the user's own namespace.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["spawn_place_order"]}}},
        "b": {},
    },
}


async def main() -> int:
    called = []

    def spawn_place_order(interpreter, ctx, event, action_def):
        called.append("spawn_place_order")

    logic = MachineLogic(actions={"spawn_place_order": spawn_place_order})
    interp = Interpreter(create_machine(CFG, logic=logic))
    await interp.start()

    err = None
    try:
        await interp.send("GO")
        await asyncio.sleep(0.05)
    except BaseException as exc:  # noqa: BLE001
        err = exc

    states = sorted(interp.current_state_ids)
    status = interp.status
    await interp.stop()

    print("OBSERVED:")
    print(f"  user_action_called = {called}")
    print(f"  current_state_ids  = {states}")
    print(f"  status             = {status}")
    print(f"  error              = {err!r}")

    print("EXPECTED:")
    print("  user_action_called = ['spawn_place_order']  (the declared action runs,")
    print("                        exactly like a user-defined 'log' or 'assign' does)")
    print("  current_state_ids  = ['m.b']")

    failed = called != ["spawn_place_order"] or states != ["m.b"]
    print("RESULT:", "FAIL - spawn_* hijacked the user action" if failed else "PASS")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
