---
r7: R7-09
title: "Bug: a contradictory `configuration` key outranks `state_ids` on restore, so a blob whose two state fields disagree restores to the wrong machine state"
labels: [bug, severity/medium, area/persistence]
severity: Medium
engines: both
repro_script: repro/R7-09_configuration_outranks_state_ids.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

A persisted snapshot carries both `state_ids` and `configuration`. When the two
disagree, `configuration` wins — `base_interpreter.py:1689`:
```python
restore_ids = snapshot.get("configuration") or snapshot["state_ids"]
```
so a blob whose `configuration` was emptied or rewritten while `state_ids`
stayed intact restores into a state the `state_ids` field explicitly
contradicts, with no diagnostic. Standalone reproduction:
`repro/R7-09_configuration_outranks_state_ids.py`.

Carried forward from the previous round unchanged; the read-side legality work
(round 6, #143) closed the neighbouring cases (5 000 mutations produced 0 raw
builtins and 0 restored `running`-with-no-leaf), and this is the hole that
remains.

## Environment

- Library commit: `221ce7c` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Engine: both (reproduced on `SyncInterpreter`; the restore path is shared
  by `Interpreter`)

## Minimal reproduction

See `repro/R7-09_configuration_outranks_state_ids.py` — a byte-for-byte copy
is kept alongside this issue. It persists a two-state machine, then restores
two mutated blobs: `configuration=[]` (silently falls back and is accepted)
and a `configuration` naming a different leaf than `state_ids` (silently
relocates the machine). Exits 1 while the behaviour is present, 0 once fixed.

## Observed

```
state_ids in snapshot     = ['m.a']
configuration in snapshot = ['m', 'm.a']

  configuration=[] (state_ids intact)            ACCEPTED  states=['m', 'm.a']
  configuration=['m','m.b'] vs state_ids=['m','m.a'] ACCEPTED  states=['m', 'm.b']
```

## Expected

XState v5's `getPersistedSnapshot()`/restore contract treats the persisted
value as authoritative and singular — there is no analogous split field to
cross-validate in JS, but the SCXML configuration-legality principle (exactly
one active leaf per region, ancestors closed) that `base_interpreter.py`
itself implements in `_configuration_is_legal()` implies `configuration` must
be the ancestor closure of `state_ids`; a mismatch between two fields that are
redundant by construction is definitionally corrupt data and should be
refused, not silently resolved in favour of one field.

## Root cause

`src/xstate_statemachine/base_interpreter.py:1689`:
```python
restore_ids = snapshot.get("configuration") or snapshot["state_ids"]
```
The reader prefers `configuration` unconditionally and never cross-validates
it against `state_ids`. The round-6 #143 read-side legality check runs AFTER
this selection, so a legal-but-forged configuration passes it cleanly.

## Impact

General: any lossy or partially-corrupted transport (a proxy that truncates
one field, a manual edit, a buggy migration script) silently relocates the
machine to a plausible-looking but wrong state instead of failing loudly.
Order-management scenario: a snapshot store that races two writers, or a
migration that patches `configuration` for a schema change but misses
`state_ids` (or vice versa), silently reopens or reroutes an order's state
machine to the wrong state with no error surfaced to the operator.

## Proposed fix

Refuse a payload whose `state_ids` is not a subset of its `configuration`
(equivalently: `configuration` must equal the ancestor closure of
`state_ids`), rather than resolving the disagreement in favour of either
field — raise `SnapshotCorruptError`. That is the one-line assertion applied
in downstream restore wrappers, and it costs nothing on the legal-blob path.

## Acceptance criteria

- `test_configuration_state_ids_mismatch_refused` (both engines,
  `SyncInterpreter.from_snapshot` and `Interpreter.from_snapshot`):
  a blob with `configuration=[]` and non-empty `state_ids` raises
  `SnapshotCorruptError`.
- `test_configuration_contradicts_state_ids_refused` (both engines): a blob
  whose `configuration` names a leaf disjoint from `state_ids` raises
  `SnapshotCorruptError`.
- `test_configuration_matching_state_ids_still_accepted` (both engines,
  regression guard): a legal blob where `configuration` is exactly the
  ancestor closure of `state_ids` continues to restore successfully.

## Related

Round-6 #143 (read-side configuration-legality check) closed the neighbouring
corruption cases but runs after this selection, leaving this hole; register
id `D7-persistence-3` (carried `R6-16`, re-rated Medium this round because the
contradictory key is authoritative, not merely unvalidated).

## Verification

- Date: 2026-09-20
- Python: 3.13.7
- Commit: 221ce7c
- Command: `python repro/R7-09_configuration_outranks_state_ids.py`
- Exit code: 1 (reproduced — both mutated blobs silently accepted)
