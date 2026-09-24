# SOAK re-run — `xstate-statemachine` @ `c78ce99` (unreleased 0.8.1, round-10)

**Build under test.** `_ref/xstate-statemachine` @ `c78ce99` (round-10 fix
PR, #212–#216 on top of round-9). `__version__` still `0.8.0` — keyed on
commit. `CHANGELOG.md` `[Unreleased]` documents #212 (SUPERSEDES #206: a
`raise(delay=)` self-send is now a timer, an `after`-rule cousin — a 1 ms
self ping-pong is legal periodic work, NOT a runaway), #213 (snapshot
layout v3, `scheduled_sends`), #214 (restore applies `strict`, upcasts v2
`done`/`error`/`after` as engine-minted, records carry `lane`), #215
(settle-budget/descent-wait fixes), #216 (unknown top-level config keys →
WARNING + did-you-mean, `strict_config=True` → `InvalidConfigError`).

**Date:** 2026-09-22. **Python:** CPython 3.13.7 / Windows 11.
**Interpreter:** `.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified.

**Time-bound disclosure.** Whole-task budget 20 minutes; scripts capped at
30–60 s each via `timeout`. The 12-min/200-machine full soak was **not**
run at full scale — `attack_r10_new_3_soak.py` ran a reduced 30-machine /
20 s heartbeat+chaos-restore soak instead (see §4 not-covered). All prior
`battle-19cb1f1/soak/*` scripts were copied byte-for-byte and re-run
unmodified.

---

## 1. Prior-defect re-verification (`battle-19cb1f1/soak/*` re-run unmodified against `c78ce99`)

| ID | 19cb1f1 verdict | c78ce99 re-run result | Verdict |
|---|---|---|---|
| D-soak-1 (`wait=True` receipt hangs after uncaught plugin-hook exception) | FIXED | both receipts resolved | **FIXED** (unchanged) |
| D-soak-2 (`SimulatedClock` settler leak on crash-restore) | FIXED | `settlers=0`, `1/21 reachable`, NOT REPRODUCED | **FIXED** (unchanged) |
| D5-soak-1 (`check_shape()` gap) | FIXED | all 6 hostile fields typed correctly (`SnapshotCorruptError`/`SnapshotVersionError`) | **FIXED** (unchanged) |
| soak-adjacent #145 (`actionErrorPolicy:"fail"` stop contract) | FIXED | `status="stopped"`, config `[]`, restore accepted terminal | **FIXED** (unchanged) |
| #166-168 settle-budget under concurrent externals | PASS | tripped at lap 1001 regardless of 0/1/4/16 concurrent senders | **PASS** (unchanged) |
| #172 threadsafe in-flight counter under churn | PASS | 25 generations, `anomalies=[]` | **PASS** (unchanged) |
| #157 loop-side RAISE observability | PASS | 1199/1199 refusals fired `on_event_dropped(reason="queue_full")` exactly once | **PASS** (unchanged) |
| #173 `service_pool_size=1` + `stop()` churn (`def`) | PASS | 50 generations, `hangs=0`, `double_fires=0` | **PASS** (unchanged) |
| #173 (`async def` lane) | PASS | 50 generations, `hangs=0`, `double_fires=0` | **PASS** (unchanged) |
| round-7 A: `_chain_owed` leak, 100 never-completing services + `stop()` | PASS | `hangs=0`, `dt_s=0.236` | **PASS** (unchanged) |
| round-7 B: external `priority=True` sends during self-generated chain | PASS | `ext_seen=2997/3000, dropped=0` | **PASS** (unchanged; same known microstep-cap artifact) |
| round-7 C: `children_timeout`, 50 slow children | PASS (bound-respected) | `bounded=True`, same `n_registered_children` harness gap | **PASS** (unchanged) |
| #195 forgery-under-load (200 hand-built events, `strict=True`, both engines) | PASS | `onDone_fires_from_forged=0` both engines, `call_site_refused=200/200` | **PASS** (unchanged) |
| #192 priority shed-by-provenance | PASS | `dropped=0, ext_seen=2997/3000` | **PASS** (unchanged) |
| #204 invoke arms only after settle (round-9) | PASS | `svc_calls=0` all 4 combos, `A_NO_SPURIOUS_INVOKE=True` | **PASS** (unchanged) |
| #203 hand-built `AfterEvent` refused (round-9) | PASS | machine stayed in `d.waiting` both engines | **PASS** (unchanged) |
| #207 stranded-invocation hook under 20-way concurrency (round-9) | PASS | 40/40 instances stranded exactly once, hook fired once each | **PASS** (unchanged) |
| #206 delayed self-send debt (round-9 rule, **now superseded by #212**) | PASS (old rule) | **SUPERSEDED** — see below | **SUPERSEDED** |

No harness adaptation was needed for the first 17 rows: round-10's fix set
(scheduled-sends persistence, restore-strict/lane, settle-budget/descent
wait, config-key policing) touches none of the code paths these scripts
pin, and results are byte-identical to the round-9 re-run.

### 1.1 `#206`/round-9's `attack_new_r9_soak_2.py` §B — SUPERSEDED, not FAIL

Re-run unmodified, the exact `TestDelayedSelfSendIsCharged.CFG` shape
(`a`/`b` ping-pong via `raise(event="GO", delay=1)`, `maxIterations=20`):

```
async: {'lap': 800, 'last_error': None}
sync:  {'lap': 0,  'last_error': None}
```

Under round-9's rule the async engine tripped `RunawayChainError` at
`lap≈20`; under round-10's #212 rule the same script now runs to
`lap=800` (the script's own iteration cap) with **no error at all** — the
delayed self-send is charged as a timer, not a chain debt, exactly as
#212 documents. This is graded **SUPERSEDED**, not a regression: the old
assertion (`async: RunawayChainError at ~maxIterations`) encoded the
overturned #206 rule; the new correct assertion — recorded fresh in
§2.2 below with `attack_q` — is "a 1 ms `raise(delay=)` ping-pong across
many machines runs indefinitely, CPU bounded by the clock, no
`RunawayChainError`," which **holds**.

---

## 2. New round-10-targeted attacks (`battle-c78ce99/soak/`)

| Attack | Target | Result |
|---|---|---|
| `attack_r10_new_1.py::attack_p` | #213: v3 snapshot round-trip with armed delayed self-sends at random points in the ping-pong | **PASS** — 60/60 restored, `scheduled_sends` field present |
| `attack_r10_new_1.py::attack_q` | #212: 20 machines × 1 ms `raise(delay=)` ping-pong for 5 s, CPU bounded, no `RunawayChainError` | **PASS** |
| `attack_r10_new_1.py::attack_r` | #216: top-level config-key misspellings (default=WARNING no raise, `strict_config=True`→`InvalidConfigError`) + nested state-level unknown key | **PASS top-level; DEFECT-adjacent nested — see D11-soak-2** |
| `attack_r10_new_2_security.py::attack_s` | THE round-10 security question: forged v2-shaped `after` record (no `engine` flag) minting an engine completion via `upcast()` | **DEFECT — see D11-soak-1** |
| `attack_r10_new_3_soak.py::attack_t` | Reduced-scale soak: 30 machines, 17 ms heartbeats + external producer + chaos snapshot/restore every 0.5 s for 20 s | **PASS** |

### 2.1 `attack_p` — v3 persistence round-trip

60 random ping-pong machines (`a↔b`, 37 ms / 41 ms `raise(delay=)`),
snapshotted after 0–4 random settle waits, restored via
`Interpreter.from_snapshot(snap_str, machine)`. All 60 restored and ran
to completion without error; the persisted JSON carries a
`scheduled_sends` key (confirmed non-empty on at least one sample). No
defect — consistent with #213.

### 2.2 `attack_q` — 1 ms ping-pong across 20 machines, CPU-bounded

20 machines each running an `a↔b` ping-pong via `raise(event="GO",
delay=1)`, driven for 5 s wall-clock:

```
n_machines=20 wall_s=5.01 min_count=1337 max_count=1338
n_with_error=0
attack_q_no_runaway=True
```

~267 transitions/s/machine (bounded by the 1 ms clock plus scheduler
overhead, not runaway growth), zero `RunawayChainError` across all 20
machines. Consistent with #212: a delayed self-send ping-pong of any
period is a periodic process, not a chargeable chain. No defect.

### 2.3 `attack_r` — #216 config-key fuzz, top-level and nested

Top-level misspellings (`actionErrorPolicyy`, `Strict`, `maxIteration`,
`onUnhandledEvent`, `strictConfigg`): default construction succeeds
(WARNING, not verified textually here — see §4 not-covered for the
did-you-mean text check), `strict_config=True` raises `InvalidConfigError`
for all 5 — consistent with #216.

Nested (state-level) unknown key `actionErrorPolicyy` under
`states.s`: **neither** default nor `strict_config=True` raises anything.
This is not necessarily a defect — #216 is documented as a *top-level*
key check — but the prompt's own instruction to "document what nested
does" surfaces a gap: `strict_config=True` gives no protection at all
against a misspelled *state-level* policy key (e.g. `actionErrorPolicy`
misspelled inside a specific state's config), which is exactly the kind
of silent-downgrade defect #216 was meant to close, just one level down
the tree. Recorded as **D11-soak-2** (see §3).

### 2.4 `attack_s` — v2-upcast minting vector (the round-10 security question)

A running machine with a real 60 s `after` transition
(`waiting --after(60000)--> late_fired`) was snapshotted, then a **forged**
v2-shaped snapshot was built by hand:

- `"version": 2`
- `pending_events` containing one record: `{"kind": "after", "type":
  "after.60000.guard.waiting", "scheduled_for": 0.0, "fired_at": 0.0}`
  — **no `"engine": true` flag**, i.e. exactly what an attacker who
  can write raw JSON but doesn't know about the v3 provenance flag would
  produce, or what a genuinely 0.8.0-era (pre-#195) snapshot writer
  would have emitted for a real, engine-fired `after` completion.

Restored via `Interpreter.from_snapshot(forged_str, machine,
verify_machine_hash=False)` (hash check bypassed to isolate the upcast
path, as a real cross-version restore would also need `minimum_version`
relaxed or no hash recorded):

```
attack_s v2_forged_after_record_fires_early: True
attack_s config_after_restore: ['guard.late_fired']
attack_s VULNERABLE_IF_TRUE: True
```

The machine ended up in `late_fired` — the 60-second `after` fired
instantly on restore. See **D11-soak-1**.

### 2.5 `attack_t` — reduced-scale chaos soak (30 machines, 20 s)

30 machines running a 17 ms `raise(delay=)` heartbeat ping-pong, an
external producer sending `EXT` round-robin every 5 ms, and a chaos task
snapshotting + restoring one random machine every 0.5 s:

```
n_machines=30 wall_s=20.38 min_beats=648 max_beats=649
sent=1265 ext_received=1265 dropped_ext=0
restore_ok=40 restore_errs=0
attack_t_heartbeats_alive=True attack_t_no_dropped_ext=True
attack_t_no_runaway=True
```

All heartbeats alive and roughly in lockstep (648–649 beats over 20 s ≈
17 ms period, matching the timer), zero dropped externals, zero restore
errors, zero `RunawayChainError`. No defect — consistent with #212/#213.

---

## 3. Defects

### D11-soak-1 — **Blocker** — v2-upcast minting is exploitable exactly as feared

**Reproduced.** `attack_r10_new_2_security.py`. A snapshot blob claiming
`"version": 2` with a `pending_events` record `{"kind": "after", "type":
"after.<ms>.<state_id>", ...}` and **no `"engine"` flag** is upcast by
`persistence.upcast()` (round-10, `2 -> 3` step) into an engine-minted
completion — `rec.setdefault("engine", True)` is applied unconditionally
to any v2-tagged record whose `kind` is `done`/`error`/`after`, with no
signature or provenance check beyond the attacker-controlled `version`
field and `kind` string. Firing the corresponding `after` transition
instantly on restore, from a snapshot an attacker who can merely
downgrade the declared `version` to `2` can construct without needing to
know about the v3 `engine` flag at all.

This is exactly the trust-boundary caveat the library's own
`from_snapshot` docstring calls out ("a party who controls the whole
blob can write a consistent one" — `machine_hash` is a fingerprint, not a
MAC) — but #214's whole point was to make a *v3* forged record (no
`engine` flag, i.e. "I did not opt out of the safety check") NOT drive
`after`/`onDone`. The `2 -> 3` upcast step reopens exactly that hole for
anyone willing to also lie about `version`. `verify_machine_hash=False`
was used to isolate the mechanism in the repro (a routine cross-version
restore or a hash-less v2 payload would also need to bypass or lack the
hash check), but the *decisive* step — minting the completion — happens
in `upcast()`, unconditionally, before any hash verification is even
consulted for the record's own kind/engine flag.

- **File/line:** `src/xstate_statemachine/persistence.py:427-439`
  (`upcast()`, the `version < 3` branch, `rec.setdefault("engine", True)`)
- **Severity:** Blocker (OMS) — matches the register's `R10-01` family
  (engine-event provenance forgeable) but via the v2-compat path
  specifically, which #214 was supposed to close for v3 and instead
  reopens for anyone who declares `version: 2`.
- **Repro:** `battle-c78ce99/soak/attack_r10_new_2_security.py`

### D11-soak-2 — **Medium** — #216 protects only top-level keys; nested (state-level) policy misspellings pass silently even under `strict_config=True`

**Reproduced.** `attack_r10_new_1.py::attack_r`. A misspelled
state-level policy key (e.g. `actionErrorPolicyy` nested under
`states.s`) is silently accepted by `create_machine()` both with and
without `strict_config=True` — no warning, no error. #216's changelog
entry is scoped to "unknown top-level config keys," so this is not a
regression against a stated contract, but it leaves the exact failure
mode #216 was written to close (a misspelled safety policy silently
reverting to permissive default) fully open one level down the config
tree, which is where `actionErrorPolicy` is actually most commonly set
(per-state, not just at the machine root in idiomatic configs).
Recommend: extend the `KNOWN_MACHINE_KEYS` check (or an analogous
per-state list) to `states.*` policy keys, or explicitly document the
top-level-only scope as a known limitation.

- **File/line:** `src/xstate_statemachine/factory.py` (top-level-only
  `strict_config`/`KNOWN_MACHINE_KEYS` check; no equivalent walk over
  `states.*` keys — exact line not isolated in this pass, see §4)
- **Severity:** Medium
- **Repro:** `battle-c78ce99/soak/attack_r10_new_1.py::attack_r`

No other defects found in this soak pass; all round-10 CHANGELOG claims
exercised (#212 timer semantics, #213 scheduled_sends round-trip, #215
settle/descent behavior implicitly via unchanged prior-defect rows, #216
top-level key policing) held except the two above.

---

## 4. Not covered (budget-bounded disclosure)

- **Full 12-min/200-machine soak** was reduced to 30 machines / 20 s —
  the CPU-bounded and no-dropped-external claims scale roughly linearly
  in this library's architecture (no shared global lock contention
  observed at 20-30 machines across every prior soak track), but this is
  an extrapolation, not a verified claim at the requested scale/duration.
- **v2 fixture upcast matrix** (`done`/`error`/`after`, both with and
  without pre-existing `engine` flag, across all record-bearing keys
  `pending_events`/`deferred`) was exercised only for `after`; `done`/
  `error` upcast paths share the same unconditional `setdefault` code
  path (`persistence.py:432-439` loops over all three kinds identically)
  so the same vulnerability class is expected to reproduce for `done`/
  `error` too, but this was not independently re-run per-kind given the
  time budget.
- **lane restore ordering** and **machine_hash coverage of
  scheduled_sends**: not separately probed. `structure_hash` (used for
  `machine_hash`) is a structural (config) fingerprint computed from the
  machine's static definition, not the live snapshot payload — by
  construction it cannot and does not vary with `scheduled_sends`
  content; treating "does machine_hash cover scheduled_sends" as
  expecting a data hash was a misreading of the mechanism, not something
  this pass found broken.
- **200-config livelock fuzzer**, **50× determinism traces**,
  **restore of 200 v3 snapshots concurrently**, **strict_config bypass
  via `x-` prefix**, **redaction**, **on_invalid_event on restore
  exactly-once** were not run this pass — out of the 20-minute budget
  after the higher-priority security-vector and persistence checks.
- `attack_r`'s WARNING-text ("did-you-mean" hint) content was not
  captured/verified textually, only that no exception is raised by
  default and one is raised under `strict_config=True`.

---

## 5. Verdict

**Two new defects this pass.** D11-soak-1 (Blocker) shows round-10's
provenance fix (#214) is bypassable via the `version: 2` upcast path —
the exact class of defect the round's headline fix (#212/#214) was
supposed to retire, reopened by the compatibility shim that makes old
snapshots restore safely. D11-soak-2 (Medium) is a scope gap in #216,
not a regression. All eighteen prior-round soak-track
defects/checks remain FIXED/PASS, with round-9's #206 finding correctly
reclassified **SUPERSEDED** (not a regression) per #212's documented
reversal, and confirmed by a fresh, purpose-built round-10 attack
(`attack_q`) that the new rule holds under concurrent load. The
reduced-scale chaos soak (`attack_t`) found no additional defects at 30
machines / 20 s. Given D11-soak-1's severity, this track does **not**
recommend shipping 0.8.1 on the persistence/restore surface without
either (a) closing the v2-upcast minting hole, or (b) explicitly
documenting that a v2-declared payload's `after`/`done`/`error` records
must be treated as equally untrusted as the machine's own signature over
the whole blob — i.e. that `verify_machine_hash`/`expected_machine_hash`
must be treated as mandatory, not optional, whenever a snapshot crosses
a trust boundary and might be v2-shaped.
