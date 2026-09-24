"""R5-15 repro: #130 `escalate` reaches the parent's `onError` only when the
`invoke` declares an explicit `id`.

`id` is OPTIONAL on an `invoke`; the parser defaults it to the state's own
id (`models.py`, `_parse_invoke`: `invoke_id = i_config.get("id", self.id)`),
and the runtime actor address for an id-less invoke keeps that synthesised
id (`interpreter.py::_start_invoked_actor`: `f"{self.id}:{invocation.src}:{uuid4()}"`
only when NOT `invocation.id_is_explicit`... but the ESCALATE handler at
`base_interpreter.py` strips the parent-id prefix off `self.id` and matches
it against the invoke's `id`, which for the id-less shape is the STATE id,
not the synthesised actor id -- so the match fails and the parent never
hears about it. A plain callable service that raises reaches `onError` in
both shapes; this is specific to `escalate`.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CHILD = {
    "id": "c",
    "initial": "w",
    "states": {
        "w": {"entry": [{"type": "escalate", "params": {"error": "child exploded"}}]},
    },
}

PARENT = {
    "id": "p",
    "initial": "w",
    # No explicit `id` on the invoke -- legal per the schema, and the
    # library's own default fills one in.
    "states": {"w": {"invoke": {"src": "kid", "onError": "caught"}}, "caught": {}},
}


async def main() -> int:
    logic = MachineLogic(services={"kid": create_machine(CHILD, logic=MachineLogic())})
    interp = Interpreter(create_machine(PARENT, logic=logic))
    await interp.start()

    for _ in range(60):
        if "p.caught" in interp.current_state_ids:
            break
        await asyncio.sleep(0.02)

    states = sorted(interp.current_state_ids)
    status = interp.status
    reached = "p.caught" in states
    await interp.stop()

    print("OBSERVED:")
    print(f"  current_state_ids = {states}")
    print(f"  status            = {status}")
    print(f"  reached_onError   = {reached}")

    print("EXPECTED:")
    print("  current_state_ids = ['p.caught']  (escalate from an id-less invoke")
    print("                       reaches onError exactly like an explicit-id one)")

    print("RESULT:", "PASS" if reached else "FAIL - escalate lost with no explicit invoke.id")
    return 0 if reached else 1


sys.exit(asyncio.run(main()))
