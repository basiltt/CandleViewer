---
r4: R4-18
title: "Perf: SimulatedClock._attach() has no paired detach, leaking every restored interpreter forever"
labels: [bug, performance, severity/medium, area/timers]
severity: Medium
repro_script: repro/R4-18_simulatedclock_settler_leak.py
commit: 5e07ba8
python: 3.13.7
verified: true
---
## Summary

`SimulatedClock._attach(settle)` registers a settle callable in
`self._settlers` and there is no corresponding public (or private)
detach/unregister method anywhere in `clock.py`. Every interpreter ever
pointed at a shared `SimulatedClock` — the documented pattern for
crash-recovery / deterministic-replay against `from_snapshot()`, which
takes no `clock=` argument (see R4-22) — leaves its bound-method closure
(`interp._settle_for_clock`) alive in `_settlers` forever, even after the
interpreter is fully stopped and otherwise unreferenced. That closure
keeps the whole interpreter object graph (machine, actors, context,
plugins) reachable, and `_settle_sync`/`_settle` re-walk the ever-growing
list on every subsequent tick, so both memory and per-tick CPU grow
without bound. Filed as High in the original register row; downgraded to
Medium because the leak is scoped to the `SimulatedClock`
crash-recovery/deterministic-replay idiom (tests and replay harnesses),
not the `RealClock` production path.

## Environment

- Commit: `5e07ba8` (xstate_statemachine 0.8.1 unreleased; `__version__` reports 0.8.0)
- Python: 3.13.7, Windows 11
- Editable install of the library under a project-local venv (`.venv-main`)

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R4-18: `SimulatedClock._attach()` (clock.py) has no paired detach. Every
interpreter ever restored onto (or pointed at) a shared `SimulatedClock`
leaks forever: its `_settle_for_clock` bound method stays in
`clock._settlers`, keeping the whole interpreter object graph alive, and
`_settle_sync`/`_settle` walk the ever-growing list on every tick.

Standalone, derived from battle-5e07ba8/soak/repro_d_soak_2.py, trimmed to
run well under the time budget (20 restore cycles instead of a 25-minute
soak).

