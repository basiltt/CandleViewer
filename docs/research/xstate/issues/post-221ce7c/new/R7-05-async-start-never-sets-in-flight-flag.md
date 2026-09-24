---
r7: R7-05
title: "Bug: async `start()` never sets the in-flight flag, so the mid-step snapshot refusal is inert for the whole initial-entry window — 720/720 torn blobs land there; sync refuses the identical call"
labels: [bug, severity/high, area/interpreter, area/persistence]
severity: High
engines: async only (`SyncInterpreter` is correct)
repro_script: repro/R7-05_async_start_never_sets_in_flight_flag.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

The root-level mid-step snapshot refusal is inert during the async engine's
initial-entry window. A `get_persisted_snapshot()` from an entry action running
during `start()` is **accepted** on async and **refused** on sync, and the blob it
returns is torn.

```
write-accepted / read-refused blobs: async=1 sync=0          (VERDICT FAIL)
sync : REFUSED / REFUSED
async: ACCEPTED, ctx filled_qty=100 avg_px=0  -> restores silently, last_error=None
property run: 720 torn outcomes, ALL in window `entry@start`;
              `on_transition@start` (320 cases) tears zero times
```

An order snapshot with `filled_qty=100` and `avg_px=0` restores clean, because the
configuration is legal. Nothing downstream can detect it.

## Root cause

`interpreter.py` assigns `_processing` in exactly three places — `:420`
(initialise `False`), `:1654` and `:1698` (the run loop). `start()` (`:536-556`)
runs `_enter_states` and `_settle_transient_transitions` with the flag still
`False`. `sync_interpreter.py:370-374` deliberately sets `_is_processing = True`
around its initial descent.

`base_interpreter.py:1389` gates the root refusal on `_step_in_flight()`
(`:1290-1295`), which reads only those two flags — so the refusal cannot fire for
the entire async initial-entry window. The fix that moved initial invoke
registration into `start()` **widened** the window.

## Why it is not covered by the existing resolution

The docs (`api/index.md:715`, `:1789`) promise `SnapshotMidStepError` when
`get_persisted_snapshot()` is called "from inside an action" — which is exactly
this call site. It is not API misuse either: the sync engine refuses on the
identical machine, and no flag exists that makes async refuse, so there is no
correct usage that avoids it.

## Suggested fix

Mirror `sync_interpreter.py:370-374`: set `self._processing = True` around the
initial descent in `Interpreter.start()`, restored in a `finally`.

## Environment

- `xstate-statemachine` @ `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- CPython 3.13.7, Windows 11
- both engines compared on the identical machine; async is the defective one

## Minimal reproduction

`repro/R7-05_async_start_never_sets_in_flight_flag.py` — standalone, library
only; runs sync and async on the same chart and restores any torn blob it
captures. 60 s watchdog. **Exit code 1** means async accepted a torn
initial-entry snapshot that sync refused.

## Observed

```
--- sync
  live after start : ctx={'filled_qty': 100, 'avg_px': 101.5}
  snapshot in entry: REFUSED  ctx=None
  snapshot in entry: REFUSED  ctx=None
--- async
  live after start : ctx={'filled_qty': 100, 'avg_px': 101.5}
  snapshot in entry: ACCEPTED ctx={'filled_qty': 0, 'avg_px': 0}
  snapshot in entry: ACCEPTED ctx={'filled_qty': 100, 'avg_px': 0}   >>> TORN
     restored: ['oms.filled'] ctx={'filled_qty': 100, 'avg_px': 0} last_error=None

torn ACCEPTED blobs in the initial-entry window: async=1 sync=0
```

The property run behind this (7,622 attempts) produced **720 torn outcomes, all
720 attributed to the `entry@start` window**; `on_transition@start` (320 cases)
tears zero times.

## Expected

`SnapshotMidStepError` on both engines.

- **The library's own contract, quoted.** `docs/api/index.md:715` on
  `.get_persisted_snapshot()`:

  > "Raises `SnapshotMidStepError` **[0.8.1]** (#102) if called while a macrostep
  > is in flight (e.g. from inside an action)"

  and `docs/api/index.md:1789`: "`get_persisted_snapshot()` was called while a
  macrostep is in flight … **Snapshotting from inside an action.**" The call site
  in the repro is precisely "from inside an action".
- **Engine parity.** `sync_interpreter.py:370-374` implements the contract; the
  async engine does not, and no flag exists that makes it do so — there is no
  correct usage that avoids the window.

## Impact

**General.** For the whole initial-entry window — widened by #171, which moved
child registration and initial settling into `start()` — the documented
mid-step refusal is inert on the async engine. Snapshots taken there are torn in
the *context*, which the read-side legality check cannot detect, so they restore
clean with `last_error is None`.

**Order-management scenario.** An order restored into `filled` with
`filled_qty=100, avg_px=0` is a position with a size and no price: P&L, average
price and risk are all computed from a value that was never written. Nothing
downstream raises, because the configuration is legal.

## Proposed fix

```python
self._processing = True
try:
    await self._enter_states([self.machine], init_event)
    await self._settle_transient_transitions()
    await self._await_actor_bringups()
finally:
    self._processing = False
```

around `interpreter.py:536-561`, exactly as `sync_interpreter.py:370-374` does.

## Acceptance criteria

- `test_snapshot_from_initial_entry_action_is_refused` — a
  `get_persisted_snapshot()` from an entry action of the **initial**
  configuration raises `SnapshotMidStepError`; **parametrised over `def` /
  `async def` action kinds and over both `Interpreter` and `SyncInterpreter`**.
- `test_step_in_flight_is_true_during_initial_descent` — `_step_in_flight()`
  reads `True` throughout `start()`'s entry + settle + bring-up block on both
  engines.
- `test_no_torn_context_blob_in_start_window` — property form: over N runs of a
  paired context write in entry, zero accepted blobs have one half written.
- `test_processing_flag_restored_after_start_raises` — an entry action that
  raises still leaves `_processing` `False`.

## Related

Deepens **#169** (`get_persisted_snapshot()` from inside an entry/exit action is
accepted and persists a torn state), closed against this commit: #169's root
refusal genuinely works for the post-start path on both engines — we verified
that — but is inert in the initial-entry window because the flag it reads is
never set there. **#171** widened that window. Companion residual windows from the
same #169 fix: **R7-07** (child branch) and **R7-10** (transition actions). Also
**#102**, **#142**, **#143** (the read side that cannot catch a torn context).

Register source ids: `D7-persistence-1`, `D7-semantics-1` (identical root cause,
two probes); `q1b_start_entry_window_min.py`, `d7s1_start_entry_window_torn.py`,
`q1_hook_snapshot_property.py`.

## Verification

- Date: 2026-09-20
- Python: 3.13.7 (CPython, Windows 11)
- Library: `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- Command: `python repro/R7-05_async_start_never_sets_in_flight_flag.py`
- Exit code: **1** (reproduced)
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 220 --search "snapshot child"` — #169/#102/#142/#143 all CLOSED; no
  open duplicate.
