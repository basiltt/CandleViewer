"""LC-06 verification on xstate-statemachine 0.8.0.

0.8.0 adds build-time target validation (`create_machine(..., strict_targets=True)`,
default True). This must reject the LC-06 config at create_machine() time
instead of silently binding the foreign `audit.archive.filled` node at runtime.

We test:
  1. DEFAULT (strict_targets=True): create_machine() must raise
     InvalidConfigError naming the unresolvable target.
  2. OPT-OUT (strict_targets=False): the 0.7.x fallback behaviour is
     restored (with a DeprecationWarning) -- documented, not asserted as a pass/fail.
"""

from __future__ import annotations

import asyncio
import sys
import warnings

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import InvalidConfigError

CFG = {
    "id": "m",
    "type": "parallel",
    "context": {},
    "states": {
        "audit": {
            "initial": "archive",
            "states": {
                "archive": {
                    "initial": "open",
                    "states": {"open": {}, "filled": {}},
                }
            },
        },
        "order": {
            "initial": "submitting",
            "states": {
                "submitting": {"on": {"FILL": "filled"}},
                "done": {},
            },
        },
    },
}


async def default_case() -> bool:
    """strict_targets=True (default): must raise at create_machine()."""
    try:
        create_machine(CFG, logic=MachineLogic())
        print("DEFAULT OBSERVED: create_machine() did NOT raise")
        return False
    except InvalidConfigError as exc:
        msg = str(exc)
        print(f"DEFAULT OBSERVED: create_machine() raised InvalidConfigError: {msg}")
        return "filled" in msg and "order" in msg


async def optin_legacy_case() -> str:
    """strict_targets=False: document what the escape hatch still does."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        machine = create_machine(CFG, logic=MachineLogic(), strict_targets=False)
        warned = any(issubclass(x.category, DeprecationWarning) for x in w)
    interp = await Interpreter(machine).start()
    await interp.send("FILL")
    await asyncio.sleep(0.2)
    observed = sorted(interp.current_state_ids)
    await interp.stop()
    bad = "m.audit.archive.filled" in observed
    print(
        f"OPT-OUT (strict_targets=False) OBSERVED: state={observed} "
        f"bound_foreign_state={bad} deprecation_warning={warned}"
    )
    return bad, warned


async def main() -> int:
    print("EXPECTED (default): create_machine() raises InvalidConfigError for "
          "unresolvable target 'filled' in 'order'; audit region never touched.")
    default_ok = await default_case()

    bad, warned = await optin_legacy_case()
    print(
        "EXPECTED (strict_targets=False, documented legacy escape hatch): "
        "restores 0.7.x fallback binding AND emits a DeprecationWarning."
    )

    print(f"RESULT default_ok={default_ok} legacy_fallback_bound={bad} legacy_warned={warned}")

    # Acceptance: default behaviour now rejects the config at build time.
    return 0 if default_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
