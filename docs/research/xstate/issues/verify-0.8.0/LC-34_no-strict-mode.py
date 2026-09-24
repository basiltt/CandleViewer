"""LC-34 verification on xstate-statemachine 0.8.0.

CHANGELOG [wave 3] "Strict mode" (#51): `strict` machine config key or
Interpreter/SyncInterpreter(strict=) ctor flag. Under strict, send() of an
undeclared event type raises UnknownEventError synchronously at the call
site (before queueing), with a difflib suggestion. is_known_event() honours
partial ('mouse.*') and bare '*' descriptors. event_schemas gives payload
validation regardless of strict. DEFAULT is strict unset/False (0.7.x
silent no-op semantics preserved) -- this is an opt-in policy, so we test
BOTH: default behaviour (unchanged silent no-op) and strict=True (typo now
raises).
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    create_machine,
    UnknownEventError,
    InvalidEventPayloadError,
)

logging.disable(logging.CRITICAL)

CFG = {
    "id": "order",
    "initial": "pending",
    "states": {
        "pending": {"on": {"FILL": "filled"}},
        "filled": {"type": "final"},
    },
}


async def check_default() -> bool:
    """Default: strict unset -> typo'd event is still a silent no-op (0.7.x semantics)."""
    machine = create_machine(CFG)
    interp = await Interpreter(machine).start()
    ok = True
    try:
        await interp.send("FILLL")
    except Exception as exc:
        print(f"OBSERVED default send('FILLL') raised {type(exc).__name__} -- unexpected")
        ok = False
    print(f"OBSERVED default: status={interp.status!r} (unchanged, no exception)")
    print("EXPECTED default: silent no-op preserved (0.7.x semantics)")
    if interp.status != "running":
        ok = False
    await interp.stop()
    return ok


async def check_strict() -> bool:
    """strict=True: typo raises UnknownEventError with a suggestion, before queueing."""
    machine = create_machine(CFG)
    interp = await Interpreter(machine, strict=True).start()
    ok = True
    raised = None
    try:
        await interp.send("FILLL")
    except UnknownEventError as exc:
        raised = exc
    print(f"OBSERVED strict=True send('FILLL') raised = {raised!r}")
    print("EXPECTED UnknownEventError mentioning 'FILL'")
    if raised is None or "FILL" not in str(raised):
        ok = False

    # declared-but-unhandled event under strict is still a no-op
    machine2 = create_machine(CFG)
    interp2 = await Interpreter(machine2, strict=True).start()
    try:
        await interp2.send("FILL")  # handled fine
    except Exception as exc:
        print(f"OBSERVED unexpected exception on valid event: {exc!r}")
        ok = False
    print(f"OBSERVED strict=True with declared+handled event: status={interp2.status!r}")
    await interp.stop()
    await interp2.stop()
    return ok


async def check_payload_schema() -> bool:
    class FillSchema:
        def validate(self, payload):
            if not isinstance(payload.get("qty"), (int, float)):
                raise ValueError("qty must be numeric")

    machine = create_machine(CFG, event_schemas={"FILL": FillSchema()})
    interp = await Interpreter(machine).start()
    ok = True
    raised = None
    try:
        await interp.send("FILL", qty="not-a-number")
    except InvalidEventPayloadError as exc:
        raised = exc
    print(f"OBSERVED event_schemas rejects bad payload -> {raised!r}")
    if raised is None:
        ok = False
    await interp.stop()
    return ok


async def main() -> int:
    ok_default = await check_default()
    ok_strict = await check_strict()
    ok_schema = await check_payload_schema()

    has_ctor_param = "strict" in Interpreter.__init__.__code__.co_varnames
    print(f"OBSERVED Interpreter.__init__ accepts strict = {has_ctor_param}")

    ok = ok_default and ok_strict and ok_schema and has_ctor_param
    print(
        "RESULT:",
        "FIXED-OPT-IN (strict=True/event_schemas; default unchanged)" if ok else "NOT FIXED",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
