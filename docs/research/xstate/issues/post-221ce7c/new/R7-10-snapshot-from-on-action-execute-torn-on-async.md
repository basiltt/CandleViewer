---
r7: R7-10
title: "Bug: `get_persisted_snapshot()` from `on_action_execute` returns a torn blob (`status: running`, `state_ids: []`) on async; the sync engine refuses the identical call"
labels: [bug, severity/medium, area/persistence, area/plugins]
severity: Medium
engines: async only
repro_script: repro/R7-10_snapshot_from_on_action_execute_torn.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

Calling `get_persisted_snapshot()` from the `on_action_execute` plugin hook
returns a blob with `status: "running"` and `state_ids: []` on the async
engine. The sync engine refuses the same call with `SnapshotMidStepError`.
Engine parity is broken and the async result is meaningless. Standalone
reproduction: `repro/R7-10_snapshot_from_on_action_execute_torn.py`.

The blob is caught on restore by the round-6 #143 configuration-legality
check, so this is an **observability and parity** defect, not a corruption
path — a caller that persists it discovers the problem at restore time rather
than silently loading bad state.

This is the third residual window of the round-6 #169 root-level mid-step
refusal (the other two are the async initial-entry window, R7-05, and the
child-actor branch, R7-07, both filed separately). All three have the same
shape: the refusal is gated on flags that the async engine does not set on
that path.

## Environment

- Library commit: `221ce7c` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Engine: async only (`Interpreter`); `SyncInterpreter` refuses correctly

## Minimal reproduction

See `repro/R7-10_snapshot_from_on_action_execute_torn.py` — a byte-for-byte
copy is kept alongside this issue. A nested machine with entry/exit actions
at every level and a `STEP` transition carrying its own action list is driven
once on the async engine and once on the sync engine, with a plugin that
calls `get_persisted_snapshot()` from every `on_action_execute` invocation.
Exits 1 while at least one async call returns a torn blob, 0 once fixed.

## Observed

```
async rows: [{'action': 'act', 'disposition': 'RETURNED', 'status': 'running', 'state_ids': []}, {'action': 'act', 'disposition': 'RETURNED', 'status': 'running', 'state_ids': ['ord.top.one.deep']}, {'action': 'act', 'disposition': 'refused:SnapshotMidStepError'}, {'action': 'act', 'disposition': 'refused:SnapshotMidStepError'}, {'action': 'act', 'disposition': 'refused:SnapshotMidStepError'}]
sync  rows: [{'action': 'act', 'disposition': 'refused:SnapshotMidStepError'}, {'action': 'act', 'disposition': 'refused:SnapshotMidStepError'}, {'action': 'act', 'disposition': 'refused:SnapshotMidStepError'}, {'action': 'act', 'disposition': 'refused:SnapshotMidStepError'}, {'action': 'act', 'disposition': 'refused:SnapshotMidStepError'}]
async_torn_blobs=1 sync_torn_blobs=0
restored_from_torn_blob: {'restore': 'REFUSED', 'exc': 'SnapshotCorruptError'}
```

## Expected

XState v5's `getPersistedSnapshot()` is documented as reflecting the actor's
current, settled configuration; the library's own documented contract for
this exact case (see the round-6 #169 refusal design and its own comment at
`base_interpreter.py:1385-1388`, "the documented contract... is what callers
rely on") is that a mid-step snapshot attempt is refused
(`SnapshotMidStepError`), not silently handed back with an empty
`state_ids`. The sync engine implements that contract for this call site;
the async engine does not, for at least one action position.

## Root cause

`src/xstate_statemachine/base_interpreter.py:1389` (`if
self._step_in_flight():` refusal check) is armed on the "in flight" flag set
by round-6 #169 for entry/exit actions, but `on_action_execute` also fires
for **transition** actions, and for those the async engine's
exit→actions→enter transaction (`interpreter.py`, `_execute_transition`) has
already emptied `_active_state_nodes` via `_exit_states` before the in-flight
flag covers that window — so the refusal check at `:1389` sees a legal-looking
(non-in-flight) state and lets the call through onto an already-torn
configuration.

## Impact

General: a plugin author following the documented pattern ("snapshot from
inside a hook, expect either data or `SnapshotMidStepError`") gets silent
garbage from one specific hook position on one specific engine, discovered
only later at restore time. Order-management scenario: an audit/replay
plugin that snapshots on every action for a compliance trail silently
records a blob with no active states for an in-flight order transition on
the async engine, while the same code path on the sync engine correctly
raises and is caught — a parity gap that surfaces as flaky, engine-dependent
test failures in exactly the kind of plugin most likely to be relied on for
correctness evidence.

## Proposed fix

Extend the in-flight flag to cover the whole exit→actions→enter transaction
on the async engine, so transition actions are inside the same refusal
window that entry/exit actions already are — mirroring the fix direction for
R7-05 (the async initial-entry window).

## Acceptance criteria

- `test_on_action_execute_snapshot_refused_during_transition_actions[def]`
  and `[async def]` (async engine only; parametrised over action-implementation
  kind where applicable): `get_persisted_snapshot()` called from
  `on_action_execute` during a transition's own action list raises
  `SnapshotMidStepError`, matching the sync engine's behaviour for the
  identical machine and event.
- `test_on_action_execute_snapshot_parity_both_engines`: for the same nested
  machine and `STEP` event, the set of `on_action_execute` calls that return
  a snapshot (vs refuse) is identical between `Interpreter` and
  `SyncInterpreter`.

## Related

Round-6 #169 (root-level mid-step refusal) — this is the third residual
window; see also R7-05 (async initial-entry window) and R7-07 (child-actor
branch), both the same class of gap. Register id `D7-concurrency-2`.

## Verification

- Date: 2026-09-20
- Python: 3.13.7
- Commit: 221ce7c
- Command: `python repro/R7-10_snapshot_from_on_action_execute_torn.py`
- Exit code: 1 (reproduced — 1 torn blob from async, 0 from sync)
