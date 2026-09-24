"""R10-07 (STANDALONE): unknown TOP-LEVEL config keys are accepted silently, so
a misspelled SAFETY POLICY downgrades to its permissive default with no
diagnostic.

Bad *values* for *known* keys are still correctly refused with
`InvalidConfigError` -- that part works, and the control below proves it. What
is missing is any whitelist validation of the top-level key SET.

For a system where the chart config is the safety envelope, the keys most
likely to be mistyped are exactly the ones you cannot afford to lose:
`actionErrorPolicy`, `guardErrorPolicy`, `onUnhandled`, `maxIterations`,
`strict`. A single-character typo silently reverts each to its permissive
default and the build stays green.

Exit 0 = misspelled keys are diagnosed (fixed).
Exit 1 = any misspelled key builds clean while its value is dropped (defect).

Stdlib + xstate_statemachine only. Runs from any cwd. No watchdog needed
(build-time only), but one is supplied for uniformity.
"""
from __future__ import annotations

import json
import sys

from xstate_statemachine import create_machine, MachineLogic

BASE = {"id": "m", "initial": "a", "states": {"a": {}}}

# (typo'd key, correct key, attribute the correct key sets, declared value)
TYPOS = [
    ("spawnBlockingTimeoutMs", "spawnBlockingTimeout", "spawn_blocking_timeout_ms", 1234),
    ("actionErrorPolicyy", "actionErrorPolicy", "action_error_policy", "rollback"),
    ("guardErrorPolicies", "guardErrorPolicy", "guard_error_policy", "deny"),
    ("maxIteration", "maxIterations", "max_iterations", 42),
    ("onUnhandledEvent", "onUnhandled", "on_unhandled", "error"),
    ("Strict", "strict", "strict", True),
]


def _build(cfg: dict):
    return create_machine(json.loads(json.dumps(cfg)), logic=MachineLogic())


def main() -> int:
    bad = 0
    print(f"{'typo key':<26}{'built?':<9}{'attr':<26}{'value seen':<14}verdict")

    for typo, correct, attr, value in TYPOS:
        cfg = dict(BASE)
        cfg[typo] = value
        try:
            m = _build(cfg)
            built, seen = True, getattr(m, attr, "<no attr>")
        except Exception as exc:  # noqa: BLE001 - any refusal is the good case
            built, seen = False, type(exc).__name__

        # Reference: what the CORRECT key produces, so "value seen" is comparable.
        cfg2 = dict(BASE)
        cfg2[correct] = value
        try:
            ref = getattr(_build(cfg2), attr, "<no attr>")
        except Exception as exc:  # noqa: BLE001
            ref = f"<{type(exc).__name__}>"

        silent = built and seen != ref
        bad += 1 if silent else 0
        print(f"{typo:<26}{str(built):<9}{attr:<26}{str(seen):<14}"
              f"{'SILENT DOWNGRADE (ref=' + str(ref) + ')' if silent else 'ok'}")

    # Control: a bad VALUE for a KNOWN key must still be refused.
    try:
        _build({**BASE, "actionErrorPolicy": "not-a-policy"})
        print("\ncontrol: bad value for a known key -> ACCEPTED  <-- would be worse")
        bad += 1
    except Exception as exc:  # noqa: BLE001
        print(f"\ncontrol: bad value for a known key -> refused with "
              f"{type(exc).__name__} (correct)")

    print()
    print("VERDICT:", "DEFECT PRESENT" if bad else "ok",
          f"({bad}/{len(TYPOS)} keys silently dropped)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
