---
r9: R9-07
severity: Medium
verified: true
build: f28719c
relates_to: [167, 179, 201]
labels: [bug, severity/medium, area/interpreter]
repro: new/repro/R9-07_rollback_ondone_silent_wedge.py
---

# `rollback` + `invoke.onDone` storm self-terminates below `maxIterations`, never reports `RunawayChainError`, and wedges the machine in the transient invoking state

**Severity (ours):** Medium
**Build:** `main` @ `f28719c` (merge of PR #202, unreleased 0.8.1; `__version__` still reports `0.8.0` — keyed on the commit)
**Environment:** CPython 3.13.7, Windows 11, fresh venv
**Relates to:** #167, #179, #201 — narrower than claimed: those pin the *bounded* exit from this same storm (`RunawayChainError` at the configured limit); the *other*, early exit from the identical cycle is not covered by any of the three.

---

## Summary

A `rollback` + `invoke.onDone` storm can stop **below** the configured `maxIterations` without raising `RunawayChainError`, leaving the machine parked in the **transient invoking state** — a state it was never supposed to come to rest in.

This is distinct from the bounded case, which works correctly: with the storm running to the configured limit, the plateau is exactly `maxIterations + 2` on both service spellings and `RunawayChainError` fires (we re-verified this separately and it holds at `maxIterations` 10 and 50 below). The issue here is the *other* exit from the same loop: at the shipped **default** (`maxIterations=1000`), the cycle stops on its own, well under the limit, silently.

## Root cause

The re-arm mechanism itself sits in `_finish_rollback` (`base_interpreter.py:4187-4220`): on a policy-driven rollback it restores context, discards any events the failed action queued (`_discard_raised_since`), and returns `True` so the caller swallows the exception and the state machine is left in its pre-transition configuration (`starting`, invoke still outstanding) — this is by design and correct for a single rollback.

The runaway guard that is supposed to bound *repeated* re-arms is the chain-budget check at `interpreter.py:1675-1702` (`over = self._raise_depth > limit and self_generated`, tripping `_chain_tripped = True` and raising `RunawayChainError` once `_raise_depth` exceeds `machine.max_iterations`). The self-terminating exit happens before that counter reaches the default limit of 1000: the storm's own re-arm/rollback loop, run to completion under `_finish_rollback`, exits — with `last_error` set to the entry action's own `RuntimeError` (the `boom` action's raise, propagated as the swallowed rollback cause is re-surfaced via `last_error`), not `RunawayChainError` — at a lap count that is non-deterministic across runs but consistently well under 1000 (266/27 in the attached run; the register recorded 190-252 in an earlier sampling). Because the loop's own natural termination is reached first, the chain-budget guard never gets the chance to fire, and no observable distinguishes "the storm settled" from "the storm is still one microstep from re-arming" — the machine is left in `starting` with the invoke it was mid-arming for the last, uncompleted time, and `starting` is not a state anything will ever re-enter to shake it loose.

## Impact

**General:** the failure is **observability-shaped**, and that is what makes it awkward. A caller watching for `RunawayChainError` sees nothing. A caller watching `status` sees `"running"`. The machine is parked in a state whose whole purpose is to be transient, so no `onDone`/`onError` will ever arrive to move it, and no timeout is attached because none was expected to be needed.

**Order-management:** in an order-management context, the transient invoking state is "order submitted, awaiting acknowledgement". Wedging there silently is indistinguishable, from outside, from a slow exchange — a caller has no signal to distinguish "waiting on a real, in-flight acknowledgement" from "the interpreter gave up internally and nothing is actually in flight".

## Minimal reproduction

`R9-07_rollback_ondone_silent_wedge.py` (attached; stdlib + `xstate_statemachine` only, inlined, run from a neutral cwd). `starting` --onDone--> `recording`; `recording` entry (`boom`) always raises; `actionErrorPolicy: rollback`. Runs both `def` and `async def` service spellings at `maxIterations` `DEFAULT` (1000), 10, and 50. Exits 1 if either service spelling wedges silently (final config == `[starting]`, `status` still `running`, no `RunawayChainError`) at the default limit.

## Observed (fresh run)

```
def   / DEFAULT : svc_invocations=266  final=['r7.starting']  status=running  last_error_type=RuntimeError        runaway_reported=False  wedged=True
def   / mi=10   : svc_invocations=12   final=['r7.starting']  status=running  last_error_type=RunawayChainError   runaway_reported=True   wedged=True
def   / mi=50   : svc_invocations=52   final=['r7.starting']  status=running  last_error_type=RunawayChainError   runaway_reported=True   wedged=True
async / DEFAULT : svc_invocations=27   final=['r7.starting']  status=running  last_error_type=RuntimeError        runaway_reported=False  wedged=True
async / mi=10   : svc_invocations=12   final=['r7.starting']  status=running  last_error_type=RunawayChainError   runaway_reported=True   wedged=True
async / mi=50   : svc_invocations=16   final=['r7.starting']  status=running  last_error_type=RuntimeError        runaway_reported=False  wedged=True

VERDICT: SILENT WEDGE at default maxIterations ['def', 'async']
```
Exit code: 1. (Full JSON captured in the run; the `async`/`mi=50` cell also self-terminated silently in this run, underscoring the non-determinism of exactly when the loop stops relative to any given limit.)

## Expected

`docs/_guide/production-characteristics.md` and the #201 changelog entry both describe `maxIterations` as the backstop for `rollback` + `invoke.onDone` storms: "both async lanes trip `RunawayChainError`" at the configured limit (changelog #201). Per SCXML there is no equivalent "silently give up mid-invocation" terminal state — an implementation that detects it cannot make further progress on an in-flight invocation is expected to surface that as an error, not leave the interpreter reporting `status="running"` indefinitely with no path back to observability.

## Suggested direction

Either raise on the early-termination path as well (treat "the rollback/re-arm loop exhausted itself without reaching a stable non-invoking configuration" as its own runaway condition, independent of the `_raise_depth` counter), or expose the reason the chain stopped so a caller can distinguish "settled" from "gave up". A machine coming to rest in a state with an `invoke` and no pending invocation is arguably an invariant worth asserting in the interpreter itself, since the library already knows which states are transient (they declare `invoke`) — a generic external wrapper does not have that information without duplicating the machine definition.

## Proposed fix

In `_finish_rollback` (`base_interpreter.py:4187-4220`), when the loop's own natural termination is reached (the failed action's rollback returns `True` and the machine settles back into the invoking state with no invocation actually re-armed — i.e., the invoke's onDone/onError never fires again after this rollback), raise a new, distinct exception (e.g. `RunawayChainError` with a "self-terminated: invoking state re-armed no further work" reason, or a new `StalledInvocationError`) rather than leaving `last_error` as the swallowed action's own `RuntimeError`. Alternatively, add an invariant check on `stop()`/idle-detection that flags "current state declares `invoke` but no invocation is outstanding and none will ever be re-armed" as an observable condition.

## Acceptance criteria

- `test_rollback_ondone_storm_self_terminates_raises_runaway` — parametrised over `def`/`async def` services and both `Interpreter`/`SyncInterpreter` engines (where applicable — `SyncInterpreter` does not support `async def` services; skip that cell explicitly, don't silently omit it): the attached storm at the **default** `maxIterations` either (a) raises `RunawayChainError`/an equivalent, or (b) the machine's final configuration is asserted to not be the transient invoking state with no invocation outstanding.
- `test_rollback_ondone_storm_bounded_case_still_works` (regression guard) — at `maxIterations` 10/50, the storm still raises `RunawayChainError` as it does today; the fix for the early-exit path must not regress the already-correct bounded case.
- `test_wedged_state_is_observable` — after the storm settles (by either exit), a documented API (an exception, a status flag, or a plugin hook) distinguishes "settled cleanly" from "gave up mid-invocation", so a caller does not have to poll `current_state_ids` against the machine's own invoke declarations to detect the wedge.

## Our containment

A wrapper attempt counter on every `rollback` + `invoke.onDone` state, plus an out-of-process progress check. Filed because the silent-wedge shape is hard for any wrapper to detect generically — the wrapper has to know which states are transient, which the library already knows.

## Verification

- Date: 2026-09-22
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `f28719c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- cwd used: `<home>` (neutral, outside both repos)
- Exit codes: `R9-07_rollback_ondone_silent_wedge.py` → **1** (both `def` and `async def` lanes wedged silently at the default `maxIterations`; both correctly raised `RunawayChainError` at `maxIterations=10`)
