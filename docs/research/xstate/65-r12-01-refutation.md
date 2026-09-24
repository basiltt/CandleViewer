# R12-01 adversarial refutation — "forged `scheduled_sends` mints engine-only events" @ de2da4e

**Verdict: DOWNGRADE Blocker → Low (strict-mode parity gap, #214).** The
security claim as written is REFUTED; a narrower, non-security defect survives.

## What the claim said
`_rearm_restored_self_sends` calls `restore_event()` / `_arm_restored_self_send`
directly, bypassing `_admit_restored`, so "the v3 `engine` provenance flag is
never consulted" and a forged record mints `done.invoke.*` / `after.*` with
attacker-chosen payload.

## Reproduced (standalone, cwd `C:/Users/basil`, stdlib + xstate_statemachine)
`battle-de2da4e/fuzz/r12-01_refutation_repro.py`, both `def` and `async def`,
polled to convergence (60 × 20 ms):

| record appended to `scheduled_sends` | result | delivered event |
|---|---|---|
| control (untouched v3 blob) | `['fg.armed']` inert | — |
| D1 `{"type":"done.invoke.job","data":{"filled":999999}}` | `['fg.expired']` | `Event`, `is_system_event=False`, **`e.data == {}`** |
| D1b same **+ `"kind":"done","engine":true`** | `['fg.expired']` | `_EngineDone`, `is_system_event=True`, `data={'filled':999999}` |
| D2 `{"type":"after.999.fg.armed"}` | `['fg.expired']` | `Event`, `is_system_event=False` |
| D6 same forgery in **`pending_events`** (pre-existing path) | `['fg.expired']` | `Event`, `is_system_event=False` |

## Why the claim fails
1. **The `engine` flag IS consulted.** `restore_event` → `_restore(...,
   trusted=record.get("engine") is True)` runs on the `scheduled_sends` path
   exactly as on the `pending_events` path. Without the flag the record
   restores as a *public* `Event` — user traffic, not a completion — and the
   claimed payload never arrives (`e.data == {}`, `filled` absent). The repro's
   own `hit={'filled':999999}` only appears in D1b where the forger *adds*
   `engine: true`.
2. **The D1b escalation is not new and is a documented trust boundary.** The
   identical result is reachable through `pending_events` (`r12-01_refutation_repro_b.py`:
   `engine:true` → `_EngineDone`, `data={'filled':42}`), the #195 path that ships
   with the explicit comment: *"A caller who can write arbitrary snapshot records
   already controls `state_ids` and `context` outright (#185), so this is the
   correct trust boundary."* `from_snapshot`'s docstring (#205) states the snapshot
   is TRUSTED INPUT and `machine_hash` is a fingerprint, not a MAC — authenticate
   outside. A party who can append to `scheduled_sends` can equally set
   `configuration: ["fg.expired"]` and `context: {"filled": 999999}` directly, which
   is strictly more powerful. **No privilege boundary is crossed** (same R10-01/R11-01
   pattern). Not a duplicate; a re-instance.
3. XState v5 offers no counter-authority: `createActor(m, {snapshot})` likewise
   restores persisted snapshots verbatim and documents them as trusted.

## What does survive (the downgrade)
`_rearm_restored_self_sends` does **not** call `_admit_restored`, so `strict: True`
is enforced on restored `pending_events` but **not** on restored `scheduled_sends`.
Measured (`r12-01_refutation_repro_b.py`): on a `strict: True` machine an unknown
type in `pending_events` yields `UnknownEventError` on `last_error` at restore;
the same unknown type in `scheduled_sends` restores and arms silently —
`last_error is None` before and after `start()`. That is a real #214 parity gap:
an operator who relies on strict mode to catch a corrupted/migrated journal gets
no signal for the delayed-send half. It is a consistency/observability defect,
not an escalation — the event still arrives as ordinary user traffic.

Suggested fix: run `_admit_restored(event)` inside the `_rearm_restored_self_sends`
loop (and skip the record on refusal), mirroring the `pending_events` loop.

**Severity: Low.** Affects only strict-mode machines restoring hand-edited or
corrupted snapshots; no wrong state, no minted engine events, no payload
injection beyond what `context`/`configuration` already grant.
