---
r4: R4-29
title: "Bug: SyncInterpreter.start() emits a synthetic init on_transition hook the async engine never emits"
labels: [bug, severity/medium, area/interpreter, area/sync-interpreter, area/observability]
severity: Medium
repro_script: repro/R4-29_sync_start_synthetic_init_hook.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`SyncInterpreter.start()` fires a synthetic init `on_transition` hook record
(for the internal event `___xstate_statemachine_init___`) through the
plugin/hook path. `Interpreter.start()` has no equivalent — it does not
emit any `on_transition` record for entering the initial configuration. As a
result, a hook-based audit trace built from `on_transition` records always
has one extra leading record on the sync engine, at a fixed index (0), for
otherwise identical machines and event sequences. This is a constant,
deterministic offset rather than run-to-run instability, but it means naive
byte-for-byte (or record-for-record) comparison of the two engines' audit
trails is never valid without special-casing index 0.

## Environment

- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Install: editable clone at `_ref/xstate-statemachine`, run via its
  `.venv-main` interpreter

## Minimal reproduction

```python
"""R4-29: SyncInterpreter.start() fires a synthetic init `on_transition` hook
record (sync_interpreter.py:336-339) that the async engine's start() never
emits (interpreter.py). Any hook-based audit trace diffed across engines
therefore mismatches at index 0 always -- a fixed constant offset, not
run-to-run instability.

Exits 1 while the sync trace has a leading transition record for the
synthetic init event `___xstate_statemachine_init___` that has no
counterpart in the async trace.
"""
from __future__ import annotations

import asyncio
import logging
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "h",
    "initial": "a",
    "context": {},
    "states": {"a": {"entry": ["ea"], "on": {"GO": "b"}}, "b": {"entry": ["eb"]}},
}


class All(PluginBase):
    def __init__(self, t):
        self.t = t

    def on_transition(self, i, f, to, tr):
        self.t.append(("transition", tr.event, tuple(sorted(s.id for s in f)), tuple(sorted(s.id for s in to))))


def mk():
    return create_machine(
        CFG,
        logic=MachineLogic(actions={"ea": lambda i, c, e, a: None, "eb": lambda i, c, e, a: None}),
    )


async def a_trace():
    t = []
    i = Interpreter(mk())
    i.use(All(t))
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.05)
    await i.stop()
    return t


def s_trace():
    t = []
    i = SyncInterpreter(mk())
    i.use(All(t))
    i.start()
    i.send("GO")
    i.stop()
    return t


if __name__ == "__main__":
    a = asyncio.run(a_trace())
    s = s_trace()
    print("OBSERVED sync trace  :", s)
    print("OBSERVED async trace :", a)
    print("EXPECTED: sync[0] == async[0] (both emit, or neither emits, the init transition)")
    sync_only_init = bool(s) and s[0][1] == "___xstate_statemachine_init___" and (not a or a[0] != s[0])
    if sync_only_init:
        print("FAIL: sync-only leading synthetic init transition record; traces diverge at index 0")
        sys.exit(1)
    print("PASS: no sync-only leading init record")
    sys.exit(0)
```

## Observed behaviour

```
OBSERVED sync trace  : [('transition', '___xstate_statemachine_init___', (), ('h', 'h.a')), ('transition', 'GO', ('h', 'h.a'), ('h', 'h.b'))]
OBSERVED async trace : [('transition', 'GO', ('h', 'h.a'), ('h', 'h.b'))]
EXPECTED: sync[0] == async[0] (both emit, or neither emits, the init transition)
FAIL: sync-only leading synthetic init transition record; traces diverge at index 0
```

## Expected behaviour

Two engines that expose the same plugin/hook API for auditing purposes
should produce structurally comparable `on_transition` traces for the same
machine and event sequence: either both engines emit a transition record
for entering the initial configuration, or neither does. Emitting the
initial configuration in the trace is arguably the more useful choice, since
otherwise there is no `on_transition` record showing which state(s) the
machine started in.

## Root cause analysis

- `sync_interpreter.py:336-339` — `SyncInterpreter.start()` fires the
  synthetic init transition (event `___xstate_statemachine_init___`, `from=
  ()`, `to=<initial states>`) through the plugin/hook path, including
  `on_transition`.
- `interpreter.py`'s `start()` has no equivalent call — it enters the initial
  configuration without emitting any `on_transition` record for it.

## Impact

Any hook-based audit/trace log — the library's documented mechanism for
externally observing machine behavior — built by diffing or comparing
records across engines mismatches at index 0, always, for every machine and
every event sequence. This is a fixed constant offset (not intermittent),
so it is straightforward to work around once known, but it means a naive
cross-engine trace-reconciliation check (e.g. verifying a migration from one
engine to the other produced an identical audit trail) cannot be used
without a special case for the leading record.

## Proposed fix

Pick one behavior and apply it to both engines. Emitting the initial
transition on both engines is the more useful choice — add the equivalent
synthetic init `on_transition` call to `Interpreter.start()` in
`interpreter.py`, matching `sync_interpreter.py:336-339`'s event name and
`from=()`/`to=<initial states>` shape.

## Acceptance criteria

- [ ] `Interpreter.start()` and `SyncInterpreter.start()` emit the same
      `on_transition` behavior at index 0 (both emit the synthetic init
      record, or neither does).
- [ ] A test named `test_sync_async_init_transition_hook_parity` (or
      equivalent) exists under `tests/`.
- [ ] `repro/R4-29_sync_start_synthetic_init_hook.py` exits 0 once fixed.

## Related

- Register row R4-29 (filed Medium, stands as filed on re-triage).
- Source: `battle-5e07ba8/determinism/d7_hook_parity.py`.

## Verification

- Date: 2026-09-19
- Python: `.venv-main` interpreter, version 3.13.7
- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-29_sync_start_synthetic_init_hook.py` fresh, standalone:
  exit code `1`, output matched the Observed section verbatim (sync trace
  has a leading `('transition', '___xstate_statemachine_init___', (),
  ('h', 'h.a'))` record; async trace does not).
- Confirmed root cause: `sync_interpreter.py:336-339`'s `start()` method
  calls `plugin.on_transition(self, pre_states, post_states,
  initial_transition)` for every plugin after processing transient
  transitions on startup. `Interpreter.start()` in `interpreter.py` has no
  equivalent call anywhere in its startup path — confirmed by inspection;
  no `on_transition` invocation exists for the initial configuration on the
  async engine.
- This finding is an engine-parity/observability claim about the library's
  own plugin/hook API and audit-trace format, not an external XState/SCXML
  semantics claim, so no external URL fetch applies (XState's own
  `@xstate.microstep`/inspection API is a distinct mechanism not directly
  comparable to this library's `on_transition` hook).
- No project name/label leak found. No duplicate found; `gh issue list`
  search for "init transition" surfaced no issue addressing a synthetic
  init `on_transition` record or hook-trace parity at index 0 between
  engines.