Exits 1 (defect present) if, after 20 crash/restore cycles against ONE
shared SimulatedClock and a forced `gc.collect()`, every stopped
interpreter is still reachable (not GC'able) and the clock's settler list
has grown to match. Exits 0 once a detach exists and is called on stop.
"""
from __future__ import annotations

import asyncio
import gc
import json
import weakref

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.base_interpreter import _accepts_kwarg
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"GO": {"target": "a"}}}},
}

CYCLES = 20


async def main() -> int:
    clock = SimulatedClock()
    refs = []

    m = create_machine(CFG, logic=MachineLogic())
    interp = Interpreter(m, clock=clock)
    await interp.start()
    refs.append(weakref.ref(interp))

    # This is the documented workaround pattern: from_snapshot() takes no
    # clock= argument, so callers must manually re-point interp.clock and
    # re-`_attach` the new settle callable to keep virtual time across a
    # restore (see docs/research/xstate/battle-5e07ba8/persistence/harness.py
    # ::attach_clock).
    for _ in range(CYCLES):
        snap = interp.get_persisted_snapshot()
        snap_str = json.dumps(snap, default=repr)
        await interp.stop()

        new_m = create_machine(CFG, logic=MachineLogic())
        restored = Interpreter.from_snapshot(snap_str, new_m)
        restored.clock = clock
        restored._clock_accepts_sync = _accepts_kwarg(clock.set_timeout, "sync")
        clock._attach(restored._settle_for_clock)  # the only public hook
        await restored.start()

        refs.append(weakref.ref(restored))
        interp = restored

    await interp.stop()
    gc.collect()

    alive = sum(1 for r in refs if r() is not None)
    settlers = len(clock._settlers)
    print(f"OBSERVED: settlers registered on the clock: {settlers}")
    print(f"OBSERVED: interpreters still reachable (not GC'able): {alive} / {len(refs)}")
    print(
        "EXPECTED: a stopped interpreter's settler is removed from the clock "
        "(settlers stays bounded) and the interpreter is GC'able once "
        "otherwise unreferenced"
    )

    defect = alive == len(refs) and settlers >= len(refs)
    print(f"\nVERDICT: leak_reproduced={defect}")
    return 1 if defect else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED: settlers registered on the clock: 21
OBSERVED: interpreters still reachable (not GC'able): 21 / 21
EXPECTED: a stopped interpreter's settler is removed from the clock (settlers stays bounded) and the interpreter is GC'able once otherwise unreferenced

VERDICT: leak_reproduced=True
```
(exit code 1 — defect present)

The source soak test (25 minutes, not re-run here due to the 90-second
repro-script bound; the leak mechanism and root cause were independently
re-confirmed in this pass) additionally correlated this pattern with RSS
growth from 61.8 MB to 340.6 MB and event-loop lag growing from
single-digit milliseconds to 113.7 seconds over 20 minutes of
crash/restore cycling against one shared clock.

## Expected behaviour

A settle callable registered by a now-stopped, unreferenced interpreter
should not keep that interpreter's entire object graph reachable
indefinitely, and the clock's per-tick settle cost should not grow
without bound as interpreters are restarted against it. This is the
standard observer/registry contract: registration should be paired with
an equally-public deregistration, called from the interpreter's own
teardown path (`stop()`), the same way most publish/subscribe or
listener-registry designs pair `on()`/`off()` (equivalently `addListener`/
`removeListener`) to avoid exactly this class of leak.

## Root cause analysis

- `clock.py:259` — `SimulatedClock.__init__` creates `self._settlers:
  List[Callable[[], Any]] = []`.
- `clock.py:365` (`_attach`) — appends `settle` to `self._settlers` if not
  already present (idempotent only against the identical callable
  object); **no `_detach`/`remove`/`unregister` method exists anywhere in
  `clock.py`**.
- `interpreter.py:931` (`_bind_loop`) is the sole call site:
  `if isinstance(self.clock, SimulatedClock): self.clock._attach(self._settle_for_clock)`
  — this is never balanced by a corresponding detach call in `stop()` or
  any other teardown path.
- `_settle_sync` (`clock.py:332-341`) and `_settle`
  (`clock.py:349-358`) both do `for settle in list(self._settlers): ...`
  on every timer tick, so the cost of every future `increment()`/`set()`
  call grows linearly with the number of interpreters ever attached to
  the clock, not the number currently alive.
- `_settle_for_clock` is a **bound method** of the interpreter, so each
  entry in `_settlers` strong-references `self` (the interpreter) and,
  transitively, its machine, actors, context and plugin list — nothing
  about the interpreter can be garbage-collected while its entry remains.

## Impact

For general users, any test suite or production deterministic-replay
harness that restarts/restores interpreters against one long-lived
`SimulatedClock` (exactly the pattern the library's own persistence
guidance recommends for crash-recovery testing, since `from_snapshot()`
has no `clock=` parameter — R4-22) accumulates unbounded memory and
CPU-per-tick over the life of the process. In the adopting project, this
would appear as a slow, silent leak in exactly the kind of long-running
soak/replay test the order-management persistence path needs to validate
its own crash-recovery correctness — the tool used to test resilience
itself becomes the resource leak, and CI or long-lived test workers
running many restore cycles would see growing RSS and growing per-tick
latency with no application-level explanation.

## Proposed fix

Add `SimulatedClock._detach(settle)` (mirroring `_attach`'s idempotent
`list.remove` semantics) and call it from the interpreter's `stop()` /
teardown path, symmetric with the existing `_bind_loop` call to
`_attach`. As defence in depth against a caller who forgets to detach
(or a crash that skips normal teardown), hold settlers via
`weakref.WeakMethod` instead of a strong bound-method reference, so a
dropped interpreter cannot pin its object graph through the clock even if
`_detach` is never called; `_settle_sync`/`_settle` would then simply
skip (and can opportunistically prune) any dead weak references.

## Acceptance criteria

- [ ] `SimulatedClock._detach()` exists and removes a previously-attached
      settler.
- [ ] The interpreter's `stop()` (or equivalent teardown) calls
      `_detach()` when `self.clock` is a `SimulatedClock`.
- [ ] `_settlers` no longer grows unboundedly across repeated
      restore/restart cycles against one shared clock.
- [ ] `tests/test_clock_settler_lifecycle.py::test_stopped_interpreter_is_detached_from_clock`
- [ ] `tests/test_clock_settler_lifecycle.py::test_stopped_interpreter_is_gc_able`
- [ ] `repro/R4-18_simulatedclock_settler_leak.py` exits 0

## Related

- Register source id: `D-soak-2`
- Depends on / interacts with R4-22 (`from_snapshot()` has no `clock=`
  parameter), which is why the manual `_attach` re-registration workaround
  this bug leaks through exists in the first place

## Verification

- Date: 2026-09-19; Python 3.13.7; commit `5e07ba8`.
- Re-ran `repro/R4-18_simulatedclock_settler_leak.py` in a fresh process
  (60s cap): `settlers registered on the clock: 21`, `interpreters still
  reachable: 21 / 21`, `leak_reproduced=True`; exit code `1`.
- Confirmed `src/xstate_statemachine/clock.py` has `_attach` (appends to
  `self._settlers` if not already present) with no corresponding
  `_detach`/`remove`/`unregister` method anywhere in the file; confirmed
  `_settle_sync`/`_settle` iterate `list(self._settlers)` on every tick,
  and that `_settle_for_clock` is a bound interpreter method (so each
  entry strong-references the interpreter's full object graph) —
  matching the draft's root-cause narrative.
- No external XState/SCXML claim to check (this is a Python-side
  implementation detail — `SimulatedClock` has no XState-JS analogue in
  the way the draft frames it).
- Searched `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 120 --search "clock"`: closest is #49 (feature request for
  clock injection generally, already closed/implemented) and #89 (an
  unrelated `sync=` kwarg bug); neither covers the `_attach`/no-`_detach`
  leak; no duplicate found.
- No project name/label leakage found in the file.
