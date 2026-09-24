# R11-02 — "`scheduled_sends` is a second, ungated restore door" — DOWNGRADED High → Low

Filed **High** (security). **Downgraded to Low.** The security claim is refuted; a real but observability-grade contract inconsistency survives and is raised as a note on the #214 thread rather than as its own issue.

## Behaviour — reproduces exactly as reported

`base_interpreter.py:1900-1904` stores `scheduled_sends` records verbatim into `_restored_self_sends`; `_rearm_restored_self_sends` (`:1244-1260`) arms them via `_deliver` with `_processing` deliberately raised, i.e. with self-generated engine standing. `_admit_restored` — the `strict` mirror #214 added — is called only from the `pending_events` loop two lines below (`:1909-1916`).

Confirmed: forged records deliver bogus events under `strict`, drive `onDone`, and fire a declared 60 s `after` in ~1 ms, with `invalid == []` and `last_error == null`, on both engines and both action kinds. Sub-finding (c): `lane: "priority"` is caller-writable and `_enqueue_restored` honours it with no provenance check.

## Why the security claim fails

1. **No trust boundary is crossed.** New standalone probe `probes/main-c78ce99/r11_02_equivalent_doors.py`: forging the snapshot's `configuration` **alone** reaches the same target state **with no event at all**. The v2 `pending_events` upcast (#214) and the v3 `"engine": true` flag (#195) are *documented* doors to the same place.
2. **The library states the boundary explicitly** at `events.py:421`: *"a caller who can write arbitrary snapshot records already controls `state_ids` and `context` outright (#185)."* The R10-01 pattern, third occurrence.
3. **The live path is checked.** A live `raise(delay=)` is strict-checked at arm time (`base_interpreter.py:3525`), so an undeclared event enters `scheduled_sends` only via forgery or a chart change.
4. `minimum_version=3` does **not** close this door — a fully valid v3 blob suffices — which was the original reason for the High. That is true, and it is immaterial once the door leads somewhere the writer could already reach.

## What survives — Low, contract inconsistency

#214 promises that restored user events get the same `strict` check a `send()` does, **with a reported refusal**. That is true for `pending_events` and false for the field added in the same release. So a **chart upgrade that undeclares an event** yields *silent delivery* through this path instead of `on_invalid_event` / `last_error`.

That is a real defect of the observability kind, not of the security kind.

**Suggested fix (raised on #214):** route `_rearm_restored_self_sends` through `_admit_restored`, and refuse `kind in (done, error, after)` in `scheduled_sends` outright — a delayed *self-send* is never a completion.

## Carried forward

- **CV-C54** — reconcile persisted vs admitted record counts on restore and fail loudly.
- **CV-C42, re-grounded** — together with R11-12 (`lane` unenforceable on the sync engine), restored **ordering is not a property at all**. The wrapper must not depend on it.

Adoption verdict unchanged by this finding.
