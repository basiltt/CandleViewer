# 58 — Round-10 findings register (`main` @ `19cb1f1`, unreleased 0.8.1)

Inputs: round-10 battle findings (`battle-19cb1f1/**`), carry-forwards re-run
verbatim from `battle-f28719c` / `battle-6db65d8`, `O-*` from
`57-r10-diff-review.md`, regressions from `55-r10-regression.md`.

Method, per the financial-OMS standard: every finding's repro was re-run fresh
from neutral cwd `<home>` with the round-10 venv, 120 s cap, both
service spellings (`def` / `async def`) where the finding touches a service or
action; source read at the cited `file:line`; then classified and merged by
root cause into `R10-nn`. Nothing is counted that did not reproduce in this
pass. Library source was never modified.

Classification vocabulary: **LIBRARY-DEFECT**, **DOC-DEFECT**,
**HARNESS-ERROR**, **DESIGN-CONSTRAINT**, **OUR-CONTRACT-DEFECT**,
**DUPLICATE**, **FIXED/WITHDRAWN**.

---

## Summary

| id | sev (OMS) | class | title |
|---|---|---|---|
| R10-01 | **Blocker** | LIBRARY-DEFECT | Engine-event provenance is type identity; `done`/`error`/`after` forgeable 7 ways, in-process and via `restore_event` |
| R10-02 | **High** | LIBRARY-DEFECT | `onDone` targeting its own source state never re-arms the invoke; machine parks dormant, silently |
| R10-03 | **High** | LIBRARY-DEFECT | `#206` converts a self re-arming timer into a chart that dies at `maxIterations` (behaviour break, async engine) |
| R10-04 | Medium | LIBRARY-DEFECT | An in-flight delayed self-`raise` is silently lost across snapshot/restore |
| R10-05 | Medium | LIBRARY-DEFECT | Restore path bypasses `strict` and drops lane provenance; a persisted fired `after` is now refused, not demoted (migration cliff) |
| R10-06 | Medium | DOC-DEFECT | `#209`'s "all three lanes agree at limits 1–25" is false on engine-work-only charts; gap grows with the limit |
| R10-07 | Medium | LIBRARY-DEFECT | Unknown top-level config keys accepted silently; a misspelled safety policy downgrades to default |
| R10-08 | Low | LIBRARY-DEFECT | Call-site `QueueOverflowError` refusals fire no `on_event_dropped` (99.3 % of shed invisible) |
| R10-09 | Low | LIBRARY-DEFECT | `SnapshotMidStepError` from an invoked child's entry action reports `child=False` |
| R10-10 | Low | DOC-DEFECT | CHANGELOG self-contradicts on the runaway plateau (`+2` vs `+3`); code and tests say `+2` |
| R10-11 | Low | DOC-DEFECT | `#208`'s "refuses `ok` over an illegal configuration" path is unreachable on a live machine |
| R10-12 | Low | LIBRARY-DEFECT | `after` does not fire under `SimulatedClock.increment()` (pre-existing, not a round-10 regression) |
| R10-13 | Low | LIBRARY-DEFECT | Chain trip not surfaced on `on_error` / `interpreter.error`; `last_error` cleared on the async lane, retained on `def` |
| R10-C1 | **Blocker** | OUR-CONTRACT-DEFECT | B16 elevation region outlives the session |
| R10-C2 | **Blocker** | OUR-CONTRACT-DEFECT | B18 `onUnhandled:"error"` + sole guarded `RELEASE` bricks the kill switch |
| R10-C3 | High | OUR-CONTRACT-DEFECT | B19 `stale_lockout` has no operator escape hatch |
| R10-C4 | High | OUR-CONTRACT-DEFECT | Kill/cancel deferrable for the full service duration on invoking states |
| R10-C5 | Medium | OUR-CONTRACT-DEFECT | B16 re-elevation via the `elevated→elevated` re-enter arm is unaudited |
| R10-D1 | — | DESIGN-CONSTRAINT | rollback + `invoke.onDone` re-arms a side-effecting service (documented; plateau pinned) |
| R10-D2 | — | DESIGN-CONSTRAINT | Invoke-bearing states with an escape transition must use `async def` services (#193) |
| R10-D3 | — | DESIGN-CONSTRAINT | Hand-built `AfterEvent` refused at the inbox (#203) — correct; wrapper timeout supervisors need a new route |
| R10-D4 | — | DESIGN-CONSTRAINT | `send()` stays success-shaped after `status="error"` |
| R10-H1 | — | HARNESS-ERROR | `send(wait=True)` treated as "the service chain finished" |

Withdrawn as fixed at `19cb1f1`: `D9-fuzz-3/R9-03`, `D9-fuzz-4/R9-08`,
`D9-fuzz-2/R9-09` (on its named shape), `CV-F28-01`, `CV-F28-02`. Recorded as
measurement, not a finding: `D4-D6-plateau`, `O-3`, `O-4`, `O-7`, `O-8`.
Withdrawn as non-reproducing noise: `R9-09-verify`.

---

## R10-01 — Engine-event provenance is a Python type, not a capability

**Severity (OMS): Blocker.** Class: **LIBRARY-DEFECT**. Re-verified this pass.

Merges: `D10-fuzz-1`, `D10-concurrency-1`, `D10-concurrency-3`,
`D10-semantics-1`, `D10-persistence-1`, `R9-01-recheck`,
`D9-fuzz-1 / R9-01` (carry-forward, unchanged).

### What reproduces

All runs from neutral cwd `<home>`, both service kinds where a service
is involved, both engines where the probe covers them.

| repro | result this pass |
|---|---|
| `battle-19cb1f1/fuzz/n1_after_forgery.py` | 4 / 5 vectors FORGED; control V1 (public `AfterEvent`) correctly `REFUSED:UnknownEventError` |
| `battle-19cb1f1/concurrency/t1_after_provenance_forgery.py` | `FAIL` — 8/8 forged cells reach `['t1.late']` against a declared `after:{60000:…}`; control refused in all cells |
| `battle-19cb1f1/concurrency/s6_restore_event_forgery_minimal.py` | `FAIL` — forged `engine:true` record drove a real `onDone`, context `{'v':'FORGED'}`, genuine result discarded |
| `battle-19cb1f1/persistence/u2_after_forgery.py` | `FAIL` — vectors C/D/E/F all `system=True`, `fired=1`, 60 s timer fires instantly under `strict:True` + `onUnhandled:"error"`; controls B and G refused |
| `battle-19cb1f1/semantics/repro/d10_sem_1_after_replace.py` | `REPRODUCED` on both kinds — `_replace` re-types a 5 ms settle timer's own event into a 24 h margin-call descriptor; `oms.margin.called` reached, `last_error=None` |
| `battle-f28719c/fuzz/g7_forgery_repro.py` (carry-forward) | 3 / 4 vectors succeed, unchanged |

Seven distinct vectors across two event families: import path
(`events.engine_after` / `engine_done`), `type(held_genuine_event)(…)`,
`NamedTuple._replace`, `pickle` round-trip, `copy.deepcopy`, a hand-written
snapshot record carrying `"engine": true`, and the private class imported
directly as an ordinary module attribute.

### Root cause (source read)

- `events.py:281-283` — `is_system_event` is `isinstance(event, _ENGINE_MINTED_TYPES)`.
- `events.py:579` — `class _EngineAfter(AfterEvent): __slots__ = ()`; likewise
  `_EngineDone` / `_EngineError`. A bare subclass with **no unforgeable state**.
- `events.py:555-565` (comment block) — the design deliberately preserves the
  subclass through `_replace`, `pickle` and `deepcopy` so persistence works.
  That same preservation is the forgery primitive.
- `events.py:604-615` — `engine_done` / `engine_error` / `engine_after` are
  module-scope public factories; the underscore prefix is convention only.
- `events.py:414` — `trusted = record.get("engine") is True` in
  `restore_event`, then `_restore(..., trusted=trusted)` mints the private
  subclass from a plaintext boolean the blob writer controls.
- `base_interpreter.py:4624` — `#203` changed the `after` selection gate to
  `isinstance(event, AfterEvent) and is_system_event(event)`, i.e. it routed a
  second event family through the already-broken primitive.

### Why Blocker for an OMS

The `after` half is strictly more powerful than the completion half: firing a
timer needs no in-flight invocation to impersonate, any state carrying a timer
is reachable, and the transition's `actions` run. The `_replace` vector needs
no private name at all — an `after` transition's own actions are handed the
genuine `_EngineAfter`, and a plugin hook sees engine events by design. Under
`strict:True` + `onUnhandled:"error"` — our own hardened configuration — a
24-hour margin-call deadline fires in 250 ms with `last_error=None`.

`#203` was round 9's answer to the round-8 Blocker. It did not close it.

### Fix direction (for upstream)

Provenance must be a value the engine **mints and holds**: a per-interpreter
nonce compared by identity against the timer registration / invocation
actually outstanding, checked at selection time. Not a type, and not a boolean
in the payload. One such change closes both event families and the restore
path together.

---

## R10-02 — A self-targeting `onDone` never re-arms the invoke; the machine parks dormant and silent

**Severity (OMS): High.** Class: **LIBRARY-DEFECT**. Reproduced this pass.

Merges: `D10-concurrency-2`.

### What reproduces

- `concurrency/t4_self_target_ondone_never_rearms.py` → `FAIL`. SELF shape
  (`invoke` on `work`, `onDone:{target:'work'}`): 1 entry, 1 submit, dormant
  `True`, `last_error=None`, `status='running'`.
- `concurrency/t3b_stranded_minimal.py` → `FAIL` on all supported
  engine × kind cells: wedged in `['t3b.work']` with the stranded hook silent
  (`0` fires).
- `concurrency/t3_stranded_hook_storm.py` (100 concurrent machines):
  `n_stranded == 0` for 100/100, `dormant == True` for 100/100.
- Controls behave: the HOP shape (`onDone → hop --always--> work`) re-arms 11
  times and trips `RunawayChainError`; the CLEAN control is not dormant.

### Root cause (source read)

`base_interpreter.py:4952` — `self._states_to_invoke.append(state)` is reached
**only** from state entry (`_enter_state`). `base_interpreter.py:3898` removes
the state on exit. `base_interpreter.py:4958` `_arm_pending_invokes()` drains
that list at settle.

Under SCXML 3.12 a transition **with a target** exits and re-enters its source
even when `source == target`. Here the state never exits, so it is never
re-recorded, so there is nothing to arm.

Observability compounds the defect: `base_interpreter.py:1921`
`_stranded_by_cut` inspects only events **cut by the chain budget**. In this
shape nothing is cut because nothing is generated, so `#207`'s brand-new
detection is attached to the wrong event and the dormant invocation is
invisible to `on_invocation_stranded`, to `last_error` and to `status`.

### Why High for an OMS

The natural spelling of a poll/retry loop — invoke, on completion re-enter
myself — silently becomes a one-shot. There is no error, no hook, no status
change: a fill-poller stops polling and the machine still reports `running`.
Detection today requires polling `has_dormant_invocations()` on a timer.

**Wrapper constraint:** never target an invoking state from its own `onDone`;
always hop through an intermediate state with an `always` back. Assert
`has_dormant_invocations() is False` in the supervisor's health sweep.

---

## R10-03 — `#206` converts a self re-arming timer into a chart that dies at `maxIterations`

**Severity (OMS): High.** Class: **LIBRARY-DEFECT** (undeclared behaviour break).
Source: `O-1` (`57-r10-diff-review.md`). Confirmed by diff read + probes.

`interpreter.py:2206-2247` treats a delayed send to self issued from an action
as a debt of the arming step (`_chain_owed_sends`, `_armed_this_step += 1`) and
charges the firing as engine work (`_deliver_priority(...,
engine_completion=self_armed)`), incrementing `_raise_depth`. Nothing in that
path is time-aware: **wall-clock time between beats never ends the chain.** The
chain clears only on "raised nothing, armed nothing, owes nothing", and a
heartbeat re-arms in its own entry action, so that test is false on every lap.

`probes/main-19cb1f1/p2_delayed_selfsend_heartbeat.py`, 30 ms heartbeat,
`maxIterations: 8`: async `def` 47 beats → **9 beats + `RunawayChainError`**;
async `async def` 48 → **9 + `RunawayChainError`**; sync `tick()` 30 → 30
(unchanged); async with external traffic every 4th sample 47 → 45 (rescued).
`p3_delayed_selfsend_scope.py` at `maxIterations: 4` gives **5 beats at 30 ms,
100 ms and 250 ms alike** — the charge is purely per-lap, independent of period.

The changelog describes the fix in terms of a 1 ms ping-pong cycle and does not
name it as a break for periodic work. It is one: `raise(delay=)` self-paced
heartbeats and pollers — the standard chart idiom for periodic processes — now
stop after `maxIterations` beats on the async engine.

**Wrapper constraint (CV-C47):** no `raise(delay=)` self-paced periodic work on
the async engine. Drive periodic work from an external timer, or from the
sync engine's `tick()`.

---

## R10-04 — An in-flight delayed self-`raise` is silently lost across snapshot/restore

**Severity (OMS): Medium.** Class: **LIBRARY-DEFECT**. Merges `D10-persistence-2`.

`persistence/u4_delayed_debt.py` parts B/C, both kinds, re-run this pass:
state `a` entry arms `{"type":"raise","params":{"event":"PONG","delay":300}}`;
snapshot 50 ms into the window yields `pending_events=[] deferred=[]`. The live
machine reaches `['debt.b']` once the delay elapses; the restored machine is
still `['debt.a']` after 600 ms. Part D shows an **external** delayed send
survives — the asymmetry is confirmed in the same run.

Root cause (`interpreter.py:1480-1497`): `_snapshot_pending_events` reads the
priority queue plus the inbox deque only, so a timer that is armed-but-not-yet
-fired has no representation in the snapshot at all — unlike a *fired* `after`,
which `#107` persists via the priority lane. `#206` made the delayed self-send
a debt of the arming step; a snapshot discharges that debt with no hook, no
warning and no error. Restore does not re-run entry, so the machine resumes
into a state whose only exit was the lost event.

---

## R10-05 — The restore path bypasses `strict` and drops lane provenance; a persisted `after` is now refused rather than demoted

**Severity (OMS): Medium.** Class: **LIBRARY-DEFECT**.
Merges `D10-persistence-3`, `D10-semantics-2` (= `D9-semantics-2 / R9-13`),
and `O-2` (migration cliff).

Two symptoms, one code path.

**(a) `strict` is not applied to restored events.**
`battle-f28719c/semantics/p_persistence.py::P2` re-run at `19cb1f1`:
`strict/bare_done` → `status=running err=None recv=['done.invoke.q']`;
`strict/plain_undeclared` → `status=running err=None recv=['BOGUS']`.
`onUnhandled:"error"` does catch both. `_check_strict` runs at the `send()`
call site (`base_interpreter.py:1767`); the restore path re-enqueues via
`_enqueue_restored` → `_put_inbox` (`interpreter.py:1499-1500`), bypassing it.
This contradicts the documented restore contract at `events.py:403-414`.

**(b) The priority lane is not restored as a lane, and the demotion is now a
refusal.** `persistence/s2_lane_provenance_roundtrip.py` part A: live pending
`['EXT','INB']` round-trips in order, but records carry only
`['kind','payload','type']` and the restored `_priority_queue` is `[]`
(`interpreter.py:356` holds `Tuple[AnyEvent, bool]`; `:1497` drops the flag).
`persistence/n1_priority_lane_107.py` route A: snapshot
`pending_events=['after.1000.lanes.waiting'] kinds=['after']` (persisted per
`#107`), restored `states=['lanes.waiting'] fired=0` — *replayed on restore =
False*, where the same probe reported `True` at `6db65d8`, `cec108b` and
`221ce7c`.

`O-2` is the migration face of (b): a 0.8.0-written record has `kind:"after"`
(v2 shape, so the v1 name-based fallback does not catch it) but no `engine`
flag, so it restores as a public `AfterEvent` which `#203`'s provenance gate
then refuses. The deadline is **dropped rather than demoted** — no raise, no
warning, nothing in `last_error`, and `has_dormant_timers` does not cover it
because the event was already in the persisted inbox rather than awaiting
re-arm. `p1_after_provenance_migration.py` Q1: `t.late` at `f28719c` →
`t.wait` at `19cb1f1`.

The security direction of `#203` is right; the failure mode is not. A refused
restored deadline must be loud.

**Wrapper constraint (CV-C48):** 0.8.0-era snapshots containing `after` records
must be migrated (or the deadlines re-armed explicitly) before restore.

---

## R10-06 — `#209`'s "all three lanes agree at limits 1–25" is false on engine-work-only charts

**Severity (OMS): Medium.** Class: **DOC-DEFECT**. Merges `D10-fuzz-2`;
supersedes the general half of `D9-fuzz-2 / R9-09`.

`fuzz/n6_shrunk_repros.py` section D2 re-run this pass (`always` + zero-delay
`raise` cycle, `maxIterations` swept 1–25): **24 / 25 limits DIFFER.**
mi=1 sync 4 / async 6; mi=3 sync 10 / async 12; mi=10 sync 23 / async 33;
mi=19 sync 41 / async 60. Both lanes trip with `RunawayChainError` at every
limit. Surfaced by `n5_livelock_receipt_fuzz.py` P3 (12 engine-work-only cells
out of 352 configs).

The chart has no timers and no delayed sends, so the `#206` carve-out
(timer-paced self-sends are caller-tick-driven on `SyncInterpreter`) does not
apply — every step is engine work the chain budget is defined to charge. The
two engines charge the `always` settle step differently relative to `raise`:
async grows ~`3·mi+3`, sync ~`2·mi+3`.

`#209` genuinely fixed the two shapes it measured — `g2_lap_parity.py` def-lane
mismatches 13 → 0, and all 26 remaining mismatches are the documented
`SyncInterpreter` + `async def` → `NotSupportedError` exclusion — and then
re-asserted the claim generally. At mi=25 the same chart is permitted ~47 %
more work on one engine than the other. The runaway budget is a safety control,
so an overstated guarantee about it is a doc defect worth fixing.

---

## R10-07 — Unknown top-level config keys accepted silently; the declared value is dropped

**Severity (OMS): Medium.** Class: **LIBRARY-DEFECT**. Merges `CV-19-W01`.
Carry-forward, unchanged from `6db65d8` and `f28719c`.

`gate/g9_build.py` case `cfg/unknown-key-diagnosed`:
`create_machine({..., 'spawnBlockingTimeoutMs': 1234})` (note the trailing
`Ms`) builds clean and `machine.spawn_blocking_timeout_ms` is `None`. Bad
*values* for *known* keys are still correctly refused with
`InvalidConfigError`; only unknown *keys* pass. FAILs on both lanes.

There is no whitelist validation of top-level config keys. For an OMS this is
material because the keys most likely to be misspelled are the safety
policies: a mistyped `actionErrorPolicy` or `guardErrorPolicy` silently
downgrades the policy to its permissive default with no diagnostic.

**Wrapper constraint:** validate the key set against a known whitelist before
calling `create_machine`.

---

## R10-08 — Call-site `QueueOverflowError` refusals fire no `on_event_dropped`

**Severity (OMS): Low.** Class: **LIBRARY-DEFECT**. Merges `D10-concurrency-4`
(= `D9-concurrency-2` = `D8-concurrency-5` = `D7-concurrency-3`, unchanged).

`concurrency/r9_observability_matrix.py --only=qf` re-run this pass: `FAIL`,
`queue_full: call-site refusals fire NO hook`. Prior run at `19cb1f1`:
`callsite_refusals 241414`, `loopside_refusals 1811`, `queue_full_hooks 1811`,
`loopside_hooked_exactly_once true`, `callsite_hooked false` — i.e.
241 414 / 243 225 (**99.3 %**) of refusals are invisible to the hook.

The bounded-inbox overflow path raises `QueueOverflowError` at the `send()`
call site without routing through the shed-notification path the loop-side drop
uses. Low severity only because the call-site raise is itself a loud, synchronous
signal; the defect is that a metrics pipeline built on `on_event_dropped`
under-reports the shed rate by two orders of magnitude.

---

## R10-09 — `SnapshotMidStepError` from an invoked child's entry action reports `child=False`

**Severity (OMS): Low.** Class: **LIBRARY-DEFECT** (diagnostic quality).
Merges `D9-fuzz-5 / R9-15` (= `D8-fuzz-5 / R8-14`, unchanged).

`battle-6db65d8/fuzz/r14_observability.py` section C re-run: both service kinds
report `REFUSED child=False` when the snapshot is attempted from inside an
invoked child machine's entry action. Sections A/B/D still PASS. The child
provenance flag is not propagated to the error constructed on the child's entry
path. **The refusal itself is correct** — only the attribution is wrong.

---

## R10-10 — CHANGELOG self-contradicts on the runaway plateau (`+2` vs `+3`)

**Severity (OMS): Low.** Class: **DOC-DEFECT**. Merges `R9-DOC-01`.

`CHANGELOG.md [Unreleased]`: the `#207` entry says the cycle "trips at exactly
`maxIterations + 2` on both lanes"; the `#210` entry says the test "asserts the
exact plateau (`maxIterations + 3`)". Observed in `g9_d2_storm.py` and
`g9_d2b_sweep.py`: limit **+2** at all 25 swept limits, both engines, both
service kinds, and 1002 at the default 1000. The library's own
`tests/test_round9_findings.py` asserts `limit + 2` at `:580` and `:643`.

Documentation-only typo in the `#210` sentence; code and tests agree on `+2`.
See also `R10-M1` below for the `+2` / `+3` decomposition, which is the likely
origin of the confusion.

---

## R10-11 — `#208`'s "refuses `ok` over an illegal configuration" path is unreachable on a live machine

**Severity (OMS): Low.** Class: **DOC-DEFECT**. Source: `O-5`. Verdict
**PLAUSIBLE** (not fully confirmed within the time bound).

`interpreter.py:1869-1884` adds, at receipt resolution, a branch guarded by
`step_error is None and self.status == "running" and not
self._configuration_is_legal()`. `p5_receipt_illegal_configuration.py` finds no
**false** error receipts (Q1 6/6 `ok`, Q2 2/2 `ok`, Q3's 39 error receipts are
genuine `RunawayChainError` settle trips identical at `f28719c`). Q4 is the
finding: a real `maxIterations` cut on a `raise`-storm reports `error is None`
i.e. `ok`, on **both** trees — because `_repair_configuration()` runs on every
settle trip (`interpreter.py:2064`, `sync_interpreter.py:1038`), so the
configuration is legal again before the receipt resolves.

Harmless and correctly conservative, but the changelog overstates it, and it is
an unexercised branch on the receipt hot path guarded by an O(states) recursive
walk that runs on **every** `wait=True` receipt with `step_error is None`.
Measure against `bench/` before adopting `wait=True` broadly on a hot lane.

---

## R10-12 — `after` does not fire under `SimulatedClock.increment()`

**Severity (OMS): Low.** Class: **LIBRARY-DEFECT** (or probe-harness artefact —
not isolated). Source: `O-6`. **Pre-existing, not a round-10 regression.**

`p1_after_provenance_migration.py` Q3: a `SimulatedClock` advanced 61 000 ms
past a 60 000 ms `after` leaves the machine in `t.wait` on **both** `f28719c`
and `19cb1f1` (including awaiting the awaitable `increment()` returns). Since it
is identical on both trees it is **not** caused by `#203`; Q2 proves the engine's
own `_fire` mints `_EngineAfter` correctly. Recorded because the brief asked
specifically whether `SimulatedClock` was a legitimate path broken by `#203`:
it was not. Whether this is a harness artefact (async settler attachment under
a freshly created loop) or a real defect in the deterministic-replay path needs
its own investigation.

---

## R10-13 — Chain trip not surfaced on `on_error` / `interpreter.error`; `last_error` lane-asymmetric

**Severity (OMS): Low.** Class: **LIBRARY-DEFECT**. Merges `F2`, `F3`.

`contracts/repro/r2_chain_trip.py` and `r6_stranded_hook.py`, `CV=async|def`: a
`RunawayChainError` is reported on `last_error` and via
`on_event_dropped(..., 'chain_budget')` only; `i.error` stays `None` and
`status` stays `running`. `#207` materially improves this — `stranded`,
`on_invocation_stranded`, `has_dormant_invocations`, `pending_invocations()`
and an ERROR log remove the stranded-vs-slow ambiguity — but the trip still
does not reach the error channel.

`contracts/repro/r5_lasterror_kind.py`: `last_error` is **cleared once settled
on the `async def` lane and retained on the `def` lane**. A supervisor sampling
`last_error` asynchronously rather than per step therefore sees the runaway on
`def` services and misses it on the *recommended* `async def` services.

**Wrapper constraint:** `CvErrorHooks` must implement `on_invocation_stranded`
and must sample `on_event_dropped(..., 'chain_budget')` rather than polling
`last_error`.

---

# Our-contract defects (chart bugs, not library defects)

## R10-C1 — B16: the elevation region outlives the session

**Severity (OMS): Blocker.** Class: **OUR-CONTRACT-DEFECT**.
Merges the four duplicate filings `F7`, `C-04` (×3 independent repros),
`CV-19-C04`, and `C-04c` (same root cause).

Re-run this pass: `contracts/repro/r8_c04_b16_elevation.py`, `CV=async|def` →
`STILL_ELEVATED_AFTER_LOGOUT=True`, resting in
`['session.auth.revoked','session.elevation.elevated']` with
`elevated_until_us=9999999`, `clear_elevated` never run. The `REVOKE` control
correctly lands `['session.auth.revoked','session.elevation.normal']`.
Corroborated by the standalone `repro/c04_elevation_survives_logout.py` and
`repro/cv19_c04_elevation_survives.py` (LOGOUT, IDLE_DEADLINE **and**
ABSOLUTE_DEADLINE), both engines, both service spellings.

`B16` is a parallel chart. `states.elevation.elevated.on` lists only
`ELEVATION_DEADLINE`, `STEP_UP_OK` and `REVOKE`. `LOGOUT`, `IDLE_DEADLINE`,
`ABSOLUTE_DEADLINE` and `MFA_TIMEOUT` revoke the `auth` region only, and
`auth.revoked` being `final` does not stop the sibling region — which also
still accepts `STEP_UP_OK`, so a dead session can be **re**-elevated (the
former `C-04c`). Any "is elevated" authorisation predicate — e.g. B18's
`owner_and_elevated` — therefore grants privilege on a dead session.

`B16.machine.json` is byte-identical to `B16.catalogue.json` (sha1
`9d8ad9937417`); no corrections pass ever touched it, and it is unfixed in the
corrected `battle-f28719c` JSON. **The engine follows the chart — not a library
defect.**

**Fix:** add `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE` / `MFA_TIMEOUT`
to `elevation.elevated` targeting `elevation.normal` with `clear_elevated`, and
give the elevation region a terminal state mirroring `auth.revoked` so
`STEP_UP_OK` cannot be taken after revocation. Preferably drive elevation
clearing off `auth` reaching `revoked`.

## R10-C2 — B18: `onUnhandled:"error"` plus a sole guarded `RELEASE` bricks the kill switch

**Severity (OMS): Blocker.** Class: **OUR-CONTRACT-DEFECT**.
Merges `F6`, `C-07b` (×3 independent repros), `CV-19-C07b`, and `CD-02`.

Re-run this pass: `contracts/repro/r7_c07b_b18_release.py`, `CV=async|def`,
`UNH=error` → `C-07b PRESENT=True`. `ENGAGE` → `engaged`, `running`. A
`RELEASE` from a non-elevated operator (guard denies) → `status=error`,
`last_error=UnhandledEventError`. The **subsequent legitimate** `RELEASE` from
an elevated operator → still `engaged`, `status=error`, `released=0`; the
library logs `dropping event 'RELEASE'`. `send()` returns `accepted` on all
three (see `R10-D4`). Setting `UNH=defer` fixes it.

`kill_switch.engaged`'s only `RELEASE` handler carries guard
`owner_and_elevated`; a denied guard selects no transition, so the event is
unhandled, and `B18`'s catalogued `onUnhandled:"error"` makes that fatal. The
round-6 Amendment-6 removal recorded in `28-statechart-catalogue.md` never
landed in the JSON — `onUnhandled:"error"` is still present in **all three**
contracts dirs (`3ed3099`, `6db65d8`, `f28719c`; sha1 `4e9e8a9b60be`,
unmodified). The same root cause produces `CD-02`: `kf_drives.py` D3 shows 39
async / 20 def subsequent drops under the catalogued policy, 0 under `defer`,
because `RELEASE` is declared only on `engaged` and not on the
`cancelling`/`flattening` chain states.

**The library behaves exactly as documented; the policy choice is the defect.**

**Fix:** drop `onUnhandled:"error"` from B18; give `engaged` an unguarded
`RELEASE` fallback that audits the denial as a no-op; declare `RELEASE` on the
invoking chain states.

## R10-C3 — B19: `stale_lockout` has no operator escape hatch

**Severity (OMS): High.** Class: **OUR-CONTRACT-DEFECT**. From `C-06`.

`n2_b18_b20.py` (both lanes): `B19/INV-b2` FAIL, state
`reconciliation.stale_lockout`, `unhandled=[[OPERATOR_RESOLVED, deferred]]`,
`deferred=1`. `stale_lockout.on` contains only `RECONNECTED` — a critical
account-locked state clearable only by an event the operator cannot produce.

## R10-C4 — Kill/cancel is deferrable for the full service duration on invoking states

**Severity (OMS): High.** Class: **OUR-CONTRACT-DEFECT**. From `CD-01`.

`kb_killdefer.py` 8/8 both lanes; `ka_killswitch.py` K1/K3 async FAIL —
unchanged from `f28719c`. B6 `submitting_slice`/`final_sweep`, B7
`repricing`/`market_converting` and B9 `evaluating`/`acting` declare no
kill/cancel handler, so `onUnhandled:"defer"` holds the kill **1.493 s** (B6) /
**1.461 s** (B9) against a 1.5 s service, versus 0.001 s with the handler.
Nothing is lost — latency and observability only, hence High not Blocker. Note
the interaction with `R10-D2`: on the `def` lane the escape is not an escape at
all.

## R10-C5 — B16: re-elevation via the `elevated→elevated` re-enter arm is unaudited

**Severity (OMS): Medium.** Class: **OUR-CONTRACT-DEFECT**. From `C-04b`.

`n1_b16_b17.py` `B16/INV-c`: `audit_step_up=1` for 2 `STEP_UP_OK`, both lanes.
The `elevated` `STEP_UP_OK` re-enter arm's `actions` is `[stamp_elevated_until]`
only, omitting the `audit_step_up` present on the `normal→elevated` arm. A
privilege extension therefore leaves no audit record.

---

# Design constraints (documented behaviour; wrapper obligations, not defects)

## R10-D1 — rollback + `invoke.onDone` re-arms a side-effecting service
From `F1`. `contracts/repro/r1_rollback_onDone.py`, `r6_stranded_hook.py`,
`CV=async|def` at MAXIT 10/25/default. The documented rollback contract unwinds
the failed transition and SCXML re-entry re-arms the invoke; **each lap is a
real exchange order.** Round 9 pins the constant and lane parity
(`#209`/`#210`); see `R10-M1` for the `+2` / `+3` reading. Not a library
defect. Wrapper must make invoked services idempotent under re-entry (client
order id keyed on chart state, not on lap).

## R10-D2 — Invoke-bearing states with an escape transition must use `async def`
From `CV-19-C01`, `#193` / `production-characteristics.md` §2.
`g9_d3_inv.py` `B12/INV-e`: on the `def` lane `CANCEL` cannot pre-empt
`seek_and_prime` during B12 buffering — the entering macrostep awaits the
service — so the escape is not an escape. Identical on both engines. Binds B12
`buffering`, B12 `stepping`, B13 `subscribing`.

## R10-D3 — Hand-built `AfterEvent` refused at the inbox (`#203`)
From `F5`. `contracts/repro/r9_after_provenance.py`, `CV=async|def`: a forged
`AfterEvent` with the correct type string is now rejected at `send()` rather
than driving the timer (it fired instantly at `f28719c`). **This is correct
behaviour** — it is the control arm of `R10-01`. Consequence for us: wrapper
timeout supervisors must drive timers through the clock or through a domain
event, not by hand-building an `AfterEvent`.

## R10-D4 — `send()` stays success-shaped after `status="error"`
From `CV-19-L01`. `repro/cv19_c07b_killswitch_bricked.py`:
`authorised_send_exc` is null while the library logs the drop loudly and
`i.error` is set. Carried observation, not new. Mitigated by a wrapper that
reads `status` / `error` after each send.

---

# Harness errors

## R10-H1 — `send(wait=True)` treated as "the service chain finished"
From `F4`. Observed on B3's three-retry unwind chain with the harness `cvz.py`
settle widened to 5x50 ms. **The receipt is a macrostep receipt**, not a chain
receipt; fixed-width settles race under CPU load. Our harness was wrong, not
the library. Wrapper code must never read a `wait=True` receipt as "the service
chain has finished". See also `R10-11` on the per-receipt cost of `wait=True`.

---

# Measurements (recorded, not findings)

## R10-M1 — runaway plateau decomposition
From `D4-D6-plateau`. `g9_drives.py`, 44/44 both lanes: D6 (invoke on the
**initial** state) = 7/8/11/15 at limits 4/5/8/12 → `+3`; D4 (event-entered) =
6/7/10/14 → `+2`. The `+3` decomposes as initial descent + seed + the `limit+1`
cut; an event-entered state has no initial descent and costs one lap less. This
matches both of the library's own pins (round-6
`TestAsyncRollbackRearmCycleBounded` asserts 1000+3; round-9
`TestStrandedInvocationObservable` asserts 1000+2) — **they measure different
shapes, and neither is wrong.** The CHANGELOG conflates them; that is `R10-10`.
Lap parity async==sync holds at odd and even limits here (`#209`); `#207`
stranded observability fires in all 16 rows.

## R10-M2 — `#204` improves the settle-budget trip over an invoking state
From `O-3` (CONFIRMED, no action). The observable outcome changes, and the
change is an improvement.

## R10-M3 — `#207` stranded reporting is exactly-once with a correct payload
From `O-4` (CONFIRMED, no action), both engines.

## R10-M4 — `#209` seed settle standing is not more permissive in any reachable shape
From `O-7` (CONFIRMED, no action) — no `#103`/`#151`-class permissiveness
regression found.

## R10-M5 — test changes weaken nothing; one test is materially stronger
From `O-8` (no action).

---

# Withdrawn

| id | reason |
|---|---|
| `D9-fuzz-3 / R9-03` | **FIXED.** `r18_ext_starvation_repro.py` / `r19_starvation_drain.py` re-run verbatim: 500/500 external priority sends applied on `def`, `async def` and sync, plus both ablations (was 72/500 on the async `def` lane). Drain empties in <1 s at 8–9 % of a core (was stuck at 66 %). `n7` soak: 915 600/915 600 applied, 0 lost. |
| `D9-fuzz-4 / R9-08` | **FIXED by `#208`.** `r3_empty_repro.py` re-run verbatim: EMPTY config 0/15 on both kinds on the async engine (was 11/15); sync clean. `n5_livelock_receipt_fuzz.py` over 1408 fuzzed cells: 0 success-shaped receipts over an illegal configuration, 0 error receipts over a legal settled one. |
| `D9-fuzz-2 / R9-09` | **FIXED on its named shape by `#209`.** `g2_lap_parity.py` re-run verbatim: def-lane mismatches 13 → 0 at every limit 1–25, odd and even, both shapes. All 26 remaining mismatches are the documented `SyncInterpreter` + `async def` → `NotSupportedError` exclusion. The general claim remains false on a different shape — refiled as **R10-06**. |
| `CV-F28-01` | **FIXED by `#204`.** `g9_d1_always.py`: all 8 cells report 0 service submissions and land in `fwd.moved` / `bak.idle` per SCXML §6.1 `statesToInvoke`. At `f28719c` the roll-forward `def` cells submitted 1 each. |
| `CV-F28-02` | **FIXED by `#207`/`#209`.** `g9_d2_storm.py` on the verbatim B11/B13 shapes at `maxIterations=12`: 14 laps, `last_error=RunawayChainError`, `err.stranded=('sub',)`, `on_invocation_stranded` fires, `has_dormant_invocations=True`, `pending_invocations()=[('recording.starting','sub','subscribe_streams')]`. `g9_d2b_sweep.py` at the shipped default: 1002 laps, deterministic (was 190–252 non-deterministic with `last_error=RuntimeError`). |
| `R9-09-verify` | **Non-reproducing noise.** The single `DIFFER` sample at mi=9 on `rollback_ondone`/`def` did not recur; isolated retries produced `SAME` twice. Timing jitter in async-engine settle accounting. Superseded in substance by **R10-06**, which is deterministic. |

---

# Regressions from `55-r10-regression.md`

**No true regression** at `19cb1f1`. The three rows that changed state:

- `verify/LC-42 send_receipt` FAIL → PASS x5/5 — **improvement**, consistent
  with `#208`'s receipt-resolution tightening.
- `verifyM4`/`verifyM5` `167 rollback_reinvoke_spin` FAIL → PASS x5/5 —
  **improvement**; previously recorded as expected-FAIL
  (`54-r9-final-readiness-verdict.md` line 82, "`#201` explicitly does not
  promise the sync re-arm"). Now stable, consistent with `#204`.
- `verifyM6`/`201 lap_parity_stated_exactly` MISSING → FAIL x5/5 — **stale
  repro, not a defect.** The script asserts the pre-`#201`/`#209` "sync engine
  stops early with `RuntimeError`" shape. The corrected sweep
  (`209_lap_parity_sweep_1_25.py`) passes. The live residual in this area is
  **R10-06**, which that script does not measure.

---

# Canonical LIBRARY-DEFECT list (for upstream)

Ranked. These are the only rows that are defects **in the library** at
`19cb1f1`; everything else above is our chart, our harness, a documented
constraint, or a doc fix.

| rank | id | sev | one-line |
|---|---|---|---|
| 1 | **R10-01** | Blocker | Engine-event provenance is type identity, not a held capability — `done`/`error`/`after` forgeable 7 ways in-process and via `restore_event`'s plaintext `"engine": true`. `events.py:281-283, 414, 555-565, 579, 604-615`; `base_interpreter.py:4624`. |
| 2 | **R10-02** | High | A self-targeting `onDone` never re-records the state, so the invoke never re-arms; machine parks dormant with `status='running'`, `last_error=None`, no stranded hook. `base_interpreter.py:1921, 3898, 4952, 4958`. |
| 3 | **R10-03** | High | `#206` charges self re-armed delayed sends per lap with no time awareness, killing `raise(delay=)` heartbeats at `maxIterations` on the async engine — an unnamed behaviour break. `interpreter.py:2206-2247`. |
| 4 | **R10-04** | Medium | An armed-but-unfired delayed self-`raise` has no snapshot representation and is silently lost on restore. `interpreter.py:1480-1497`. |
| 5 | **R10-05** | Medium | Restore bypasses `strict` and drops lane provenance; a persisted `after` is now silently **refused** rather than demoted (0.8.0 migration cliff). `base_interpreter.py:1767`; `interpreter.py:356, 1497, 1499-1500`; `events.py:403-414`. |
| 6 | **R10-07** | Medium | Unknown top-level config keys accepted silently — a misspelled `actionErrorPolicy` downgrades a safety policy to its default with no diagnostic. |
| 7 | **R10-08** | Low | Call-site `QueueOverflowError` refusals bypass `on_event_dropped`; 99.3 % of shed invisible to metrics. |
| 8 | **R10-09** | Low | `SnapshotMidStepError` from an invoked child's entry action reports `child=False` (attribution only). |
| 9 | **R10-12** | Low | `after` does not fire under `SimulatedClock.increment()` — pre-existing, needs isolation from the harness. |
| 10 | **R10-13** | Low | Chain trip never reaches `on_error` / `interpreter.error`; `last_error` cleared on `async def`, retained on `def`. |

Doc defects to file alongside: **R10-06** (`#209` lap-parity claim false on
engine-work-only charts), **R10-10** (CHANGELOG `+2` / `+3` contradiction),
**R10-11** (`#208` unreachable-branch overstatement).

**One fix retires the top of this list.** `R10-01` and the security half of
`R10-05` are the same primitive: replace type-identity provenance with a
per-interpreter nonce the engine mints *and holds*, compared by identity at
selection time against the timer registration / invocation actually
outstanding. A boolean in a payload, and a Python class, are both reproducible
by the caller; a value the engine never hands out is not.
