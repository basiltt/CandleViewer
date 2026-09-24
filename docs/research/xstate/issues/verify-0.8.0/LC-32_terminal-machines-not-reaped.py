"""LC-32 verification on xstate-statemachine 0.8.0.

CHANGELOG [wave 2] "Reaching a top-level final state now tears down" (#57):
child actors stopped, timers/invokes cancelled, actor-system registration
removed the moment status becomes done/error -- not just when stop() is
later called. Unconditional (not opt-in). status/output/context are
retained; stop() on a done machine is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

CHILD = {
    "id": "leg",
    "initial": "work",
    "states": {
        "work": {"after": {100_000: {"target": "fin"}}},
        "fin": {"type": "final"},
    },
}

SPAWN = {"type": "spawn_leg", "params": {"id": "legA", "systemId": "legsys"}}

CFG = {
    "id": "order",
    "initial": "pending",
    "context": {"blob": None},
    "states": {
        "pending": {"entry": [SPAWN], "on": {"FILL": "filled"}},
        "filled": {"type": "final"},
    },
}


async def main() -> int:
    machine = create_machine(
        CFG, logic=MachineLogic(services={"leg": create_machine(CHILD)})
    )
    interp = Interpreter(machine)
    interp.context["blob"] = ["x"] * 50_000
    await interp.start()
    await asyncio.sleep(0.05)
    print(
        f"OBSERVED while running: actors={sorted(interp._actors)} "
        f"system={sorted(interp.system.get_all())}"
    )

    await interp.send("FILL")
    await asyncio.sleep(0.15)

    child = next(iter(interp._actors.values()), None)
    print(f"OBSERVED status={interp.status!r} is_running={interp.is_running}")
    print(f"OBSERVED context retained: len(blob)={len(interp.context['blob'])}")
    print(f"OBSERVED actors after done  = {sorted(interp._actors)}")
    print(
        f"OBSERVED child after done: status="
        f"{child.status if child else None!r}"
    )
    print(f"OBSERVED system registry after done = {sorted(interp.system.get_all())}")

    reaped_on_done = (not interp._actors) and (
        child is None or child.status != "running"
    ) and (not interp.system.get_all())

    await interp.stop()
    await asyncio.sleep(0.05)
    print(f"OBSERVED after explicit stop(): actors={sorted(interp._actors)} "
          f"system={sorted(interp.system.get_all())}")
    empty_after_stop = not interp.system.get_all()
    status_still_done = interp.status == "done"
    output_readable = True
    try:
        _ = interp.output
    except Exception:
        output_readable = False

    print(
        "EXPECTED on final state: child stopped, tasks cancelled, registry "
        "empty, status stays 'done', context/output still readable"
    )

    ok = reaped_on_done and empty_after_stop and status_still_done and output_readable
    print("RESULT:", "FIXED (teardown on completion; registry cleaned)" if ok else "NOT FIXED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
