# R11-02 adversarial refutation — `scheduled_sends` restore door

**Verdict: DOWNGRADE High → Low** (contract inconsistency, not a trust-boundary defect)

## What reproduces (both re-run at c78ce99)
- `probes/main-c78ce99/p5_214_strict_lane.py` (b): a BOGUS `scheduled_sends`
  record is delivered under `strict: True`; `last_error=None`, `on_invalid_event=[]`.
- `battle-c78ce99/concurrency/u4_restore_trust_surface.py`: forged `scheduled_sends`
  drives `onDone` and fires a declared 60 s `after` in ~1 ms.
- Cause confirmed by source: `base_interpreter.py:1900-1904` stores records verbatim;
  `_rearm_restored_self_sends` (:1244-1260) → `restore_event` → `_arm_restored_self_send`,
  never `_admit_restored` (:1211, called only from the pending_events loop :1909-1916).

## Why it is not High — equivalent-doors probe
`probes/main-c78ce99/r11_02_equivalent_doors.py` (neutral cwd, sync engine, `strict: True`,
chart `a --WAKE--> b`, `after: 60000 -> late`), four mutations of the same snapshot:

| # | forged field | result |
|---|---|---|
| 1 | `configuration/state_ids` → `m.late` | **`m.late`** — no event needed at all |
| 2 | v2 `pending_events` `after` record | `m.late` (documented #214 upcast) |
| 3 | `scheduled_sends` `after` record | `m.late` (the reported door) |
| 4 | v3 `pending_events` `{"engine": true}` | `m.late` (documented #195) |

An attacker who can write `scheduled_sends` can write `configuration` in the same blob and
reach the target state directly, without any event. `events.py:421` states this boundary
explicitly: *"A caller who can write arbitrary snapshot records already controls `state_ids`
and `context` outright (#185), so this is the correct trust boundary."* This is the R10-01
pattern: the snapshot is trusted input. The "forged priority lane" half (p5 c) is the
documented `lane` field of #214 on `pending_events`, same boundary.

Also: a live `raise(delay=)` passes `_check_strict` at **arm** time
(`base_interpreter.py:3525`), so an undeclared event can only be in `scheduled_sends`
via a hand-forged blob or a chart that changed between persist and restore.

## What survives
#214's stated contract — *"restored user events pass the same `strict` check a `send()`
does; a refusal is reported"* — holds for `pending_events` and not for `scheduled_sends`.
Benign trigger (no forgery): persist under `strict`, upgrade the chart so the event is no
longer declared, restore → the send is delivered silently instead of being refused and
reported via `on_invalid_event` / `last_error`. Real, but observability-grade.

**Fix (one line of intent):** route `_rearm_restored_self_sends` records through
`_admit_restored` before arming, skipping engine-minted kinds as the pending loop does.

**Severity: Low.** No new capability; contract inconsistency + missing refusal report.
Adoption verdict unchanged (row-8 ADOPT, Phase-3 may begin); add a constraint to treat
snapshot blobs as trusted storage (already CV-C-class) and to re-check `strict` after any
chart change that removes a declared event.
