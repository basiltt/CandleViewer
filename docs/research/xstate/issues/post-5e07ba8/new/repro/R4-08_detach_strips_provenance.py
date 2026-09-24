"""R4-08: send(engine_event, wait=True) silently demotes an engine-minted
event to user traffic, because Interpreter._detach() rebuilds the Event
through dataclasses.replace(), which constructs via __init__ and therefore
cannot carry the init=False `_provenance` field (events.py:122-124).

Compares wait=False (no _detach path) with wait=True (_detach path) sending
the SAME engine-minted event to an onUnhandled:"error" machine.

EXPECTED (per this library's own #85/#86 contract, quoted in events.py:114-121):
    an engine-minted Event's provenance must survive re-processing; asking
    for a receipt (wait=True) must not change whether the event is treated
    as system traffic.
OBSERVED: wait=False -> status stays "running" (event honoured as system
traffic). wait=True -> status becomes "error" (UnhandledEventError): the
same object, merely re-detached for a receipt, is now user traffic.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import system_event

CFG = {
    "id": "m",
    "initial": "a",
    "onUnhandled": "error",
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}


async def run(wait: bool) -> str:
    interp = Interpreter(create_machine(CFG, logic=MachineLogic()))
    await interp.start()
    await interp.send(
        system_event("xstate.error.actor.child", error="boom"), wait=wait
    )
    await asyncio.sleep(0.2)
    status = interp.status
    if status == "running":
        await interp.stop()
    return status


async def main() -> int:
    status_false = await run(False)
    status_true = await run(True)
    print(f"wait=False -> status={status_false}")
    print(f"wait=True  -> status={status_true}")

    defect_present = status_false == "running" and status_true == "error"
    print(
        "\nOBSERVED:",
        "wait=True demoted the engine-minted event to user traffic "
        "(status='error')"
        if defect_present
        else "provenance preserved across both calls",
    )
    print(
        "EXPECTED: both calls report status='running' "
        "(provenance preserved regardless of wait=)"
    )
    print("RESULT:", "FAIL - defect present" if defect_present else "PASS")
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
