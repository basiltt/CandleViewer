# -*- coding: utf-8 -*-
"""Verify #147 on main@cec108b: RootTargetError is non-downgradable.

Acceptance criteria (from gh issue #147 + CHANGELOG [Unreleased]):
  1. A transition targeting the machine root raises RootTargetError
     regardless of strict_targets (True AND False).
  2. RootTargetError is a subclass of InvalidConfigError and message
     mentions "machine root".
  3. A genuinely unresolvable (non-root) target with strict_targets=False
     still only WARNS (does not raise) -- the escape hatch still works for
     its documented purpose.
  4. Both engines agree (sync + async) -- covered implicitly since the
     rejection is at create_machine()/build time, before any engine runs.

Exit 0 only if every criterion passes.
"""
from __future__ import annotations

import sys
import warnings

from xstate_statemachine import (
    InvalidConfigError,
    RootTargetError,
    create_machine,
)

CFG_ROOT = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "#m"}}, "b": {}}}
CFG_UNRESOLVABLE = {"id": "m2", "initial": "a", "states": {"a": {"on": {"GO": "nowhere"}}}}

failures: list[str] = []


def check(label: str, cond: bool) -> None:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


def main() -> int:
    # --- Criterion 1 & 2: both flag values raise RootTargetError ---
    for strict in (True, False):
        try:
            create_machine(CFG_ROOT, strict_targets=strict)
            check(f"strict_targets={strict} raises RootTargetError", False)
        except RootTargetError as exc:
            check(f"strict_targets={strict} raises RootTargetError", True)
            check(
                f"strict_targets={strict} error isinstance InvalidConfigError",
                isinstance(exc, InvalidConfigError),
            )
            check(
                f"strict_targets={strict} message mentions 'machine root'",
                "machine root" in str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            check(
                f"strict_targets={strict} raises RootTargetError "
                f"(got {type(exc).__name__} instead)",
                False,
            )

    # --- Criterion 3: genuinely unresolvable target still only warns ---
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            create_machine(CFG_UNRESOLVABLE, strict_targets=False)
        warned = any("unresolvable" in str(x.message) for x in w)
        check("genuinely unresolvable target with strict_targets=False warns", warned)
    except Exception as exc:  # noqa: BLE001
        check(
            f"genuinely unresolvable target with strict_targets=False warns "
            f"(raised {type(exc).__name__} instead)",
            False,
        )

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} criteria failed)")
        return 1
    print("RESULT: PASS (all criteria satisfied)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
