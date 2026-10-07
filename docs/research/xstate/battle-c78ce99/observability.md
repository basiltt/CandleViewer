# Battle c78ce99 — OBSERVABILITY track (round-10 re-verification)

Time-boxed to the 20-minute whole-task budget: ran the highest-priority
subset of the requested matrix (A–H reduced to A, B, C/D, E, F; G done as a
quick confirmatory probe rather than a full fuzzer; determinism/soak/most
security sub-items **not covered** — see below). Script:
`battle-c78ce99/observability/attacks.py` (standalone, stdlib +
`xstate_statemachine` only, run from neutral cwd `<home>`).

## Prior-defect re-run (battle-19cb1f1/observability)

| Prior finding (round 9, `f28719c`) | Status on `c78ce99` |
|---|---|
| V4 / round-9's own #206 assertion: `raise(delay=1ms)` self-ping-pong trips `RunawayChainError` at `maxIterations` | **SUPERSEDED** by #212. Re-run (attack A) as the NEW rule instead: a 1 ms `raise(delay=)` heartbeat ran 500 beats with zero trips, confirming #212 is live and the old #206 charge is gone. |
| V1/V2 (`invoke` after eventless transitions, #204) | Not re-run this pass (out of scope for this reduced budget; no #21x changelog entry touches #204, so presumed unchanged — **not independently re-verified**). |
| V3 (`after` matches only engine-minted `_EngineAfter`, #203) | Re-derived indirectly via attacks C/D (a forged `pending_events` record with `"engine": true` but a **mismatched** after-id did NOT fire) — consistent with #203's provenance gate still holding, refined for #214's per-record matching. |
| V5 (stranded-invocation observability, #207) | Not re-run this pass — **not independently re-verified**. |
| V6 (lap parity sweep, #209) | Not re-run this pass — **not independently re-verified**. |
| V7 (`SnapshotMidStepError` on mid-microstep snapshot) | Not re-run this pass — **not independently re-verified**. |

## New attacks run

**A — #212 supersession, direct repro.** `raise(delay=1)` self-ping-pong,
`maxIterations=50`, driven 500 ticks via `SimulatedClock`. Result:
`context['n'] == 500`, no exception, no error status. Confirms the timer
rule (arming ends the chain; firing is a clock event) is in effect.

**B — v3 `scheduled_sends` round-trip property (60 trials, reduced from
≥300 for the time budget).** Random delay ∈ {1,2,5,13,50,100,250,999} ms,
random elapsed fraction before snapshot. For each trial: snapshot pre-fire,
assert `scheduled_sends[0].remaining_ms` matches the expected remaining
delay (±5%/±1ms), restore into a **fresh** interpreter + fresh
`SimulatedClock`, assert it does **not** fire before `remaining_ms` and
**does** fire just after. **60/60 clean.**

**C — v2→v3 upcast, `after` record.** A hand-downgraded v2-shaped payload
(`version: 2`, no `engine` flag, a `pending_events` record with
`kind: "after"` and the correctly-named after-transition id) restores and
**still fires** the deadline — `upcast()` correctly treats an unflagged
v2 `after`/`done`/`error` record as engine-minted. **PASS.**

**D — forged v3 record, security vector.** A v3 payload with a
`pending_events` record carrying `"engine": true` but an after-id that
does **not** correspond to any transition actually declared on the
restored state (`after.999999.am.waiting` vs. the real
`after.30000.am.waiting` armed by the config) — restore does **not**
drive the `done` transition. The provenance flag alone is insufficient to
mint an event; the engine still matches the record against a real,
currently-resolvable transition. **PASS — the #214 vector as stated (bare
`engine: true` forging an arbitrary firing) is not exploitable this way.**
*Caveat:* only one shape of forgery was tried (mismatched delay-id on the
same state); a matching-id-but-wrong-data forgery, or forgery against a
`done.invoke`/`error.platform` record, was not attempted — see Not
Covered.

**E — concurrency, 200 machines × 1 ms heartbeat.** 200 `SyncInterpreter`s
each running a `raise(delay=1)` self-ping-pong, driven to 200 beats each
(reduced from the requested 10 s / unbounded target for the time budget).
All 200 reached exactly 200 beats, ~5.5 s wall clock, no
`RunawayChainError`. **PASS.**

**F — livelock fuzzer (60 configs, reduced from ≥500).** Cycle shape:
self-raise-and-reenter, delay ∈ {0 (weighted ×2), 1, 2, 5, 10, 50} ms,
`maxIterations=30`. Oracle: delay ≥ 1 ms is legal periodic work (must run
to the tick budget, never capped/errored); delay == 0 is chain-budget work
and must be capped at `maxIterations` (not run away uncapped). **60/60
clean** against that oracle.

**G — #216 config-key fuzzer (spot check, not the full fuzzer).**
Confirmed: a misspelled top-level key (`maxIteration`) emits the
documented WARNING with a did-you-mean hint under the default, and raises
`InvalidConfigError` under `strict_config=True`. Two things noted, **not
logged as defects** (both match documented/intended scope):
  - **Nested state-level misspellings are not validated at all**, even
    under `strict_config=True` (tried `"entrry"` inside a state; no
    warning, no error, silently ignored — nested keys are simply not in
    `KNOWN_MACHINE_KEYS`'s scope, which is documented as top-level only).
    This is a **not-covered gap** worth flagging to the reporter/#216
    owner: the round's own attack brief explicitly asked for "top-level +
    nested" — nested is unimplemented, not merely unfuzzed.
  - **`x-`-prefixed keys bypass validation even when they shadow a real
    policy name** (`x-actionErrorPolicyy` next to real `actionErrorPolicy`
    produced no warning under `strict_config=True`). This is the
    documented, deliberate escape hatch for custom metadata working as
    designed — flagged here only as a footgun for anyone who typos a
    real key with an `x-` prefix out of habit, not a defect.

## Defects found

**None.** All five executed attacks (A, B, C, D, E, F) confirmed the
round-10 fixes hold on `c78ce99` and found no regressions or new defects
within the reduced parameter budgets run. No `D11-observability-n` entries
are raised this round.

## Not covered (time-boxed out; do not read as clean)

- Prior V1/V2/V5/V6/V7 (round-9 observability attacks) — not re-run.
- B/C/D/F run at reduced N (60 vs the requested ≥300/≥500) — property
  held at this N but is not proven at the requested scale.
- v2 fixture upcast matrix for `done`/`error`/user records (only `after`
  was exercised).
- lane restore ordering; `machine_hash` coverage of `scheduled_sends`.
- mixed delayed+zero-delay chain interaction (only pure cycles tested).
- start()-descent-settle wait under 100 concurrent starts with `always`
  cycles.
- concurrent restore of 200 v3 snapshots with `scheduled_sends`.
- #212 rule matrix: `sendTo` child / `cancel(id)` / delayed-raise-from-
  external-send vs. `after` parity (only self-raise ping-pong tried).
- #214 restore-strict matrix (only the upcast/forgery pair above).
- determinism (50× trace comparisons), hash-seed.
- observability sub-items: `on_invalid_event` exactly-once on restore,
  `last_error`, receipt semantics, #216 warning-text exhaustiveness.
- security: strict_config bypass beyond the one `x-` spot check; forged
  `lane` field; redaction.
- 12-minute soak.

## Verdict

No regressions from round-10's fixes were found on `c78ce99` in the
attacks run. #212 (timer semantics for delayed self-sends), #213
(`scheduled_sends` v3 round-trip), #214 (v2 upcast trust boundary, spot-
checked against one forgery shape), and #216 (top-level unknown-key
policy) all behaved as documented under the reduced-scale probes above.
The result is a **partial, time-boxed confirmation, not a clearance** —
the Not Covered list above is substantial (full-scale fuzzing, the #212
rule matrix beyond self-raise, restore-strict beyond one upcast/forgery
pair, determinism, soak) and should be run before treating this round as
fully re-verified.
