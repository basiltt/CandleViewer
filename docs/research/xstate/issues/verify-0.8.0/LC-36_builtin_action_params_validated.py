"""LC-36 verification on xstate-statemachine 0.8.0.

Acceptance: create_machine() rejects a built-in action whose required
params are missing (or misspelled at the top level) with InvalidConfigError,
naming the stray key, while the correct 'params'-nested spelling still parses
and callables are exempt. This is a build-time validation with no opt-in
flag, so we only need to test the default path.
"""

from __future__ import annotations

import sys

from xstate_statemachine import InvalidConfigError, create_machine


def cfg(raise_action: dict) -> dict:
    return {
        "id": "eval",
        "initial": "idle",
        "states": {
            "idle": {"on": {"EVALUATE": {"target": "scoring"}}},
            "scoring": {"entry": [raise_action], "on": {"PLACE": "placed"}},
            "placed": {"type": "final"},
        },
    }


WRONG = {"type": "raise", "event": "PLACE"}  # top-level, misspelled
RIGHT = {"type": "raise", "params": {"event": "PLACE"}}  # correct nesting


def main() -> int:
    ok = True

    # 1) misspelled/top-level params -> must raise InvalidConfigError
    try:
        create_machine(cfg(WRONG))
        print(f"OBSERVED: create_machine() accepted {WRONG} with no error")
        print("EXPECTED: InvalidConfigError naming 'params' and 'event'")
        ok = False
    except InvalidConfigError as exc:
        msg = str(exc)
        print(f"OBSERVED: create_machine() raised InvalidConfigError: {msg}")
        names_stray = "'event'" in msg or "event" in msg
        names_params = "params" in msg
        print(f"EXPECTED: message mentions 'params' and the stray key 'event'")
        if not (names_stray and names_params):
            print("OBSERVED: message missing expected hint content")
            ok = False
    except Exception as exc:  # pragma: no cover
        print(f"OBSERVED: unexpected exception type {type(exc).__name__}: {exc}")
        ok = False

    # 2) correctly-nested params -> parses fine
    try:
        m = create_machine(cfg(RIGHT))
        parsed = m.states["scoring"].entry[0]
        print(f"OBSERVED: correct spelling parsed -> type={parsed.type!r} params={parsed.params!r}")
    except Exception as exc:
        print(f"OBSERVED: correct spelling unexpectedly raised {type(exc).__name__}: {exc}")
        ok = False

    # 3) callable params exempt from static check
    try:
        callable_action = {"type": "raise", "params": lambda context, event: {"event": "PLACE"}}
        create_machine(cfg(callable_action))
        print("OBSERVED: callable params accepted at construction time (exempt)")
    except Exception as exc:
        print(f"OBSERVED: callable params unexpectedly raised {type(exc).__name__}: {exc}")
        ok = False

    print("RESULT:", "FIXED (build-time validation active)" if ok else "NOT FIXED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
