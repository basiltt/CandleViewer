# -*- coding: utf-8 -*-
"""R4-22: `Interpreter.from_snapshot()` has no `clock=` parameter, so a
custom/virtual clock (e.g. `SimulatedClock`) can never be restored through
any public API. `from_snapshot` constructs via `cls(machine)`, discarding
any caller-supplied clock, and every restored interpreter silently reverts
to `RealClock` -- even though `Interpreter.__init__` itself accepts
`clock=`.

Standalone, derived from battle-5e07ba8/persistence/harness.py::attach_clock
and battle-5e07ba8/determinism/d9_snapshot_replay.py.

Exits 1 (defect present) if:
  - `from_snapshot` accepts no `clock=` keyword argument at all
    (TypeError), or
  - a restored interpreter's `.clock` is a `RealClock` even though the
    original interpreter ran on a `SimulatedClock`.
Exits 0 once `from_snapshot(..., clock=...)` is supported and forwarded.
"""
from __future__ import annotations

import inspect
import json

from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.clock import RealClock, SimulatedClock

CFG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"GO": {"target": "a"}}}},
}


def main() -> int:
    sig = inspect.signature(Interpreter.from_snapshot)
    has_clock_param = "clock" in sig.parameters
    print(f"OBSERVED: from_snapshot signature = {sig}")
    print(f"OBSERVED: 'clock' accepted as a keyword parameter = {has_clock_param}")
    print(
        "EXPECTED: from_snapshot(snapshot_str, machine, *, clock=None, ...) "
        "accepts and forwards a caller-supplied clock, per "
        "Interpreter.__init__'s own clock= parameter"
    )

    m = create_machine(CFG)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock)
    snap = interp.get_persisted_snapshot()

    defect = not has_clock_param
    if has_clock_param:
        m2 = create_machine(CFG)
        restored = Interpreter.from_snapshot(
            json.dumps(snap, default=str), m2, clock=clock  # type: ignore[call-arg]
        )
        reverted = not isinstance(restored.clock, SimulatedClock)
        print(f"OBSERVED: restored.clock type = {type(restored.clock).__name__}")
        defect = reverted
    else:
        try:
            m2 = create_machine(CFG)
            restored = Interpreter.from_snapshot(
                json.dumps(snap, default=str), m2, clock=clock  # type: ignore[call-arg]
            )
            print(f"OBSERVED: unexpectedly accepted; restored.clock={type(restored.clock).__name__}")
        except TypeError as exc:
            print(f"OBSERVED: TypeError calling with clock= : {exc}")
        # fall back path used in the adopting project's harness today
        m3 = create_machine(CFG)
        restored_default = Interpreter.from_snapshot(json.dumps(snap, default=str), m3)
        print(
            f"OBSERVED: default from_snapshot() restores onto "
            f"{type(restored_default.clock).__name__} (RealClock={isinstance(restored_default.clock, RealClock)})"
        )

    print(f"\nVERDICT: no_public_clock_restore_api={defect}")
    return 1 if defect else 0


if __name__ == "__main__":
    raise SystemExit(main())
