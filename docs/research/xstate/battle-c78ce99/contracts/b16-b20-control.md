# B16–B20 control machines end-to-end on `c78ce99`

Commit `c78ce99` (unreleased 0.8.1; `__version__` still reports `0.8.0` — keyed
on the commit). Round-10 fixes **#212–#216** in scope, including the two
semantic reversals: #212 (a `raise(delay=)` self-send is a **timer**, not a
chain — supersedes #206) and #213/#214 (**snapshot layout v3** with
`scheduled_sends`, strict restore, per-record `lane`).

Corrected JSON carried byte-identical from `battle-19cb1f1/contracts/`
(`B16`–`B20.machine.json`). Mandatory config present in every file:
`actionErrorPolicy: rollback`, `guardErrorPolicy: raise`, `strictTargets: true`,
`strict: true`, `onUnhandled: defer` (B16/B17/B19/B20) and `error` (B18, the
control machine). Every run uses `SimulatedClock`, a bounded inbox
(`max_queue_size=64`, `OverflowPolicy.RAISE`) on the async engine, and a
`PluginBase` stub standing in for the project error hooks, including
`on_invocation_stranded` (#207) and `on_invalid_event` (#159).

**Pass 1 = every service `async def`; pass 2 = every service plain `def`.**
The service-kind axis is **flat again this round**: not one check changes
verdict between the two spellings, on any of the 71 checks per lane.

## Headline

| | result |
|---|---|
| `create_machine` B16–B20 under **`strictConfig`** (`p0`) | **20/20 clean** per lane — zero unknown top-level keys, and a planted `actionErrorPolicyy` typo is refused on all five |
| B16/B17 invariants (`p1`) | 11/14 PASS per lane; **3 FAIL = C-04, both lanes** |
| B18/B19/B20 invariants + 3 mandated drives (`p2`) | 26/27 PASS per lane; **1 FAIL = C-06, both lanes** |
| Sharp edges (`p3`: C-07b, #207, #204, parity) | **13/13 PASS** per lane |
| Round-10 timer axis (`p4`: #212, #213, #214, #205) | **10/10 PASS** per lane |
| Snapshot/restore at every quiescence, **v3-asserted** | **clean on every drive**, zero drift, zero mid-step refusal, `version == 3` and `scheduled_sends` present on every payload |
| Sync parity (configuration + action trace + service-call trace) | **5/5** |
| **LIBRARY findings** | **0 new** |

**Every B16–B20 failure on this commit is still OURS.** The library cleared all
five machines on both engines and both service spellings, and the four checks
that fail are the same three catalogue defects carried forward from round 9,
unchanged in shape.

## #216 `strictConfig` — our catalogue is clean

The new gate is the one thing that could have turned our own JSON into a build
failure, so it was the first pass. Three builds per machine per lane:

1. as-carried JSON with `create_machine(..., strict_config=True)`
2. JSON plus a config-level `"strictConfig": true`
3. a negative control: `actionErrorPolicy` renamed to `actionErrorPolicyy`

All five machines build clean under (1) and (2) — **no unknown top-level key in
any catalogue file**, so there is no our-contract defect here. Top-level keys in
use across B16–B20 are exactly `id`, `initial`/`type`, `context`, `states`,
`actionErrorPolicy`, `guardErrorPolicy`, `onUnhandled`, `strict`,
`strictTargets`, `spawnBlockingTimeout` — every one of them in
`KNOWN_MACHINE_KEYS`.

The negative control is refused on all five with a precise message, e.g.

```
InvalidConfigError("Machine 'kill_switch' has unknown top-level key(s)
'actionErrorPolicyy' (did you mean 'actionErrorPolicy'?). Unknown keys are
ignored by the parser, so a misspelled policy silently reverts to its
default. …")
```

This is worth a constraint of its own: **we should ship `strictConfig: true` in
every catalogue machine**. A silently-degraded `actionErrorPolicy` on a control
machine is a rollback that never happens; the typo is now a build error for one
line of JSON. Script: `p0_build.py`.

## The round-10 timer axis: our charts do not use it, so we built the shape we would ship

A scan of all five machines for `after` blocks and for `raise` actions carrying
a `delay` returns **zero hits**: B16–B20 as catalogued have no chart-level
timers at all. Every deadline in the control charts is an *external* event
(`ELEVATION_DEADLINE`, `IDLE_DEADLINE`, `ABSOLUTE_DEADLINE`, `EXPIRY_DUE`), armed
by a wrapper action (`schedule_expiry_deadline`, `schedule_elevation_deadline`)
that the catalogue leaves unimplemented.

So #212 and #213 cannot be exercised by the charts as written. Rather than skip
the axis, `p4_timers.py` re-does **B20's expiry deadline** — the most plausible
thing we would move into the chart — in both spellings and tests each:

- `p4a` B20 with `locked.after[5000] → clear`: fires at 5001 ms on the
  `SimulatedClock` and not at 4999 ms. Correct.
- `p4b` B20 with a 1 ms `raise(delay=)` self-ping on `locked`,
  `maxIterations: 5`: **31 beats over 15 ms of clock, `status == "running"`,
  `i.error is None`.** Under the superseded #206 rule this was a debt of the
  arming step and would have tripped `RunawayChainError` at 5 beats. **#212 is
  live and correct**: a self-paced heartbeat of any period is a periodic
  process, exactly as `after: 1` has always been.

This is the reversal that matters most to us, and it is worth stating plainly:
**a `raise(delay=)` poller is now a legitimate design for our charts.** Under
round 9's rule we had written it off.

### #213 / #128 — the two timers have two different persistence contracts

This is the one genuinely new hazard this round, and it is **NEEDS-WRAPPER**,
not a library defect. Both behaviours are documented; the danger is that they
look interchangeable in a chart and are not across a restart.

| | `raise(delay=)` (#213) | `after` (#128) |
|---|---|---|
| in v3 `scheduled_sends` | **yes**, with `remaining_ms` and `send_id` | **no** — absent by design |
| re-armed by `start()` | **automatically** | only with `from_snapshot(..., restart_timers=True)` |
| delay on restore | the **remainder** | **from zero**, elapsed portion lost |
| default restore, state whose only exit is the timer | resumes correctly | **parked forever** |

Measured, both lanes: a `raise(delay=4000)` snapshotted 1000 ms in records
`{"kind": "event", "type": "PING", "remaining_ms": 3000.0, "send_id": "beat"}`
and, after restore, fires at +3001 ms and not at +2999 ms. The same deadline
written as `after: 5000` records `scheduled_sends: []`, and the restored
machine sits in `locked` after **50 seconds** of simulated clock — 10× the
deadline. With `restart_timers=True` it recovers, but only after a **full**
5000 ms, not the 4000 ms remaining.

`has_dormant_timers` is `True` on the restored interpreter in the parked case,
so the condition is detectable — that is the flag our restore path must check.

Repro: `repro/cv78_after_lost_on_snapshot.py` → `CONFIRMED (NEEDS-WRAPPER)`,
carrying its own positive control so the asymmetry is proved rather than
asserted.

### #214 / #205 — strict restore

- A v2 payload (version forced to 2, `scheduled_sends` stripped) is refused at
  `from_snapshot(..., minimum_version=3)` with
  `SnapshotVersionError("Snapshot version 2 is below the caller's
  minimum_version=3 …")`. Both lanes.
- A forged user event planted in a restored payload's `pending_events` does not
  drive the machine: the configuration after restore is unchanged
  (`risk_lockout.locked`), nothing is executed, no exception escapes. The
  `strict` check on the restore path holds.

**Every snapshot taken anywhere in this round's harness is now asserted to be
`version == 3` with a `scheduled_sends` key present** — across all B16–B20
drives, both lanes, at `t0` and after every macrostep. Zero violations.

## The three catalogue defects: all still present, all unchanged

Re-tested against the **corrected** JSON. None was fixed by a later contracts
pass, and none is affected by any round-10 change. All are defects on *any*
runtime.

### C-04 — B16 elevation outlives the session · **STILL PRESENT** · OUR-CONTRACT · Blocker

`states.elevation.elevated.on` lists `ELEVATION_DEADLINE`, `STEP_UP_OK` and
`REVOKE` — and nothing else. The `auth` region is revoked by **four** distinct
events; three never reach the parallel `elevation` region:

| kill event | final configuration | still elevated |
|---|---|---|
| `REVOKE` | `auth.revoked`, `elevation.normal` | no |
| `LOGOUT` | `auth.revoked`, **`elevation.elevated`** | **yes** |
| `IDLE_DEADLINE` | `auth.revoked`, **`elevation.elevated`** | **yes** |
| `ABSOLUTE_DEADLINE` | `auth.revoked`, **`elevation.elevated`** | **yes** |

A revoked session still carries the elevated-privilege tag that B17
`ENABLE_REQUESTED` and B18 `RELEASE` both gate on. Identical on both spellings
and on the sync engine.

Repro: `repro/cv78_c04_elevation_survives.py` → `REPRODUCED … ['LOGOUT',
'IDLE_DEADLINE', 'ABSOLUTE_DEADLINE']`.

The two companion failures are the same root cause from other angles:

- **C-04b** `INV-c every step-up audited` — the second `STEP_UP_OK` takes the
  `elevated → elevated, reenter: true` arm whose `actions` omit
  `audit_step_up`. A re-elevation is unaudited. **Medium.**
- **C-04c** `INV-d revoked terminal` — after `REVOKE` the machine is
  `auth.revoked` + `elevation.normal`, but a later `STEP_UP_OK` is still live in
  the `elevation` region and re-elevates a dead session. Post-revoke
  `MFA_OK`/`REQUEST` are correctly `deferred` (the `auth` region is final); the
  elevation region has no corresponding terminal state.

**Fix (ours, one edit):** hoist the four revocation events onto the **root** so
both regions see them, and add `audit_step_up` to the re-enter arm.

### C-07b — B18 kill switch bricked by a guard-denied `RELEASE` · **STILL PRESENT** · OUR-CONTRACT · Blocker

`engaged.on.RELEASE` has exactly one arm, guarded by `owner_and_elevated`. When
the guard denies, **no transition is selected at all**, so the event is
*unhandled* — and B18 is the machine carrying `onUnhandled: "error"`, which
makes it fatal. Observed, both spellings:

1. `ENGAGE` → `kill_switch.engaged` (trading blocked). Correct.
2. Operator presses `RELEASE` without elevation — an ordinary mistake. `send()`
   **returns normally, success-shaped, raising nothing**; the machine goes
   `status = "error"` with `UnhandledEventError`.
3. The operator elevates and presses `RELEASE` **correctly**. `send()` again
   returns normally; the event is dropped. Final configuration:
   **`kill_switch.engaged`**.

The kill switch is stuck trading-blocked and cannot be released in-process. One
wrong button press is unrecoverable.

Repro: `repro/cv78_c07b_killswitch_bricked.py` → `REPRODUCED … ['async def',
'def']`.

The library behaves exactly as documented at each step — the **policy choice is
the defect, and it is ours**. The unhandled disposition is reported to the hook
as `("RELEASE", "errored")` and `i.error` names the exception. What remains as a
Low library *observation* (not a finding) is that `send()` is still
success-shaped for the sender on a dropped event.

**Fix (ours):** drop `onUnhandled: "error"` on B18 (use `defer`, as the other
four do), **and** give `RELEASE` an unguarded fall-through arm that audits the
denial and stays in `engaged` — the B17 `ENABLE_REQUESTED` / B20
`OVERRIDE_REQUESTED` shape, which both pass this exact test.

### C-06 — B19 `stale_lockout` cannot be cleared by an operator · OUR-CONTRACT · High

`stale_lockout` (`tags: [account_locked, critical]`, entry locks the account and
pages) handles **`RECONNECTED` only**. `OPERATOR_RESOLVED` is `deferred` and the
account stays locked with `deferred_count = 1`. On a venue that never
reconnects cleanly the only exit is a process restart. Both lanes, both engines.
Fix is ours: add an `OPERATOR_RESOLVED` arm.

## The mandated drives

All driven explicitly on both spellings; all results identical to round 9,
cell for cell.

**(1) rollback + `invoke.onDone`.** Driven on B18 (`page_owner` raises,
`maxIterations: 5`) and B19 (`store_divergences` raises, `maxIterations: 25`).
Both trip, both lanes, plateau **exact**:

| machine | limit | service calls at plateau | resting state | `last_error` |
|---|---|---|---|---|
| B18 | 5 | **7** = limit + 2 | `kill_switch.flattening` | `RunawayChainError` |
| B19 | 25 | **27** = limit + 2 | `reconciliation.diffing` | `RunawayChainError` |

Polled to convergence, not sampled: the count is identical at two successive
plateaus and identical between `async def` and `def`. **#207 stays live**:
`on_invocation_stranded` fires with the real pair
(`("kill_switch.flattening", "fl", RunawayChainError(…))`,
`("reconciliation.diffing", "diff", …)`), `RunawayChainError.stranded` carries
the invoke ids, `has_dormant_invocations` is `True`, and `pending_invocations()`
returns the `PendingInvocation`. The "stranded or just slow?" ambiguity remains
closed.

**(2) `always` → invoked child.** Both directions correct.
*Positive:* B18 `engaging.always` (guard true) rolls into `cancelling`, whose
`cx` invoke **does** arm — `cancel_all_working_orders` then
`flatten_all_positions` are called and `engaging` is absent from the final
configuration. B19's `reporting.always → divergent` likewise fires with its
alert.
*Negative — the #204 `statesToInvoke` rule:* an unconditional
`always: [{target: "#kill_switch.engaged"}]` on `cancelling` means the state is
entered and exited inside one macrostep, and **the service is never submitted**:
`svc_calls == []`, final state `kill_switch.engaged` — async engine and
`SyncInterpreter`, `async def` and `def`. Four lanes, four clean results.

**(3) B18 `send_priority` under a self-generated chain.** With a runaway
`rollback + onDone` chain open (`maxIterations: 50`, `page_owner` raising), 12
`send_priority("RELEASE")` presses against the live chain: **12/12 accepted, 0
shed as `chain_budget`**, zero exceptions, both spellings. The only drops
recorded are `("RELEASE", "not_running")` **after** the interpreter had stopped
— a different and correct reason. Round 8's Blocker R8-01 stays closed.

## Snapshot / restore and sync parity

Every `drive()` snapshots at `t0` and after **every** macrostep, asserts the
payload is `version == 3` carrying `scheduled_sends`, restores into a **fresh**
machine built from the same JSON with a fresh stub **under
`minimum_version=3`**, and compares configuration + context + status + deferred
count. Zero drift, zero `SnapshotMidStepError`, zero version violations across
all B16–B20 drives on both spellings.

Sync parity is **configuration + full action trace + full service-call trace**,
5/5 on all five machines. (Round 9's harness correction still applies: sync
stubs must use `def` services; the library refuses `async def` on
`SyncInterpreter` loudly with `NotSupportedError` rather than parking.)

## Findings

| id | class | sev | machine | status |
|---|---|---|---|---|
| C-04 | OUR-CONTRACT | **Blocker** | B16 | **still present**, reproduced both lanes |
| C-04b | OUR-CONTRACT | Medium | B16 | still present (unaudited re-elevation) |
| C-04c | OUR-CONTRACT | Medium | B16 | still present (post-revoke re-elevation) |
| C-07b | OUR-CONTRACT | **Blocker** | B18 | **still present**, reproduced both lanes |
| C-06 | OUR-CONTRACT | High | B19 | still present |
| CV78-T1 | **NEEDS-WRAPPER** | High | any chart with `after` | `after` deadlines are not persisted; default restore parks the state, `restart_timers=True` restarts from zero. Check `has_dormant_timers` on every restore. |
| — | LIBRARY | — | — | **0 new findings** |

### Constraints this round proposes

- **CV-C49** Ship `"strictConfig": true` in every catalogue machine. Verified
  to build clean on all five today; it converts a future policy typo from a
  silent permissive default into a build error.
- **CV-C50** A `raise(delay=)` self-paced poller/heartbeat is now a **permitted**
  chart design (#212 reversal). It is also the *preferred* spelling for any
  deadline that must survive a restart, because it is the only one v3 persists.
- **CV-C51** Every restore path must pass `minimum_version=3` and must check
  `has_dormant_timers` (and `has_dormant_invocations`) before declaring the
  machine live; if either is true, either re-arm deliberately with
  `restart_timers=True` or fail the restore loudly.

## Scripts

All standalone or harness-backed, run from `battle-c78ce99/contracts/`:

| script | what |
|---|---|
| `cvc78.py` | harness — SimulatedClock, bounded RAISE inbox, plugin stub, **v3 snapshot audit on every roundtrip** |
| `p0_build.py` | #216 `strictConfig` build pass + typo negative control |
| `p1_b16_b17.py` | B16/B17 happy path + invariants |
| `p2_b18_b20.py` | B18/B19/B20 invariants + the three mandated drives |
| `p3_sharp.py` | C-07b, #207 stranding, #204 no-arm, sync parity |
| `p4_timers.py` | #212 / #213 / #128 / #214 / #205 timer + restore axis |
| `repro/cv78_c04_elevation_survives.py` | C-04, standalone |
| `repro/cv78_c07b_killswitch_bricked.py` | C-07b, standalone |
| `repro/cv78_after_lost_on_snapshot.py` | the `after`/`raise(delay=)` persistence asymmetry, standalone, with positive control |

Every driver takes `async` or `def` as `argv[1]` and was run both ways.
Results JSON in `results/`.
