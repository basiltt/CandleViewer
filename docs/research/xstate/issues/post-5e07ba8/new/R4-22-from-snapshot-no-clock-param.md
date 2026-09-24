---
r4: R4-22
title: "Feature: from_snapshot() has no clock= parameter, so a custom clock cannot be restored"
labels: [enhancement, severity/medium, area/timers, area/persistence]
severity: Medium
repro_script: repro/R4-22_from_snapshot_no_clock_param.py
commit: 5e07ba8
python: 3.13.7
verified: true
---
## Summary

`Interpreter.from_snapshot()` / `SyncInterpreter.from_snapshot()` construct
the restored instance via `cls(machine)`, which always uses the default
`clock=` (i.e. `RealClock`), and there is no `clock=` keyword parameter on
`from_snapshot` for a caller to override this — even though
`Interpreter.__init__` itself happily accepts `clock=`. Any deterministic
or virtual-time workflow (a `SimulatedClock`-based deterministic replay
harness, or any custom `Clock` implementation used in production) is
silently reverted to wall-clock time on every restore, and the only way
to recover the intended clock is private-attribute surgery on the
restored instance after the fact.

## Environment

- Commit: `5e07ba8` (xstate_statemachine 0.8.1 unreleased; `__version__` reports 0.8.0)
- Python: 3.13.7, Windows 11
- Editable install of the library under a project-local venv (`.venv-main`)

## Current behaviour and why it is insufficient

```python
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
```

Output:

```
OBSERVED: from_snapshot signature = (snapshot_str: str, machine: xstate_statemachine.models.MachineNode[typing.Any], *, verify_machine_hash: bool = True, restart_services: bool = False) -> ~TInterpreter
OBSERVED: 'clock' accepted as a keyword parameter = False
EXPECTED: from_snapshot(snapshot_str, machine, *, clock=None, ...) accepts and forwards a caller-supplied clock, per Interpreter.__init__'s own clock= parameter
OBSERVED: TypeError calling with clock= : BaseInterpreter.from_snapshot() got an unexpected keyword argument 'clock'
OBSERVED: default from_snapshot() restores onto RealClock (RealClock=True)

VERDICT: no_public_clock_restore_api=True
```
(exit code 1 — capability missing)

This confirms both: `from_snapshot` has no `clock=` parameter at all
(a `TypeError` on the attempted call), and its default behaviour always
produces a `RealClock`-backed interpreter regardless of what clock the
original interpreter used.

## Expected behaviour

`Interpreter.__init__(self, machine, *, clock=None, ...)` already accepts
an injectable clock as its documented mechanism for deterministic-time
testing and virtual-time replay. Since `from_snapshot()` is the other
half of the same interpreter lifecycle (construct-then-restore is meant
to be equivalent to a freshly-constructed-and-driven interpreter, modulo
state), it should expose the same injection point:
`from_snapshot(snapshot_str, machine, *, clock=None, verify_machine_hash=True, restart_services=False)`,
forwarding `clock` to `cls(machine, clock=clock)` (or leaving it `None` to
fall back to the current default) so that a caller who ran the original
interpreter on a `SimulatedClock` — or any custom `Clock` implementation
used in production — can restore onto the same kind of clock through the
public API, without private-attribute access.

## Root cause analysis

- `base_interpreter.py:1103-1110` — `from_snapshot`'s signature is
  `(cls, snapshot_str, machine, *, verify_machine_hash=True,
  restart_services=False)`; there is no `clock` parameter.
- `base_interpreter.py:1188` — `interpreter = cls(machine)` constructs the
  new instance with no clock argument, so it always falls through to
  `Interpreter.__init__`'s default (`RealClock`).
- The persisted snapshot itself only stores a wall-clock `taken_at`
  timestamp (no clock identity/kind), so even if a clock were passed in,
  there is no serialized signal for `from_snapshot` to auto-select one —
  the caller must always supply it explicitly, which is exactly why a
  `clock=` parameter (rather than snapshot-embedded clock state) is the
  right shape for the fix.
- The library's own test/battle harness had to work around this by
  reaching into `interp.clock`, `interp._clock_accepts_sync`
  (`base_interpreter._accepts_kwarg`), and `clock._attach(...)` directly
  post-construction (`battle-5e07ba8/persistence/harness.py::attach_clock`),
  which the harness's own docstring flags as private-attribute surgery
  that is "the only way to do it".

## Proposed API/text

Add a `clock: Optional[Clock] = None` keyword-only parameter to
`from_snapshot()` on `BaseInterpreter` (shared by both `Interpreter` and
`SyncInterpreter`), forwarded to `cls(machine, clock=clock)` when
constructing the restored instance (falling back to the class default
when `None`, preserving current behaviour for existing callers). Update
the `from_snapshot` docstring's persistence-guide section to document
`clock=` alongside `restart_services=` and `verify_machine_hash=`, and
note that `SimulatedClock`-based deterministic-replay callers should
always pass their existing clock instance to preserve virtual time across
a restore. This closes the private-attribute workaround entirely — no
`_attach`/`_accepts_kwarg` reach-through is needed once the constructor
argument exists.

## Acceptance criteria

- [ ] `from_snapshot(snapshot_str, machine, *, clock=None, ...)` accepts a
      `clock` keyword argument on both `Interpreter` and
      `SyncInterpreter`.
- [ ] Passing `clock=some_simulated_clock` results in
      `restored.clock is some_simulated_clock`.
- [ ] Omitting `clock=` preserves current default behaviour (no
      regression).
- [ ] `tests/test_persistence_clock.py::test_from_snapshot_accepts_clock_param`
- [ ] `tests/test_persistence_clock.py::test_from_snapshot_default_clock_unchanged`
- [ ] `repro/R4-22_from_snapshot_no_clock_param.py` exits 0

## Related

- Register source ids: `D-persistence-1`, `D-determinism-5`
- Enables removal of the private-attribute `attach_clock()` workaround in
  the adopting project's own test harness
  (`battle-5e07ba8/persistence/harness.py`)
- Directly related to R4-18 (`SimulatedClock` settler leak): the manual
  `clock._attach()` re-registration this feature gap forces callers to
  perform is the same call site that leaks

## Verification

- Date: 2026-09-19; Python 3.13.7; commit `5e07ba8`.
- Re-ran `repro/R4-22_from_snapshot_no_clock_param.py` in a fresh process
  (60s cap): output matched the Observed block verbatim (`'clock' accepted
  as a keyword parameter = False`, `TypeError` when passed anyway,
  default restore always onto `RealClock`); exit code `1` (missing
  capability, confirmed absent).
- Confirmed `src/xstate_statemachine/base_interpreter.py:1102-1110`
  (`from_snapshot` signature has no `clock` parameter) and `:1187`
  (`interpreter = cls(machine)`, no clock forwarded) — matching the
  draft's cited lines exactly. Confirmed `Interpreter.__init__` does
  accept `clock=` as documented.
- No external XState/SCXML claim requiring a fetch here (this is a
  Python-library-specific API-symmetry gap between `__init__` and
  `from_snapshot`, not an XState/SCXML spec question).
- Searched `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 120 --search "clock"`: #49 (clock injection exists, already
  closed) covers `__init__`-time injection generally but not
  `from_snapshot`'s missing parameter specifically; no duplicate found.
- No project name/label leakage found in the file.
