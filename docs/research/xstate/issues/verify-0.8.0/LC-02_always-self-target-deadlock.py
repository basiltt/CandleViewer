"""LC-02 verification on xstate-statemachine 0.8.0.

Issue: an `always` transition with a self-target deadlocked silently (no
config-time diagnostic). 0.8.0 fix: build-time validation in
`create_machine()`/`validate_machine()` rejects a non-progressing `always`
self-target with `InvalidConfigError`, naming the offending state. The
`internal` (XState v4) key is also honoured as an alias for `reenter`
instead of being silently dropped.

This is a build-time VALIDATION fix (like LC-08/LC-36), not a runtime
policy, so this script asserts the specific exception is raised.

Checks:
  1. SELF_LOOP (always self-target, no reenter): create_machine() raises
     InvalidConfigError naming state 'loop'.
  2. REENTER (always self-target WITH reenter: True): create_machine()
     succeeds (no false positive) and the machine converges.
  3. VIA_B (always through a distinct intermediate state): create_machine()
     succeeds (no false positive) and converges.
  4. INTERNAL_FALSE (`internal: False` alias for v4 migrators): no longer
     silently dropped -- since internal:False == reenter:True, this must
     now behave identically to REENTER (build succeeds, converges) rather
     than silently parking.

Exit 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import InvalidConfigError, MachineLogic, create_machine

logging.disable(logging.CRITICAL)


def make_logic():
    def inc(i, c, e, a):
        c["n"] += 1

    return MachineLogic(
        actions={"inc": inc}, guards={"enough": lambda c, e: c["n"] >= 3}
    )


SELF_LOOP = {
    "id": "m",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "loop"}},
        "loop": {
            "entry": ["inc"],
            "always": [{"target": "done", "guard": "enough"}, {"target": "loop"}],
        },
        "done": {},
    },
}

REENTER = {
    "id": "m",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "loop"}},
        "loop": {
            "entry": ["inc"],
            "always": [
                {"target": "done", "guard": "enough"},
                {"target": "loop", "reenter": True},
            ],
        },
        "done": {},
    },
}

VIA_B = {
    "id": "m",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "A"}},
        "A": {
            "entry": ["inc"],
            "always": [{"target": "done", "guard": "enough"}, {"target": "B"}],
        },
        "B": {"always": {"target": "A"}},
        "done": {},
    },
}

INTERNAL_FALSE = {
    "id": "m",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "loop"}},
        "loop": {
            "entry": ["inc"],
            "always": [
                {"target": "done", "guard": "enough"},
                {"target": "loop", "internal": False},
            ],
        },
        "done": {},
    },
}


async def run_converges(cfg) -> str:
    from xstate_statemachine import Interpreter

    interp = Interpreter(create_machine(cfg, logic=make_logic()))
    await interp.start()
    await interp.send("GO")
    await asyncio.sleep(0.2)
    state = sorted(interp.current_state_ids)
    await interp.stop()
    return state


def check_self_loop_rejected() -> bool:
    try:
        create_machine(SELF_LOOP, logic=make_logic())
        print("SELF_LOOP OBSERVED: no exception raised (BUG STILL PRESENT)")
        return False
    except InvalidConfigError as exc:
        msg = str(exc)
        print("SELF_LOOP OBSERVED: InvalidConfigError:", msg)
        ok = "loop" in msg
        print("SELF_LOOP EXPECTED: InvalidConfigError naming state 'loop'")
        return ok
    except Exception as exc:  # noqa: BLE001
        print("SELF_LOOP OBSERVED: wrong exception type:", type(exc).__name__)
        return False


def check_no_false_positive(name: str, cfg) -> bool:
    try:
        create_machine(cfg, logic=make_logic())
        state = asyncio.run(run_converges(cfg))
        print(f"{name} OBSERVED: build ok, converged to {state}")
        return state == ["m.done"]
    except InvalidConfigError as exc:
        print(f"{name} OBSERVED: unexpectedly rejected: {exc}")
        return False


def main() -> int:
    r1 = check_self_loop_rejected()
    r2 = check_no_false_positive("REENTER", REENTER)
    r3 = check_no_false_positive("VIA_B", VIA_B)
    r4 = check_no_false_positive("INTERNAL_FALSE", INTERNAL_FALSE)

    all_ok = r1 and r2 and r3 and r4
    print(
        "RESULT:",
        "FIXED-DEFAULT (build-time validation, always on unless strict_targets=False escape hatch not applicable here)"
        if all_ok
        else "NOT-FIXED/PARTIAL",
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
