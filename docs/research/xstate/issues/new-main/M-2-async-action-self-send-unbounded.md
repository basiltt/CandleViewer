---
lc: M-2
title: "Bug: `max_iterations` does not bound an action-side `send()` on the async engine; the #77 parity claim covers the `raise` built-in only"
labels: [bug, severity/medium, area/interpreter, docs, candleviewer]
severity: Medium
blocks_adoption: false
verified: true
status: still-present
retested_on: main@3c527b0 (2026-09-18, after PR #83)
repro_script: new-main/repro/c14_async_no_send_budget.py
library_version: main@3c527b0
python: 3.13.7
found_by: main @ 5327ba6 adversarial verification (21-verify-main-adversarial.md M-2)
related_issue: "#77"
---

## Summary

The `[Unreleased]` #77 entry says the budget counts *"events that arrive while
the drain is running (a `raise`, **an action calling `send()` on its own
interpreter**, a `done.invoke` from a sync service, a due timer)"*, and that the
engines *"agree now, and an engine-parity test pins it"*.

For the `raise` built-in they do agree. For the **action-side `send()`** shape
they do not: the async `Interpreter` has no budget for it at all and spins
forever.

This is not a new code regression — 0.8.0 had the same hole. What is new is the
CHANGELOG asserting it is closed, and the parity test pinning only the `raise`
shape.

## Environment

- Library: `xstate-statemachine`, local clone, `main` @ commit
  `5327ba69fb735cfe24c7b3772050dac0a71a7b3d`, `pip install -e .`
- Python: 3.13.7 (CPython) · Windows 11 x64 (10.0.26200)

## Minimal reproduction

An unconditional `i.send("LOOP")` inside the `LOOP` handler, on a machine with
`maxIterations: 1000`, run on each engine. Full script:
`repro/c14_async_no_send_budget.py` (asserts the current behaviour; exits 0).

## Observed

```
machine.max_iterations = 1000
SYNC : send() returned. steps = 1001
ASYNC: after 2.0 s of spinning, steps = 83888   status = running
ASYNC: after 3.0 s, steps = 125672  (still climbing: True)
ASYNC: queue_depth = 0
```

| Engine | Unconditional `i.send("LOOP")` inside the `LOOP` handler |
|---|---|
| `SyncInterpreter` | guard fires, `send()` returns after 1 001 steps |
| `Interpreter` (async) | **spins forever** |

## Cause

The async `send()` routes an action's self-`send()` to the **external** inbox —
it only diverts to `_internal_queue` under `OverflowPolicy.BLOCK` with a bound
set — so `_raise_depth` never counts it.

The result is a pegged run loop with `status == "running"` and
`queue_depth == 0`: invisible to every liveness signal the library offers. No
hook fires, `last_transition_ok` stays `True`, and the only external symptom is
a busy CPU.

## Expected

Either:

- **(preferred)** the async engine counts an action-originated `send()` against
  the same per-chain budget the sync engine applies, so the two genuinely
  agree; or
- the CHANGELOG and the `maxIterations` docs state plainly that the budget
  bounds the `raise` built-in only, and that an action calling `send()` on its
  own interpreter is unbounded on the async engine — with a recommendation to
  use `raise` for self-directed events.

The parity test should be extended either way, so it pins whichever contract is
chosen rather than the `raise` shape alone.

## Acceptance criteria

1. `repro/c14_async_no_send_budget.py`, inverted to assert boundedness, exits 0
   on both engines — or the docs change lands and the repro is repurposed as a
   documentation example.
2. `test_async_action_self_send_is_bounded` (or
   `test_action_self_send_is_documented_unbounded`) exists and pins the chosen
   contract.
3. The existing engine-parity test is extended beyond the `raise` built-in.
4. If the budget is added: `status` / a hook / a counter makes the cut
   observable, rather than silently stopping generation (same gap as `#77`'s
   silent overflow).


---

## Re-test on `main@3c527b0` (2026-09-18, after PR #83)

**Status: STILL-PRESENT.** PR #83 (`2459c82`: ErrorEvent #80, provenance
system events #79, one-task-per-child #43) does not touch this code path.
Repro re-run on `3c527b0` with the same interpreter and environment.

```
$ python repro/c14_async_no_send_budget.py
machine.max_iterations = 1000

SYNC : send() returned. steps = 1001
ASYNC: after 2.0 s of spinning, steps = 77342  status = running
ASYNC: after 3.0 s, steps = 112486  (still climbing: True)
ASYNC: queue_depth = 0
```

See `../../23-verify-3c527b0-findings.md` for the full re-test table.
