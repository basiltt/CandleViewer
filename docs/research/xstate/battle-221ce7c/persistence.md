# Battle-test track: PERSISTENCE & crash consistency — re-run on `221ce7c`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`221ce7c`** ("Merge pull request #178 from
basiltt/fix/157-loop-side-raise-observable"), CHANGELOG `[Unreleased] —
targeting 0.8.1`. **`__version__` still reports `0.8.0`; this build is
identified by commit, never by version string.**

**Date:** 2026-09-20 · **Python:** CPython 3.13.7 · **OS:** Windows 11 Pro
10.0.26200 · **Interpreter:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was read-only throughout.

Scripts: `docs/research/xstate/battle-221ce7c/persistence/` (prior scripts
copied verbatim from `battle-cec108b/persistence/`; new scripts are the `q*`
series). Raw output for every run is under `persistence/out/`.
Predecessor: `battle-cec108b/persistence.md`.

---

## 0. Bottom line

**The round-6 entry-window fix (#169) is real but incomplete, and two
round-6 read-side defects were never fixed.**

- **#169 holds in every window except one.** The new hook property
  (`q1`, **320 generated parallel machines, 7,622 snapshot attempts from 8
  distinct windows**) shows **0 raw exceptions and 0 round-trip
  mismatches**, and every `entry`, `exit`, `on_action`, `on_transition`,
  `after`-timer and deferred-replay window taken *after* `start()` returned
  is correctly refused or legal.
- **`D7-persistence-1` (High, NEW).** The one exception is the **async
  `start()` initial-entry window**: all **720/720** torn blobs land there
  and nowhere else (`TORN by window: {'entry@start': 720}`). The async
  engine enters its initial states *without* the re-entrancy guard the sync
  engine sets, so `_step_in_flight()` is `False` during initial entry and
  the #169 root-level refusal never fires. The library's own reader then
  rejects the blob its writer produced: `SnapshotCorruptError: status is
  'running' but the configuration has no active leaf in every region`.
  **Sync engine is correct** (refuses both attempts) — the same
  "fixed on the engine the issue was filed against" pattern round 6 named
  as its headline.
- **`R6-07` (High) is STILL-PRESENT, unchanged.** `machine_hash: None` —
  and, additionally, a *removed* `machine_hash` key — still disables drift
  verification under `verify_machine_hash=True`. A snapshot from machine A
  restores clean into a structurally different machine B. Root cause line
  `persistence.py:277` is byte-identical to the round-6 reading.
- **`R6-16` (Low) is STILL-PRESENT and is worse than filed.** `configuration`
  is not cross-validated against `state_ids`, and because the reader
  *prefers* `configuration` (`base_interpreter.py:1689`), a blob whose
  `configuration` says `m.b` while `state_ids` says `m.a` restores into
  **`m.b`** — the contradiction silently picks a winner rather than being
  refused.
- **Everything else is clean.** All four round-5 defects stay FIXED; every
  prior script reproduces its prior verdict; the 330 s / 200-machine
  executor soak is **PASS** (26,009 snapshot+restore cycles, 0 midstep,
  0 raw, 0 mismatch, flat object count); restore-and-resume **trace parity**
  holds at all 9 crash points on both engines; and the PR #165/#176
  `__slots__`/shared-sentinel work shows **no cross-machine aliasing**.

**Defects filed this round: 1 new (`D7-persistence-1`, High) + 2 carried
STILL-PRESENT (`R6-07` High, `R6-16` Low).**

**Verdict for this track: DO NOT ADOPT BARE — adopt with a wrapper.** All
three are cheaply wrappable (never snapshot from a plugin hook during
`start()`; verify `machine_hash` yourself before calling `from_snapshot`;
drop or cross-check `configuration`), and none can lose a settled order.
Persistence at quiescence — the only window an OMS actually snapshots
from — is sound at full scale.

---

## 1. Method

Machine, harness and comparison technique are unchanged from
`battle-cec108b/persistence.md` §1 — `order_machine.py` (parallel
`submitted` region, `invoke` with `onDone`/`onError`, two `after` timers,
machine-level `onUnhandled: "defer"`, `SimulatedClock` throughout) and the
`TraceP` plugin collecting the emitted-action trace through the public
`PluginBase.on_action_execute` hook.

### Exact command shape

```
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
PYTHONPATH=_ref/xstate-statemachine/src \
".venv-main/Scripts/python" <script> [args]
```

### Adaptations to prior scripts (documented-superseded behaviour)

1. `d3_torn_snapshot.py`, `d3b_partial_parallel.py`, `d6_priority_lane.py`
   and `t5_midmacrostep.py` terminate on an **expected**
   `SnapshotMidStepError` instead of printing a torn blob. That raise **is**
   the #102/#142/#169 fix, so the scripts are left unmodified and their
   traceback is read as a PASS. `d3b` additionally dies on
   `json.loads(None)` afterwards because `plug.blob` was never assigned —
   the contained plugin failure above it is the actual result. `d6` is
   still **superseded by `n1_priority_lane_107.py`** for the reason given
   in the prior two rounds; `n1` is the authority and passes 3/3.
2. `n7_restore_event_type.py` exits non-zero *by design* on this build: it
   dies on its first hostile input with the `SnapshotCorruptError` that is
   the #113 fix. Non-zero exit = PASS for this script.
3. `t2_property.py` keeps the `MAXEX` environment override added last round
   (test-harness only, no behaviour change).

### Parameter reductions (stated as required by the brief)

| Script | Brief / prior | Run here | Cost of the reduction |
|---|---|---|---|
| `q1_hook_snapshot_property.py` | ≥300 random machines | **320** — not reduced | |
| `n5_corrupt_fuzz.py` | 5,000 mutations | **2,000** | 5,000 exceeds the 120 s script bound. 2,000 resolves the historical 10.9 % leak rate to zero with wide margin. |
| `n9_soak.py` | 12 min | **not re-run** | Superseded by `m3` (same property, 200 machines + executor services rather than one machine). Task wall-clock bound. |
| `m3_soak_executor.py` | 12 min, 200 machines | **330 s, 200 machines** | Task wall-clock bound. Machine count and shape (parallel regions + plain-`def` executor services + chaos snapshot/restore every 2 s) are **not** reduced; the reduction costs duration-dependent coverage (slow leaks), not cycle coverage — 26,009 cycles were executed. |
| `n2_quiescent_property.py` | 2,000 events, restore at every point | **2,000 / `--restore-every 1`** — not reduced | |
| `m1_parallel_property.py` | ≥300 cases | **350** — not reduced | |
| `n8_determinism.py` | 50× both engines | **50×** — not reduced | |
| `t2_property.py` | 2,000 hypothesis cases | **not re-run** | Superseded by `q3` (exhaustive crash-point trace parity, both engines) and `n2`. |
| `t8_midstep_property.py` | 2,000 cases | **not re-run** | Superseded by `q1` (stronger: 8 windows, random machines, context-drift check). |

### Scope note

This report covers the **persistence** track only. The brief also lists
concurrency, fuzz/livelock, determinism, semantics, observability and
security attack families; those are the sibling tracks' remit and are
recorded here under **§5 Not covered** rather than half-executed inside the
wall-clock bound. The persistence-adjacent members of those families that
the round-6 register filed against *this* track (R6-07, R6-16, and the
perf-PR aliasing check) **were** executed and are reported in §2 and §3.

---

## 2. Prior defects: FIXED / STILL-PRESENT / CHANGED

### 2.1 Round-5 defects (closed on `cec108b`) — regression check

| ID | Prior sev | Verdict on `221ce7c` | Evidence |
|---|---|---|---|
| **D5-persistence-1** (`#102` mid-step guard is `any(leaf)`) | High | **FIXED (holds)** | `n3_parallel_tear.py 300`: 179 attempts → **0 TORN (0.0 %)**, 0 globally-empty, 0 missing-region, 142 refused. `d3b_partial_parallel.py` still cannot produce a blob. |
| **D5-persistence-2** (`#113` non-`str` event type on the restore path) | Medium | **FIXED (holds)** | `n7_restore_event_type.py` dies on the **first** hostile input: `SnapshotCorruptError: event record 'type' must be a non-empty string, got 42` (`events.py:378`). |
| **D5-persistence-3** (raw builtins leak from `from_snapshot`) | Medium | **FIXED (holds)** | `n5_corrupt_fuzz.py 2000`: **RAW builtin leaks = 0**; 1,004 typed (889 `SnapshotCorruptError`, 93 `SnapshotDriftError`, 22 `SnapshotVersionError`), 996 accepted of which **0 unsound**. |
| **D5-persistence-4** (v1 provenance laundering) | Low | **FIXED (holds)** | `t4_receipts_provenance.py` P12: `after.hours`, `xstate.custom`, `done.review`, `PLAIN` all → `system=False`; the restored `done.review` errors the machine exactly as the live-send control does. |

