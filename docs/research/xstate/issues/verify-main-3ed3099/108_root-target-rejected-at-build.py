# -*- coding: utf-8 -*-
"""Verify #108 on 3ed3099: a transition targeting the machine root must be
rejected at build time, for both `always` and ordinary `on` transitions.

Acceptance criteria (from issue #108 body + CHANGELOG [Unreleased]):
  1. `{"id": "m", "initial": "a", "states": {"a": {"always": "#m"}, "b": {}}}`
     must raise `InvalidConfigError` at `create_machine(...)` time (not
     silently build and empty the configuration at runtime).
  2. The error message must name the machine root as the problem (mentions
     "machine root"), per CHANGELOG "A transition targeting the machine
     root is rejected at build (#108)".
  3. The same rejection applies to an ordinary `on` transition targeting
     the root (`"on": {"GO": "#m"}`), not just `always` -- the issue body
     says "The same happens for an ordinary `on` transition targeting the
     root, so this is not specific to `always`."
  4. A transition targeting the root's initial child (`#m.a`, i.e. a
     *specific* state) must NOT be rejected -- confirms the fix targets
     only the root itself, not all id-based targeting.

Exits 0 only if all criteria pass.
"""
from __future__ import annotations

import asyncio
import logging

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import InvalidConfigError

logging.disable(logging.CRITICAL)

ALWAYS_CFG = {"id": "m", "initial": "a", "states": {"a": {"always": "#m"}, "b": {}}}
EVENT_CFG = {
    "id": "m2",
    "initial": "a",
    "states": {"a": {"on": {"GO": "#m2"}}, "b": {}},
}
SPECIFIC_TARGET_CFG = {
    "id": "m3",
    "initial": "a",
    "states": {"a": {"on": {"GO": "#m3.b"}}, "b": {}},
}


def main() -> int:
    failures = []

    # Criterion 1 + 2: `always` -> root rejected, message names the root.
    try:
        create_machine(ALWAYS_CFG, logic=MachineLogic())
        failures.append("criterion 1 FAILED: always->#m built without error")
    except InvalidConfigError as e:
        msg = str(e)
        print(f"always->root correctly raised InvalidConfigError: {msg}")
        if "machine root" not in msg:
            failures.append(
                f"criterion 2 FAILED: error message does not mention "
                f"'machine root': {msg!r}"
            )
    except Exception as e:
        failures.append(
            f"criterion 1 FAILED: wrong exception type {type(e).__name__}: {e}"
        )

    # Criterion 3: ordinary `on` -> root also rejected.
    try:
        create_machine(EVENT_CFG, logic=MachineLogic())
        failures.append("criterion 3 FAILED: on GO->#m2 built without error")
    except InvalidConfigError as e:
        print(f"on GO->root correctly raised InvalidConfigError: {e}")
    except Exception as e:
        failures.append(
            f"criterion 3 FAILED: wrong exception type {type(e).__name__}: {e}"
        )

    # Criterion 4: a specific (non-root) target must still build fine and
    # actually transition -- proves the fix is scoped to the root only.
    try:
        m3 = create_machine(SPECIFIC_TARGET_CFG, logic=MachineLogic())
        s = SyncInterpreter(m3)
        s.start()
        s.send("GO")
        if sorted(s.current_state_ids) != ["m3.b"]:
            failures.append(
                f"criterion 4 FAILED: specific-target machine ended in "
                f"{sorted(s.current_state_ids)}, expected ['m3.b']"
            )
        else:
            print("specific target (#m3.b) built and transitioned correctly")
        s.stop()
    except Exception as e:
        failures.append(
            f"criterion 4 FAILED: specific-target machine raised unexpectedly: {e}"
        )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL CRITERIA PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
