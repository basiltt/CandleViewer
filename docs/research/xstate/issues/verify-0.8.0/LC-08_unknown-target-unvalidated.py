"""LC-08 verification on xstate-statemachine 0.8.0.

0.8.0 (#29, #30) adds build-time validation: create_machine() walks the
finished tree and rejects any transition target that does not resolve.
Default strict_targets=True; strict_targets=False is a deprecated escape
hatch restoring 0.7.x silent-no-op behaviour.
"""

from __future__ import annotations

import asyncio
import sys
import warnings

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.exceptions import InvalidConfigError
from xstate_statemachine.interpreter import Interpreter

BAD_TARGET = {
    "id": "m",
    "initial": "s",
    "states": {"s": {"on": {"GO": "nowhere_at_all"}}, "t": {}},
}


async def default_case() -> bool:
    try:
        create_machine(BAD_TARGET, logic=MachineLogic())
        print("DEFAULT OBSERVED: create_machine() did NOT raise")
        return False
    except InvalidConfigError as exc:
        print(f"DEFAULT OBSERVED: create_machine() raised InvalidConfigError: {exc}")
        return "nowhere_at_all" in str(exc)


async def optout_case() -> bool:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        machine = create_machine(BAD_TARGET, logic=MachineLogic(), strict_targets=False)
        warned = any(issubclass(x.category, DeprecationWarning) for x in w)
    interp = await Interpreter(machine).start()
    await interp.send("GO")
    await asyncio.sleep(0.05)
    state = sorted(interp.current_state_ids)
    running = interp.is_running
    await interp.stop()
    print(
        f"OPT-OUT (strict_targets=False) OBSERVED: state={state} running={running} "
        f"deprecation_warning={warned}"
    )
    # documents legacy silent no-op persists under explicit opt-out
    return state == ["m.s"] and running and warned


async def main() -> int:
    print("EXPECTED (default): create_machine() raises InvalidConfigError naming "
          "'nowhere_at_all' -- like an unknown action name already does.")
    default_ok = await default_case()
    optout_ok = await optout_case()
    print(f"RESULT default_ok={default_ok} legacy_optout_matches_0.7.x={optout_ok}")
    return 0 if default_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