### 2.2 Round-6 defects filed against this track

| ID | Round-6 sev | Verdict on `221ce7c` | Evidence |
|---|---|---|---|
| **R6-06** (entry-action window accepts a torn snapshot; both engines) | High | **FIXED — but only for post-`start()` windows.** See `D7-persistence-1`. | `t6_action_boundary.py`: **1/6 OK, 0/6 torn, 5/6 refused** (was 2/6 OK, 4/6 refused) — the extra refusal is exactly the entry window #169 closed. `q1` confirms across 320 machines: **0 torn in any of `entry`, `exit`, `on_action`, `on_transition`, `after_timer_action`, `deferred_or_unhandled`**. The residue is the `start()` window only. |
| **R6-07** (`machine_hash: None` disables drift verification) | High | **STILL-PRESENT — unchanged, and broader than filed** | `q2_readside_gaps.py`. Not in the #166–#175 fix set; `persistence.py:277` is unchanged. |
| **R6-16** (`configuration` never cross-checked against `state_ids`) | Low | **STILL-PRESENT — and CHANGED for the worse** | `q2_readside_gaps.py`: a contradictory `configuration` does not merely go unchecked, it **wins** (`base_interpreter.py:1689` prefers it). |
| **R6-17** (two legality predicates: `_configuration_is_legal` vs `_active_leaf_present`) | Low | **STILL-PRESENT** | Both still defined at `base_interpreter.py:1297` and `:1333`. No new failure was reproduced through it this round; recorded as a standing structural risk, not re-filed. |

