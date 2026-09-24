---
r8: R8-08
title: "Bug: #186's `configuration` / `state_ids` agreement rule is one-sided — emptying either field short-circuits the check and lets a forged `configuration` relocate the machine"
labels: [bug, severity/medium, area/persistence]
severity: Medium
engines: both engines
service_kinds: n/a
repro_script: repro/R8-08_configuration_state_ids_one_sided.py
commit: 6db65d8
python: 3.13.7
verified: true
---

## Summary

#186's `configuration` / `state_ids` agreement check short-circuits when **either** field is
empty or absent. Emptying `state_ids` — a strictly simpler mutation than the contradiction
#186 refuses — lets a forged `configuration` relocate the machine on restore.

## Reproduction (`6db65d8`)

`repro/R8-08_configuration_state_ids_one_sided.py`: a blob whose `state_ids` is `[]` and
whose `configuration` names a different state than the one persisted restores **into the
forged configuration**, with no `SnapshotCorruptError`. The contradiction case that #186
was filed for is correctly refused, and the agreeing / absent-field cases correctly restore
— only the emptied-field case walks through.

The same holds symmetrically for an emptied `configuration`.

## Cause

The agreement test never runs when one side has nothing to disagree with. An empty list is
being treated as "no opinion" rather than as "disagreement", on a payload that declares
`version >= 1` and therefore claims to carry both fields.

## Suggested fix

On a `version >= 1` payload, treat an empty or absent `configuration` or `state_ids` as
disagreement rather than as an absent constraint — an emptiness pre-check ahead of the
existing comparison. This is likely a one-line change and it closes the strictly-easier
mutation.

## Impact

The input that can contradict two fields is the same input that can empty one of them, so
the check is bypassed by the weaker attacker. On our side a restore is how an order machine
comes back after a crash, and a relocated configuration is a position the system believes
in.

## Verification

2026-09-21, python 3.13.7, commit 6db65d8. Run with `PYTHONPATH` including
`battle-6db65d8/concurrency` so `common2` resolves (the repro file's `from common2 import
...` is unchanged/byte-identical; it is a sibling-directory helper, not part of the repro
body).

`repro/R8-08_configuration_state_ids_one_sided.py` — exit 1, `"result": "FAIL"`,
`"accepted_contradictions": 8`. Confirmed both directions:
- `state_ids` emptied, `configuration` names the real leaves → `disposition: "ACCEPTED"`,
  restores to the true state (this sub-case happens to land correctly by luck of which side
  won, but is accepted with no `SnapshotCorruptError` despite one field being empty on a
  `version >= 1` payload).
- `state_ids` rewritten to a different (still-legal) leaf, `configuration` left correct →
  `disposition: "refused:SnapshotCorruptError"` — confirms the *contradiction* case from #186
  is still caught.

Source confirmed at commit 6db65d8, `base_interpreter.py:1722`:
`restore_ids = snapshot.get("configuration") or snapshot["state_ids"]` — an `or`, not a
comparison; an empty `state_ids` (falsy) always yields to `configuration` with no agreement
check.
