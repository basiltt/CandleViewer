---
r9: R9-08
severity: Medium
verified: true
build: f28719c
relates_to: [197, 182]
labels: [bug, severity/medium, area/interpreter, events]
repro: new/repro/R9-08_send_wait_resolves_over_empty_configuration.py
---

# `await send(EV, wait=True)` resolves with `last_transition_ok=True` at an instant where `current_state_ids == []`

**Severity (ours):** Medium
**Build:** `main` @ `f28719c` (merge of PR #202, unreleased 0.8.1; `__version__` still reports `0.8.0` — keyed on the commit)
**Environment:** CPython 3.13.7, Windows 11, fresh venv
**Relates to:** #197 — this is its residual: the persistence-side torn-window check landed and is solid, but the receipt-side check for the same window was not added.

---

## Summary

#197's pinned property test passes, and `get_persisted_snapshot()` correctly refuses at the torn instant — so nothing inconsistent can be **persisted**. That is the important half and it is solid.

But the originally reported chart still reproduces: an `always` + nested-final + `after` chart returns a **success-shaped receipt** over an empty configuration.

## The evidence, and why it points at its own fix

From the attached repro, the async/`async def` cell at lap 0:

```json
{
  "lap": 0,
  "ok": true,
  "err": "None",
  "status": "running",
  "snap": "REFUSED:SnapshotMidStepError"
}
```

Read those last two lines together. **At the very same instant, `send(wait=True)` reports success and `get_persisted_snapshot()` refuses as mid-step.** The engine already knows the configuration is not settled — the mid-step flag is set and is being honoured by the persistence path. The receipt path simply does not consult it.

## Root cause

`get_persisted_snapshot()` (`base_interpreter.py:1359-1408`) checks `_step_in_flight()` (line 1307-1312, `getattr(self, "_processing", False) or getattr(self, "_is_processing", False)`) and raises `SnapshotMidStepError` when true — this is the #197/#182 in-flight guard, and it is correct and unconditional.

The receipt path never asks the equivalent question. `_resolve_receipt` (`interpreter.py:1063-1078`) builds the `Receipt` unconditionally from `frozenset(self.current_state_ids)` at the moment it is called, with no check against `_step_in_flight()` or `_configuration_is_legal()` (defined at `base_interpreter.py:1314`, used by the snapshot path but not here). Because a nested-final completion inside an `always`/`after` chain can call `_resolve_receipt` from a point in the macrostep chain where the configuration is transiently empty (between the final-state exit and the next transition's entry), the receipt is built and resolved with `changed=True`/no error at that exact instant, while `current_state_ids` reads `[]`.

## Impact

**General:** a caller who reads `current_state_ids` off a successful `send(wait=True)` receipt — the documented, ergonomic way to get "where did we land after this event" without a second round-trip — can observe an empty configuration at the instant the receipt says the transition succeeded. A caller who instead persists (`get_persisted_snapshot()`) is protected; a caller who trusts the receipt's own state view is not.

**Order-management:** a control loop that reads the receipt to decide "what state is the order in now" (rather than immediately re-querying `current_state_ids` or persisting) could act on an empty configuration read as if it were a real state, or silently skip processing because no leaf id matched anything expected — a class of bug that only surfaces on the same nested-final/`after`-chain shape #197 originally found.

## Minimal reproduction

`R9-08_send_wait_resolves_over_empty_configuration.py` (attached; stdlib + `xstate_statemachine` only, run from a neutral cwd). Matrix: {`def`, `async def`} service × {`Interpreter`, `SyncInterpreter`} engine. Chart: `always`-driven descent into a nested-final state under an `invoke`, plus a top-level `after` sibling — the same shape #197 pinned. For each of 25 laps, sends `GO, GO, PING, NOPE` with `wait=True` and checks whether `current_state_ids` was ever empty at receipt-resolution time; if so, cross-checks `get_persisted_snapshot()` at that same instant. Exits 1 on a success-shaped receipt (`last_transition_ok=True`, `last_error is None`) coinciding with an empty configuration.

## Observed (fresh run)

```json
{
  "rows": [
    {"engine": "async", "service": "def",   "laps": 25, "empty_hits": 0, "violation": null},
    {"engine": "async", "service": "async", "laps": 25, "empty_hits": 1,
     "violation": {"lap": 0, "ok": true, "err": "None", "status": "running", "snap": "REFUSED:SnapshotMidStepError"}},
    {"engine": "sync",  "service": "def",   "laps": 25, "empty_hits": 0}
  ],
  "failures": [
    "async/async: success-shaped receipt over empty configuration at lap 0: {'lap': 0, 'ok': True, 'err': 'None', 'status': 'running', 'snap': 'REFUSED:SnapshotMidStepError'}"
  ]
}
```
Exit code: 1. Sync cells are clean by construction (`empty_hits: 0`) — `send()` cannot return mid-step on `SyncInterpreter`, since it drains synchronously to a settled configuration before returning.

## Expected

Per the library's own contract, a `Receipt` is meant to describe a settled outcome: #182/#197 established (and #197's own test pins) that `current_state_ids == []` at any point observable via `get_persisted_snapshot()` is refused as `SnapshotMidStepError` precisely because an empty configuration is illegal per `_configuration_is_legal()` (`base_interpreter.py:1314-1329`, SCXML configuration legality — "An empty configuration is illegal"). The receipt path is not exempt from that same illegality; XState v5's actor `send`/inspection model likewise never surfaces an intermediate, empty snapshot as a settled result of an event.

## Suggested direction

Refuse (or at least withhold `last_transition_ok=True`) wherever `get_persisted_snapshot()` would refuse. The condition is already computed, already correct, and already used two call sites away — this makes the fix low-risk: reuse `_step_in_flight()` / `_configuration_is_legal()` at the point `_resolve_receipt` is invoked, or defer resolution until the chain has genuinely settled.

## Proposed fix

In `_resolve_receipt` (`interpreter.py:1063-1078`), before constructing the `Receipt`, check `not self._configuration_is_legal()` (or `self._step_in_flight()`); if true, do not resolve with the current (torn) `current_state_ids` — either defer resolution to the next point the configuration is legal (attach a completion callback rather than resolving immediately), or resolve with an explicit `deferred=True`/torn-state marker so the caller can distinguish it from a genuinely settled receipt, matching the guard already enforced identically by `get_persisted_snapshot()`.

## Acceptance criteria

- `test_send_wait_never_resolves_success_over_empty_configuration` — parametrised over {`def`, `async def`} × {`Interpreter`, `SyncInterpreter`}, using the attached nested-final/`always`/`after` chart: across N laps, no receipt with `error is None` coincides with an empty `current_state_ids` at resolution time (mirrors the existing #197 persistence-side pinned test, applied to the receipt path).
- `test_receipt_and_snapshot_agree_on_mid_step` — for any lap where `get_persisted_snapshot()` would raise `SnapshotMidStepError` if called at that instant, the concurrently-resolving receipt (if any) must not report success — closing the exact disagreement this issue documents between the two call sites.
- `test_sync_interpreter_send_never_observes_empty_configuration` (regression guard) — `SyncInterpreter.send()`/`.start()` continue to never expose an empty `current_state_ids`, preserving the existing clean behaviour on that engine.

## Severity note

We rate this **Medium, not High**, precisely because the persistence door is shut: a caller can be *told* the wrong thing, but cannot *store* it. Our wrapper contains it by never reading a receipt for configuration — we read configuration separately at quiescence.

## Related

#197 — narrower than claimed: the changelog credits #197 with closing the torn-configuration exposure end to end, but the fix only reaches `get_persisted_snapshot()`; the receipt path (`_resolve_receipt`) that #197's own originally reported chart exercises is untouched, so the same underlying torn window is still externally observable through a different, equally documented API.

## Verification

- Date: 2026-09-22
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `f28719c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- cwd used: `<home>` (neutral, outside both repos)
- Exit codes: `R9-08_send_wait_resolves_over_empty_configuration.py` → **1** (async/`async def` cell: 1 empty_hit, success-shaped receipt coincident with `SnapshotMidStepError` at lap 0; async/`def` and sync/`def` cells clean, 0 empty_hits)
