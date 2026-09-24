---
lc: F-6
title: "Bug: a `done.invoke` from a sync service is classed as self-generated; after a trip the completion is dropped and the machine parks in the invoking state (#77)"
labels: [bug, severity/medium, area/sync-interpreter, candleviewer]
severity: Medium
blocks_adoption: false
verified: true
status: still-present
retested_on: main@3c527b0 (2026-09-18, after PR #83)
repro_script: new-main/repro/f_sticky_invoke.py
library_version: main@3c527b0
python: 3.13.7
found_by: main @ 5327ba6 diff review (19-verify-main-diff-review.md F-6)
related_issue: "#77; companion to the sticky `tripped` flag report"
---

## Summary

The #77 budget explicitly classes *"a `done.invoke` from a sync service"* as
self-generated work counting against the budget
(`sync_interpreter.py:594-600`). Combined with the sticky `tripped` flag (filed
separately), a **service completion that arrives after an unrelated trip is
discarded**, and the machine parks permanently in the invoking state.

The service **ran**; its `onDone` transition never fires. This is a silent hang
— precisely the failure class the dead-loop validator exists to prevent,
reintroduced at runtime.

## Environment

- Library: `xstate-statemachine`, local clone, `main` @ commit
  `5327ba69fb735cfe24c7b3772050dac0a71a7b3d`, `pip install -e .`
- Python: 3.13.7 (CPython) · Windows 11 x64 (10.0.26200)

## Location

`src/xstate_statemachine/sync_interpreter.py:594-600` (classification) and
`:636-655` / `:672-684` (sticky trip; see the companion report).

## Minimal reproduction

`SPIN` trips a `maxIterations: 20` budget; then `GO` enters a state invoking a
trivially-returning sync service. Full script: `repro/f_sticky_invoke.py`.

## Observed

```
state: {'m.work'}   (expected m.done)
```

The machine is parked in `m.work` forever. `status` stays `"running"`,
`last_transition_ok` stays `True`, no hook fires.

## Related inconsistency

Due `after` timers are **not** affected in the same way
(`repro/f_sticky_timer.py` correctly reaches `m.done`), because `_pump_timers`
re-appends on each loop iteration and the state is reached before the budget
check bites. Two sources the budget classes identically behave differently —
the classification is coarser than its enforcement.

## Expected

A service completion is not runaway work. `done.invoke` (and `error.platform`)
delivery is driven by an external computation that has already finished; it
cannot self-feed, and dropping it strands the machine.

Either exempt engine-synthesised completion events from the budget entirely, or
— if they must be counted — never drop one: a budget that discards a
`done.invoke` converts a bounded-work guarantee into a permanent hang, which is
strictly worse than the runaway it prevents.

Fixing the sticky-flag report alone narrows this but does not close it: a long
enough legitimate chain inside one drain can still consume the budget before
the completion arrives.

## Acceptance criteria

1. `repro/f_sticky_invoke.py` exits 0 — the machine reaches `m.done`.
2. A `done.invoke` / `error.platform.*` event is never discarded by the runaway
   guard, on either engine.
3. `repro/f_sticky_timer.py` still reaches `m.done` (no regression), and due
   timers and service completions are treated consistently.
4. A genuine self-feeding loop is still bounded.
5. Tests: `test_done_invoke_survives_runaway_trip`,
   `test_timer_and_invoke_completion_treated_consistently_under_budget`.


---

## Re-test on `main@3c527b0` (2026-09-18, after PR #83)

**Status: STILL-PRESENT.** PR #83 touches `sync_interpreter.py` only for the `ErrorEvent` / provenance
plumbing (#79, #80); the self-generated classification of `done.invoke` is
unchanged.
Repro re-run on `3c527b0` with the same interpreter and environment.

```
$ python repro/f_sticky_invoke.py
state: {'m.work'} (expected m.done)
```

See `../../23-verify-3c527b0-findings.md` for the full re-test table.