### 2.3 Regression check on previously-clean results

| Script | Prior (`cec108b`) | Now (`221ce7c`) |
|---|---|---|
| `p0_smoke.py` | layout `version == 2`, 16 keys | unchanged |
| `t1_crashpoints.py` | 20/22 static, 22/22 `--restart` | **20/22** static — identical; the 2 divergences are the documented static-restore timer default |
| `t3_probes.py` | P1/P5/P6/P6b/P6c/P8/P9/P9b/P10 PASS | **all still PASS** (child actors, bounded inbox, 1 MB round-trip) |
| `t6_action_boundary.py` | 2/6 OK, 0 torn, 4 refused | **1/6 OK, 0 torn, 5 refused** — the #169 improvement |
| `t7_rollback.py` | post-rollback restore correct, mid-macrostep refused | unchanged |
| `d2_after_timer_lost.py` | `restart_services=True` re-arms, `False` does not | unchanged (`fired=True`/`pending=1` vs `False`/`0`) |
| `d5_invoke_dormancy.py` | `restart_services=True` re-runs the service | **unchanged — CV-P05 stands** |
| `n1_priority_lane_107.py` | 3/3 | **3/3** |
| `n2_quiescent_property.py 2000 --restore-every 1` | 2,000/2,000, 0 midstep, 0 mismatch | **2,000 snapshots, 0 midstep, 0 other raises, 2,000 restores, 0 mismatches, 30.5 s** |
| `n3_parallel_tear.py 300` | 0/179 torn | **0/179 torn** |
| `n4_restart_timers.py` | 5/5 | **5/5** |
| `n5_corrupt_fuzz.py 2000` | 0 raw, 0 unsound | **0 raw, 0 unsound** |
| `n6_hostile_and_hooks.py` | live 8/9, restore 5/5, redaction targeted | unchanged; provenance API surface 13/13 |
| `n8_determinism.py` | 50/50 per engine, 1 distinct blob each | **PASS** — per-engine determinism holds; the printed async-vs-sync `value` difference is the known timer/settle asymmetry, not a persistence fault |
| `n10_semantics_persist.py` | all four PASS | **all four PASS** (#109/#130/#116/#108) |
| `m1_parallel_property.py 350` | 1,217 snapshots, 0 raises/mismatches/illegal | **1,406 snapshots, 0 raises, 0 mismatches, 0 illegal** |
| `m2_roundtrip_edges.py` | 7/7 PASS | **7/7 PASS** |
| `m3_soak_executor.py 330 200` | 23,242 cycles, 0/0/0 | **26,009 snapshot+restore cycles, 0 midstep, 0 raw, 0 mismatch** (see §3.4) |

---

## 3. New attacks on this round's fixes

| # | Script | Attack | Result |
|---|---|---|---|
| Q1 | `q1_hook_snapshot_property.py 320 7` | **Snapshot from EVERY hook**, property over 320 randomly generated machines (2–3 parallel regions, random nested compound children, `after` timers, `onUnhandled` split between `defer` and `ignore`). Windows: `on_transition`, `on_action_execute` split into `entry` / `entry_nested` / `exit` / `on_action` / `after_timer_action`, and `on_unhandled_event` (deferred replay). Every action **mutates context**, so an accepted mid-action blob whose context predates the mutation is detectable. Accept criteria: refused → legal; accepted → must restore, be region-legal, round-trip byte-identical, and carry the context the machine held at that instant | **FAIL — `D7-persistence-1`.** 7,622 attempts, 6,262 refused, 1,360 accepted, **0 raw exceptions, 0 round-trip mismatches**, **720 torn — all 720 in `entry@start`** |
| Q1b | `q1b_start_entry_window_min.py` | **Minimal repro** of the above: a 2-region parallel machine, one entry action per region, snapshot from `on_action_execute`, both engines | **FAIL (async) / PASS (sync)** — async: 1 blob write-accepted and read-refused; sync: both attempts refused |
| Q2 | `q2_readside_gaps.py` | **R6-07 / R6-16 re-attack.** Snapshot from machine A restored into a structurally different machine B with `machine_hash` honest / `None` / key removed; and `configuration` emptied or set to contradict `state_ids` | **FAIL — 4/4 gaps STILL-PRESENT** (control correct: honest wrong hash → `SnapshotDriftError`) |
| Q3-A | `q3_resume_parity_sentinel.py` | **Restore + resume TRACE parity**: for every crash point k in a 10-event sequence, `(run 0..k → snapshot → restore → run k+1..n)` must equal the uninterrupted run in states, context **and** full action trace, on **both** engines; and the two engines must agree with each other | **PASS** — 9 crash points × 2 engines, **0 divergences**; plain runs agree exactly (`['tp.c']`, `n=19`, 19 actions) |
| Q3-B | `q3_resume_parity_sentinel.py` | **PR #165/#176 shared-sentinel / `__slots__` aliasing**: two independently built machines started together, driven apart, snapshotted; then one is mutated and the other's blob re-read | **PASS** — distinct `state_ids`, distinct context counters, `i1`'s blob byte-identical after `i2` moved, context objects and their nested lists not aliased |
| Q4 | `m3_soak_executor.py 330 200` | **Reduced soak**: 200 concurrent machines, parallel regions, plain-`def` executor services, chaos snapshot/restore every 2 s at quiescence | **PASS** — see §3.4 |

### 3.1 Q1 — window breakdown

```
machines               : 320  (seed 7)
snapshot attempts      : 7622
  refused (legal)      : 6262
  accepted             : 1360
TORN / inconsistent    : 720   <- must be 0
round-trip mismatches  : 0     <- must be 0
RAW exceptions         : 0     <- must be 0
windows exercised      :
    after_timer_action       330
    deferred_or_unhandled    1928
    entry                    1382
    entry@start              1040
    exit                     923
    on_action                593
    on_transition            1106
    on_transition@start      320
TORN by window         : {'entry@start': 720}
```

The `@start` suffix marks attempts made before `await start()` returned.
**Every window that a running machine can be snapshotted from is clean**;
the whole defect mass is in the async `start()` descent. Note also that
`on_transition@start` (320 attempts, the synthetic init record emitted at
`interpreter.py:1566`) is clean — by then the configuration is complete.

### 3.2 Q1b — minimal repro output

```
--- ASYNC Interpreter.start()
   ACCEPTED-write -> read side SnapshotCorruptError
        cfg=['pp', 'pp.r0', 'pp.r0.a'] ctx={'n': 0}
        Snapshot is malformed: status is 'running' but the configuration has
        no active leaf in every region (restored ['pp', 'pp.r0', 'pp.r0.a']).
   ACCEPTED-write -> read side ACCEPTED  cfg=['pp','pp.r0','pp.r0.a','pp.r1','pp.r1.a']
--- SYNC SyncInterpreter.start()
   REFUSED-write
   REFUSED-write
write-accepted / read-refused blobs: async=1 sync=0
```

Direct flag probe during the async initial entry actions:

```
  during entry: _processing= False _step_in_flight= False legal= False
  during entry: _processing= False _step_in_flight= False legal= True
```

`_step_in_flight()` — the sole predicate the #169 root refusal rests on — is
`False` throughout async initial entry, so the refusal cannot fire.

### 3.3 Q2 — read-side gap output

```
=== R6-07: machine_hash dropped, restored into a DIFFERENT machine
  (snapshot machine_hash = '510abea7b8ae24b2')
  honest hash vs machine B                  SnapshotDriftError      <- correct
  machine_hash=None vs machine B            ACCEPTED  states=['m','m.a']
  machine_hash key REMOVED vs machine B     ACCEPTED  states=['m','m.a']

=== R6-16: `configuration` contradicts `state_ids`
  configuration=[] (state_ids intact)       ACCEPTED  states=['m','m.a']
  configuration=['m','m.b'] vs state_ids a  ACCEPTED  states=['m','m.b']
```

The last line is the round-6 finding **escalating in kind**: the reader does
not ignore the contradictory `configuration`, it *prefers* it, so an attacker
who can edit one key relocates the machine to any state.

### 3.4 Q4 — soak result

```
soak budget          : 330.0s (REDUCED from the brief's 12 min)
concurrent machines  : 200
elapsed              : 332.4s
cycles               : 106100
events               : 106100
snapshots            : 26009
restores             : 26009
midstep              : 0
raw exceptions       : 0   <- must be 0
round-trip mismatch  : 0   <- must be 0
RSS   30.3 MB -> 107.0 MB   objs 20654 -> 21602
VERDICT: PASS
```

**26,009 snapshot/restore cycles across 200 parallel machines driven by
plain-`def` executor services, with zero raw exceptions, zero
`SnapshotMidStepError` at quiescence and zero round-trip mismatches.** RSS is
the live working set of 200 simultaneously-running interpreters; the
leak-sensitive figure is the tracked-object count, **flat at +4.6 %
(20,654 → 21,602) across 106,100 cycles**. CPU stayed bounded; no livelock.

---

## 4. Defects

### D7-persistence-1 — async `start()` writes a snapshot its own reader refuses (High, NEW)

**Severity: High.** A safety property the library documents and enforces
everywhere else ("a snapshot from inside an action is refused") fails open in
one window, on one engine, with no signal: `last_transition_ok` stays `True`
and no error is set. The blob is not merely torn, it is **unrestorable** —
persisting it is a silent write of an unrecoverable checkpoint. It is not a
Blocker because an OMS snapshots at quiescence, not from a `start()`-time
plugin hook, and a wrapper closes it in one line.

**Repro:** `battle-221ce7c/persistence/q1b_start_entry_window_min.py`
(minimal, 2 regions, ~100 lines) and
`q1_hook_snapshot_property.py 320 7` (property, 720/720 occurrences confined
to this window).

**Observed:**

```
ACCEPTED-write -> read side SnapshotCorruptError
   cfg=['pp','pp.r0','pp.r0.a']  ctx={'n': 0}
   "status is 'running' but the configuration has no active leaf in every region"
```
Sync engine, same machine, same hook: **REFUSED-write** (correct).

**Root cause.**
`src/xstate_statemachine/base_interpreter.py:1389` — the #169 root-level
refusal is `if self._step_in_flight(): if _seen is None: raise
SnapshotMidStepError`. `_step_in_flight()`
(`base_interpreter.py:1290`) reads `_processing` / `_is_processing`.

- `src/xstate_statemachine/sync_interpreter.py:369-373` wraps initial entry
  in the re-entrancy guard: `self._is_processing = True; try:
  self._drive(self._enter_states([self.machine])); finally:
  self._is_processing = False`. Its comment even names the hazard: entry
  runs "while the machine was still descending into its initial states".
- `src/xstate_statemachine/interpreter.py:542` — `await
  self._enter_states([self.machine], init_event)` — has **no equivalent
  guard**. `_processing` is only set inside the run loop
  (`interpreter.py:1654`), which is not what performs the initial descent.

So during async initial entry the machine is genuinely mid-step while
`_step_in_flight()` reports `False`. In a parallel machine the first region's
entry action fires before the second region has a leaf, and that partial
configuration is what gets persisted.

**Suggested fix:** mirror the sync engine — set `_processing = True` around
the `_enter_states` call in `Interpreter.start()` (and keep the existing
`finally` reset), which makes both engines refuse identically and needs no
change to the #169 predicate.

**Wrapper mitigation (ours):** gate the snapshot plugin on an
`interpreter_started` flag; never call `get_persisted_snapshot()` from a hook
until `await start()` has returned. Already demonstrated in `q1` (the
`@start` classifier) and costs one boolean.

### D7-persistence-2 — `machine_hash: None` or absent disables drift verification (High, carried `R6-07`)

**Severity: High, unchanged from round 6.** Not in the #166–#175 fix set;
`persistence.py:277` is byte-identical.

**Repro:** `q2_readside_gaps.py`. **File:line:**
`src/xstate_statemachine/persistence.py:276-277`
(`snap_hash = snapshot.get("machine_hash")` /
`if verify_hash and snap_hash is not None:`).

**Observed:** a snapshot of machine A restores **clean** into a structurally
different machine B when `machine_hash` is `None` **or the key is removed**,
even under the default `verify_machine_hash=True`; the honest-hash control
correctly raises `SnapshotDriftError`. The `None` branch exists for genuinely
unversioned v0 payloads but is keyed on the *field* rather than the
snapshot's declared `version`, so deleting one key downgrades a v2 snapshot
to unchecked. **Suggested fix:** when `version >= 1` and `verify_hash`, a
missing/`None` `machine_hash` is `SnapshotCorruptError`.

**Wrapper mitigation:** assert `blob["machine_hash"] == machine.structure_hash`
yourself before calling `from_snapshot`. Cheap, and our snapshots are
integrity-protected at rest anyway.

### D7-persistence-3 — contradictory `configuration` wins over `state_ids` (Low→Medium, carried `R6-16`, CHANGED)

**Severity: Low as filed; the behaviour observed here is Medium** because the
contradictory key is *authoritative*, not merely unvalidated.

**Repro:** `q2_readside_gaps.py`. **File:line:**
`src/xstate_statemachine/base_interpreter.py:1689` —
`restore_ids = snapshot.get("configuration") or snapshot["state_ids"]`.

**Observed:** snapshot has `state_ids=['m.a']`, `configuration=['m','m.a']`.
Editing only `configuration` to `['m','m.b']` restores the machine into
**`m.b`**. Editing it to `[]` falls back to `state_ids` and restores `m.a` —
so neither form is refused and the two keys are never compared. The #143
read-side legality check runs *after* this selection, so a *legal* forged
configuration passes it.

**Wrapper mitigation:** cross-check `set(state_ids) <= set(configuration)`
before restore, or strip `configuration` and let the fallback rebuild it.

---

## 5. Not covered

Recorded rather than half-executed, so the gap is visible to the synthesis.

**Other tracks' remit** (listed in the brief, owned by the sibling battle
tracks on this commit; nothing here duplicates or pre-empts their verdicts):

