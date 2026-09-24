---
r7: R7-11
title: "Bug: `SyncInterpreter._deferred_this_step` is never cleared on the `wait=False` path — unbounded growth; its sibling `_guard_denied_this_step` is cleared correctly"
labels: [bug, severity/medium, area/sync-interpreter, area/interpreter]
severity: Medium
engines: sync only
repro_script: repro/R7-11_sync_deferred_this_step_never_cleared.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

**Regression** (sync `_deferred_this_step` is never cleared on the `wait=
False` path, only on `wait=True`). It accumulates without bound — it is never
reset between steps when the caller uses the documented fire-and-forget
shape. The directly analogous `_guard_denied_this_step` **is** reset on the
same path, which is what makes this look like an omission rather than a
design decision. We probed the sibling specifically to check, and it is
clean. Standalone reproduction:
`repro/R7-11_sync_deferred_this_step_never_cleared.py`.

Consequences: a long-lived sync interpreter driven with fire-and-forget sends
grows this collection for the life of the process, and any per-step consumer
of it reads a value contaminated by every earlier step.

## Environment

- Library commit: `221ce7c` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Engine: sync only (`SyncInterpreter`)

## Minimal reproduction

See `repro/R7-11_sync_deferred_this_step_never_cleared.py` — a byte-for-byte
copy is kept alongside this issue. A `SyncInterpreter` with `onUnhandled:
"defer"` is sent 5000 unhandled events with `wait=False` (the documented
fire-and-forget shape), then one event with `wait=True`. Exits 1 while
`_deferred_this_step` retains more than 1 entry after the 5000 `wait=False`
sends, 0 once fixed.

## Observed

```
sends=5000
_deferred_this_step (per-STEP scope) = 5000
_deferred_events    (the real buffer, correctly bounded) = 1000
after one wait=True send: _deferred_this_step = 1
```
The real defer buffer (`_deferred_events`) is correctly bounded at 1,000;
only the per-step bookkeeping list grows without limit. A single `wait=True`
send flushes it, proving the reset is gated on `wait` rather than run once
per step.

## Expected

The library's own documented contract for this field, in
`sync_interpreter.py`'s own comments at the reset site (`# #106: per-step
scope`), is that `_deferred_this_step` has per-step scope — i.e. it must be
empty at the start of every step regardless of whether that step is a `wait=
True` or `wait=False` send. Its sibling `_guard_denied_this_step` (`# #153:
per-step scope`, same comment convention, same reset site) correctly
implements exactly that contract on the identical `wait=False` path — the two
fields are declared with the same scope and only one honours it.

## Root cause

`src/xstate_statemachine/sync_interpreter.py:570-571`, inside `send()`:
```python
if wait:
    config_before = frozenset(self._active_state_nodes)
    if not self.machine.context_is_immutable:
        context_before = copy.deepcopy(self.context)
    self._deferred_this_step.clear()  # #106: per-step scope
    self._guard_denied_this_step = False  # #153: per-step scope
```
Both per-step resets are gated behind `if wait:` as a performance
optimisation (the receipt-only bookkeeping is skipped when no `Receipt` is
returned), but `_deferred_this_step` is appended to unconditionally by
`_handle_unhandled_event` (`base_interpreter.py:3978`,
`self._deferred_this_step.append(event)`) regardless of `wait` — so on the
`wait=False` path the list grows every step and is never drained until a
`wait=True` send happens to occur.

## Impact

General: any long-lived `SyncInterpreter` driven predominantly with
fire-and-forget `send()` calls (the documented default shape) leaks memory
for the life of the process whenever it also defers events, and any
`Receipt.deferred` computed after a mix of `wait=False`/`wait=True` sends is
computed against a list contaminated by every earlier step's entries, not
just the current one. Order-management scenario: an order-state machine that
defers late-arriving fills or cancels while busy, driven mostly with
fire-and-forget event delivery from a market-data or order-gateway thread,
accumulates one leaked list entry per deferred event for the life of the
process — and any downstream code that inspects `_deferred_this_step`
directly (or a future API built on it) sees stale entries from thousands of
steps ago.

## Proposed fix

Clear `_deferred_this_step` at the same point the `wait=True` path clears it,
unconditionally — i.e. move the `self._deferred_this_step.clear()` call
outside the `if wait:` guard, at the same point `_guard_denied_this_step` is
reset (or reset both together unconditionally at the top of every step).

## Acceptance criteria

- `test_sync_deferred_this_step_cleared_on_wait_false_send`: after N
  `wait=False` sends that each cause exactly one deferral, `len(interpreter.
  _deferred_this_step) <= 1` after each send (bounded per-step, not
  accumulating).
- `test_sync_deferred_this_step_and_guard_denied_share_scope`: for a mixed
  sequence of `wait=True` and `wait=False` sends, `_deferred_this_step` and
  `_guard_denied_this_step` are reset at the same points (parity between the
  two per-step-scoped fields is preserved).
- `test_sync_deferred_this_step_no_regression_on_wait_true`: existing
  `wait=True` behaviour (receipt's `deferred` flag) is unchanged.

(Sync-only defect; no `def`/`async def` service-kind parametrisation applies
since it does not depend on invoked services.)

## Related

Round-6 `L-9` (`_guard_denied_this_step` stickiness on `wait=False`) is the
sibling probe that came back negative (correctly reset) — see
`43-r7-findings-register.md`, confirming this is a genuine asymmetry between
the two per-step-scoped fields, not a shared design choice. Register id
`L-6`.

## Verification

- Date: 2026-09-20
- Python: 3.13.7
- Commit: 221ce7c
- Command: `python repro/R7-11_sync_deferred_this_step_never_cleared.py`
- Exit code: 1 (reproduced — 5000 entries retained across wait=False sends)
