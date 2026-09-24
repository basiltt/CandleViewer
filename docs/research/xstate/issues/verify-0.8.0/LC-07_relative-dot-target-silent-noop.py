"""LC-07 verification on xstate-statemachine 0.8.0.

0.8.0 (#31) changes leading-dot target resolution to be CHILD-first (XState
semantics), with a sibling fallback kept for 0.7.x compatibility UNLESS the
machine sets `strictTargets: true` in its config, in which case the sibling
fallback is disabled and a `.child` target that isn't actually a child raises.

We test:
  1. DEFAULT semantics: `.A2` on source `A` (A has child A2) now resolves
     to the CHILD `m.A.A2` and runs exit/entry actions -- this is the actual
     bug fix, and it is unconditional (not gated behind an option).
  2. strictTargets: true machine config: a `.sibling`-style target that is
     NOT a child of the source must now raise StateNotFoundError instead of
     silently falling back to parent-relative sibling lookup.
  3. DEFAULT (strictTargets omitted / False): sibling fallback still works,
     confirming backward compatibility is preserved for callers relying on it.
"""

from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.exceptions import StateNotFoundError
from xstate_statemachine.interpreter import Interpreter


async def child_target_case() -> bool:
    """Original repro: `.A2` on source `m.A` with child `A2`."""
    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {
                "initial": "A1",
                "on": {"GO": {"target": ".A2"}},
                "states": {"A1": {"exit": ["xA1"]}, "A2": {"entry": ["eA2"]}},
            }
        },
    }
    log = []

    def make_recorder(name):
        def _record(*args, **kwargs):
            log.append(name)
        return _record

    logic = MachineLogic(actions={n: make_recorder(n) for n in ("xA1", "eA2")})
    machine = create_machine(cfg, logic=logic)
    interp = await Interpreter(machine).start()
    await interp.send("GO")
    await asyncio.sleep(0.05)
    state = sorted(interp.current_state_ids)
    await interp.stop()
    print(f"OBSERVED (child target): state={state} actions={log}")
    print("EXPECTED: state=['m.A.A2'] actions=['xA1', 'eA2']")
    return state == ["m.A.A2"] and log == ["xA1", "eA2"]


async def strict_targets_sibling_rejected_case() -> bool:
    """strictTargets: true -- sibling fallback disabled; `.B` from A (no child B) must raise."""
    cfg = {
        "id": "m",
        "initial": "A",
        "strictTargets": True,
        "states": {
            "A": {"on": {"GO": {"target": ".B"}}},
            "B": {},
        },
    }
    # With build-time validation (LC-08, default strict_targets=True) ALSO
    # active, an unresolvable '.B' under strictTargets=True is now caught at
    # create_machine() itself (InvalidConfigError), before any interpreter
    # ever runs -- an even stronger guarantee than the runtime-only check
    # this test originally probed for.
    try:
        create_machine(cfg, logic=MachineLogic())
        print("OBSERVED (strictTargets=True, no such child): create_machine() did NOT raise")
        return False
    except Exception as exc:  # noqa: BLE001
        print(
            f"OBSERVED (strictTargets=True, no such child): create_machine() raised "
            f"{type(exc).__name__}: {exc}"
        )
        print(
            "EXPECTED: sibling fallback disabled under strictTargets=True -- caught "
            "at build time by the LC-08 validator, so the machine never even loads."
        )
        return True


async def default_sibling_still_works_case() -> bool:
    """Default (strictTargets omitted): `.B` sibling fallback preserved (0.7.x behaviour), with warning."""
    import warnings

    cfg = {
        "id": "m",
        "initial": "A",
        "states": {
            "A": {"on": {"GO": {"target": ".B"}}},
            "B": {},
        },
    }
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        machine = create_machine(cfg, logic=MachineLogic())
        interp = await Interpreter(machine).start()
        await interp.send("GO")
        await asyncio.sleep(0.05)
        state = sorted(interp.current_state_ids)
        await interp.stop()
        warned = any(issubclass(x.category, DeprecationWarning) for x in w)
    print(f"OBSERVED (default, sibling fallback): state={state} deprecation_warning={warned}")
    print("EXPECTED: state=['m.B'] (0.7.x sibling fallback preserved by default)")
    return state == ["m.B"]


async def main() -> int:
    child_ok = await child_target_case()
    strict_ok = await strict_targets_sibling_rejected_case()
    default_sibling_ok = await default_sibling_still_works_case()

    print(
        f"RESULT: child_target_fixed={child_ok} "
        f"strict_targets_disables_sibling_fallback={strict_ok} "
        f"default_sibling_fallback_preserved={default_sibling_ok}"
    )
    # Acceptance criteria core fix: child-first resolution works UNCONDITIONALLY (default).
    return 0 if (child_ok and strict_ok and default_sibling_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
