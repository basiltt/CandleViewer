---
r7: R7-06
title: "Bug: `machine_hash` set to `None` or removed silently disables `from_snapshot()` drift verification on a `version >= 1` payload"
labels: [bug, severity/medium, area/persistence]
severity: Medium
engines: both
repro_script: repro/R7-06_null_or_absent_machine_hash_disables_drift_check.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

Under `verify_machine_hash=True` (the default, and passed explicitly in our test):

| Payload | Result |
|---|---|
| honest, correct hash | accepted |
| wrong hash value | `SnapshotDriftError` — correct |
| `machine_hash: None` | **ACCEPTED**, `states=['m','m.a']` |
| `machine_hash` key removed | **ACCEPTED** |

…while the payload still declares `version: 2`.

## Root cause

`persistence.py:276-277` keys the v0-compatibility bypass on the **field's
presence/value** instead of on the **declared version**. That contradicts
`docs/_guide/snapshots.md:252`, which scopes unconditional acceptance to payloads
with no `version` key at all, and contradicts `check_identity`'s own docstring.
`tests/test_persistence.py` has no null/absent-hash case.

## Severity — we downgraded this ourselves

We first filed it as a tampering issue and that framing does not hold: the hash is
a fingerprint, not a MAC, and an attacker able to null it can already rewrite
`state_ids` and `context`, which are accepted under any hash setting. Stripping
the hash grants an attacker nothing new.

The real residual harm is **operational**: a v2 snapshot whose `machine_hash` is
lost by a lossy transport (a JSON round-trip that drops nulls, a column default, a
schema migration) silently restores into a drifted machine with the wrong active
states. That is a correctness defect gated on a key-loss precondition — Medium.

## Suggested fix

One line: gate on `snapshot.get("version", 0) >= 1` and refuse a versioned payload
whose `machine_hash` is missing or null.

## Environment

- `xstate-statemachine` @ `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- CPython 3.13.7, Windows 11
- both engines (the code path is engine-independent; repro uses `SyncInterpreter`)

## Minimal reproduction

`repro/R7-06_null_or_absent_machine_hash_disables_drift_check.py` — standalone,
library only. Snapshots machine A, restores into structurally different machine B
with `verify_machine_hash=True`, and carries both controls (same-machine accept,
honest-hash refuse). **Exit code 1** while present, 0 once a versioned payload
with a null/absent hash is refused.

## Observed

```
snapshot version      = 2
snapshot machine_hash = '510abea7b8ae24b2'

Restoring into structurally DIFFERENT machine B, verify_machine_hash=True:
  honest hash vs machine A (control)         ACCEPTED  states=['m', 'm.a']
  honest hash vs machine B                   SnapshotDriftError
  machine_hash=None vs machine B             ACCEPTED  states=['m', 'm.a']
  machine_hash key REMOVED vs machine B      ACCEPTED  states=['m', 'm.a']
```

Both controls behave correctly, isolating the defect to the null/absent field.

## Root cause

`persistence.py:276-277`, confirmed open in the current source:

```python
snap_hash = snapshot.get("machine_hash")
if verify_hash and snap_hash is not None:
```

The bypass is keyed on the **field's presence/value** rather than on the
snapshot's **declared `version`**.

## Expected

A payload declaring `version >= 1` whose `machine_hash` is missing or `None` is
refused under `verify_machine_hash=True`.

- **The library's own contract, quoted.** `docs/_guide/snapshots.md:252`:

  > "**Unversioned 0.7.x snapshots restore unchanged.** A payload with **no
  > `version` key** is treated as version 0 and accepted unconditionally — there
  > is no breaking change for snapshots taken before 0.8.0."

  The documented bypass is scoped to *no `version` key*. The code instead keys it
  on the *hash* field, so a `version: 2` payload takes the v0 path.
- **XState v5.** v5 restores via `createActor(logic, { snapshot })` and treats the
  snapshot as belonging to the logic it is passed
  (<https://stately.ai/docs/persistence>); this library's `machine_hash` is an
  added safety check over that, and the check is the only drift defence it has.

## Impact

**General.** A v2 snapshot whose `machine_hash` is lost by a lossy transport — a
JSON round-trip that drops nulls, a database column default, a schema migration —
silently restores into a drifted machine with the wrong active states, under the
default `verify_machine_hash=True`. Not a tampering issue (the hash is a
fingerprint, not a MAC, and anyone who can null it can rewrite `state_ids`), so
the harm is operational and gated on a key-loss precondition.

**Order-management scenario.** An order-state snapshot taken before a chart
change restores into the new chart with its old `state_ids` silently accepted:
an order believed to be in `working` resumes in a state the new machine gives a
different meaning, with no error. The drift check exists exactly to stop this
across a deploy.

## Acceptance criteria

- `test_versioned_snapshot_with_null_machine_hash_is_refused` — `version >= 1`
  and `machine_hash: None` raises `SnapshotCorruptError` (or `SnapshotDriftError`)
  under `verify_machine_hash=True`; **parametrised over both `Interpreter` and
  `SyncInterpreter`**.
- `test_versioned_snapshot_with_absent_machine_hash_is_refused` — same for a
  removed key.
- `test_unversioned_v0_snapshot_still_restores_unchanged` — the documented
  compatibility path (no `version` key) is not regressed.
- `test_verify_machine_hash_false_still_bypasses` — the explicit opt-out still
  works.

## Related

Carried from round 6 as `D6-security-1-R6-07` and re-verified **still present,
byte-identical source** on `221ce7c`; it is not in the #166–#175 fix set. Related
read-side work: **#45** (snapshots carry a schema version and machine identity —
this defect makes that version field non-load-bearing), **#143** and **#142**
(configuration-legality checks on restore). `tests/test_persistence.py` has no
null/absent-hash case.

Register source ids: `D7-persistence-2`, `D6-security-1-R6-07`;
`q2_readside_gaps.py`, corroborated by
`security/attack_snapshot_corrupt_fuzz.py` (`accepted_bad = 196/300`, unchanged
from `cec108b`).

## Verification

- Date: 2026-09-20
- Python: 3.13.7 (CPython, Windows 11)
- Library: `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- Command: `python repro/R7-06_null_or_absent_machine_hash_disables_drift_check.py`
- Exit code: **1** (reproduced)
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 220 --search "machine_hash"` — #45 and #143 are CLOSED and neither
  covers the null/absent field; no open duplicate.