- **Concurrency:** async chain/settle budget under 16 concurrent external
  senders during a self-generated chain (external must not reset the bound);
  `service_pool_size=1` with 50 plain services + `stop()` mid-service;
  done-callback double-fire; `RAISE` loop-side refusal hook exactly once per
  refusal (#157/#172/#173).
- **Fuzz/livelock:** config fuzzer across both engines with a 30 s watchdog
  (nested invoke cycles, `always` cycles, rollback+`onDone`, `sendTo`
  self-loops), ≥500 configs, trip observable via `last_error`/receipt
  (R6-01/02/03, #166–#168).
- **Determinism:** 50× identical traces both engines *including trip points*
  and equal lap counts; hash-seed sweep. (Per-engine determinism and the
  perf-PR aliasing sentinel **were** run here — `n8`, `q3-B`.)
- **Semantics:** guard-crash vs denied vs deferred vs unhandled 4-way matrix;
  `start()` ordering vs #116 (the #116 *persistence* aspect is covered by
  `n10` D); entry-window refusal at child vs root (the **root** case is
  `D7-persistence-1` above; the **child** case, which relies on the
  deliberate `_await_settled_for_snapshot()` race tolerance, was not
  separately attacked).
- **Observability:** hook matrix incl. loop-side `queue_full`, `chain_budget`
  on both engines, exactly-once, ordering.
- **Security:** `internal=True` forgery post-fix; `__slots__` attribute
  surface. (Redaction **was** re-checked here via `n6` D and passes.)

**Inside this track, deliberately not re-run:**

- `n9_soak.py` at 12 min and `m3` at 12 min — wall-clock bound; `m3` at 330 s
  with 200 machines covers the same property at higher cycle count. The
  reduction forfeits slow-leak/multi-minute-drift coverage only.
- `t2_property.py` and `t8_midstep_property.py` — superseded by `q3` and `q1`
  respectively, both of which are strictly stronger (see §1).
- `n5_corrupt_fuzz.py` at the brief's 5,000 mutations — run at 2,000.
- **`RealClock` persistence.** Every run here uses `SimulatedClock`. Timer
  lateness across a restore under a real clock (the R6-14 shape) is not a
  persistence result this round.
- **Cross-version migration.** v0→v2 and v1→v2 upcast are exercised only
  through `n5`'s fuzz and `m2-C`; a curated corpus of real older-version
  blobs does not exist.
- **Multi-process / concurrent snapshot of one interpreter.** All snapshots
  are taken from the owning thread or its plugin hooks.

---

## 6. Verdict

**DO NOT ADOPT BARE — ADOPT WITH A WRAPPER.** Downgraded from
`cec108b`'s unqualified **ADOPT** for this track, on the strength of one new
High and two unfixed round-6 findings.

The core property an OMS depends on is **sound and was measured at scale on
this build**: a snapshot taken at quiescence round-trips exactly, every time.
2,000 events with a snapshot *and a full restore-and-compare at every one of
the 2,000 quiescent points* → 2,000/2,000 OK, 0 raises, 0 mismatches
(`n2`); 1,406 snapshots across 350 random parallel machines → 0/0/0 (`m1`);
26,009 snapshot+restore cycles across 200 machines with executor services →
0/0/0 with a flat object count (`m3`); restore-and-resume trace parity at
every crash point on both engines (`q3-A`); no aliasing from the `__slots__`
perf work (`q3-B`).

What is not sound is the **edges around that window**:

1. **`D7-persistence-1` (High)** — the async `start()` descent is the one
   place the mid-step refusal fails open, and it writes an unrestorable blob.
   *Wrapper:* never snapshot from a hook before `await start()` returns.
2. **`D7-persistence-2` (High, `R6-07`)** — drift verification is one deleted
   key away from off. *Wrapper:* verify `machine_hash` yourself.
3. **`D7-persistence-3` (Medium, `R6-16` escalated)** — a forged
   `configuration` relocates the machine on restore. *Wrapper:* cross-check
   or strip `configuration`.

All three mitigations are a few lines in the adapter we already require for
CV-P05 (`restart_services=True` re-runs services — unchanged this round).
None of the three can lose, duplicate or strand a settled order; all three
are on the *read* or *start* path, not the steady-state write path.
**Persistence is not a gating concern for adoption, but it is no longer a
bare-adoption one either** — and the pattern round 6 named as its headline,
*"fixed" means "fixed on the engine the issue was filed against"*, reproduced
again here in `D7-persistence-1`.
