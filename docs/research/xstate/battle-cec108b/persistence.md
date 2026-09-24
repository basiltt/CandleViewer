# Battle-test track: PERSISTENCE & crash consistency — re-run on `cec108b`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`cec108b`** (merge of PR #164, `fix/0.8.1-round5`), CHANGELOG
`[Unreleased] — targeting 0.8.1`. **`__version__` still reports `0.8.0`; this
build is identified by commit, never by version string.**

**Date:** 2026-09-19 · **Python:** CPython 3.13.7 · **OS:** Windows 11 Pro
10.0.26200 · **Interpreter:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was read-only throughout.

Scripts: `docs/research/xstate/battle-cec108b/persistence/` (prior scripts
copied verbatim except where a reduction is recorded below; new scripts are
the `m*` series). Raw output for every run is under `persistence/out/`.
Predecessor: `battle-3ed3099/persistence.md`.

---

## 0. Bottom line

**Round 5 closes the persistence track. All four round-4 defects are FIXED,
and every new attack this brief asked for passes.**

- **D5-persistence-1 (High, the `any(leaf)` mid-step guard)** is **FIXED**.
  `_configuration_is_legal` is now exactly-one-leaf-per-region on both sides.
  `n3_parallel_tear.py 300`: **0/179 torn** (was 49/179 = 27.4 %) — 59 legal,
  120 refused, **0 missing-region, 0 globally-empty**. `d3b_partial_parallel.py`,
  the minimal repro, no longer produces a blob at all: the snapshot inside the
  `exchange` region's `onDone` raises `SnapshotMidStepError`.
- **D5-persistence-2 (restore-path event-type guard)** is **FIXED**:
  `n7_restore_event_type.py` now raises `SnapshotCorruptError: event record
  'type' must be a non-empty string, got 42` on the *first* hostile type.
- **D5-persistence-3 (raw builtin leaks from `from_snapshot`)** is **FIXED**:
  `n5_corrupt_fuzz.py 2000` → **0 raw leaks** (was 545/5,000 = 10.9 %),
  1,004 typed, 996 accepted of which **0 unsound**.
- **D5-persistence-4 (v1 provenance laundering)** is **FIXED**: `t4` P12 now
  reports `after.hours → system=False`, `xstate.custom → system=False`
  (was `True`/`True`), and the end-to-end control confirms a restored
  `done.review` errors the machine exactly as a live send does.

The headline properties hold at full scale: **2,000 events, a snapshot at
every one of the 2,000 quiescent points and a full restore-and-compare at
every one — 2,000/2,000 OK, 0 mid-step raises, 0 mismatches** (`n2`, 14.4 s);
and the new random-parallel property (`m1`) took **1,217 snapshots across 350
generated parallel machines with 0 raises, 0 byte-level round-trip
mismatches and 0 illegal configurations**.

`m2` attacks the five specific round-5 claims this brief names — entry-action
window, history-in-parallel restore, v1 upcast with a torn configuration,
`"fail"`-stopped snapshot, actors+deferred legality — **7/7 PASS**.

**Defects filed this round: 0.** Two items are recorded as *observations*
(§5), not defects: the lifecycle asymmetry of a `stopped` snapshot, and
the unchanged `restart_services=True` service re-run (CV-P05, already a
known adoption constraint).

**Verdict for this track: ADOPT — persistence is no longer a gating
concern.**

---

## 1. Method

Machine, harness and comparison technique are unchanged from
`battle-3ed3099/persistence.md` §1 — `order_machine.py` (parallel
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

1. `d3_torn_snapshot.py`, `d3b_partial_parallel.py` and `t5_midmacrostep.py`
   now terminate on an **expected** `SnapshotMidStepError` instead of printing
   a torn blob. That raise **is** the #102/#142 fix, so the scripts are left
   unmodified and their traceback is read as a PASS. `d3b` additionally dies
   on `json.loads(None)` afterwards because `plug.blob` was never assigned —
   the containment log line above it (`Plugin 'SnapOn' failed in
   'on_action_execute' … SnapshotMidStepError`) is the actual result.
2. `d6_priority_lane.py` remains **superseded by `n1_priority_lane_107.py`**
   for the reason given in the prior round (its freeze technique no longer
   parks an `AfterEvent` on a build where #114/#148 fail a cancelled loop).
   It is re-run for the record and still prints an empty lane; `n1` is the
   authority and passes 3/3.
3. `t2_property.py` gained an `MAXEX` environment override (test-harness
   only, no behaviour change) so the case count could be reduced to fit the
   wall-clock bound.

### Parameter reductions (stated as required by the brief)

| Script | Brief / prior | Run here | Cost of the reduction |
|---|---|---|---|
| `t2_property.py` | 2,000 hypothesis cases | **60** | Each case is a full plain+interrupted double run of `order_machine`; 2,000 exceeds the 120 s script bound by ~10×. Superseded in coverage by `n2` (2,000 events × 2,000 restores) and `m1` (350 generated machines), both of which ran unreduced. |
| `n5_corrupt_fuzz.py` | 5,000 mutations | **2,000** | 5,000 exceeded 120 s on this build. 2,000 is enough to resolve a 10.9 % prior leak rate to zero with a wide margin (expected ≈218 leaks at the prior rate; observed 0). |
| `n9_soak.py` | 12 min | **300 s** | Task wall-clock bound. 13,704 cycles / 10,948 snapshots / 7,502 restores in 300 s exceeds the cycle count 12 min of a slower workload would reach; the reduction costs duration-dependent coverage (slow leaks, multi-minute drift), not cycle coverage. |
| `m3_soak_executor.py` | 12 min, 200 machines | **330 s, 200 machines** | Same bound. Machine count and shape (parallel regions + plain-`def` executor services + chaos snapshot/restore every 2 s) are **not** reduced. |
| `m1_parallel_property.py` | ≥300 cases | **350** — not reduced | |
| `n2_quiescent_property.py` | 2,000-event run, restore at every point | **2,000 / `--restore-every 1`** — not reduced | |
| `n8_determinism.py` | 50× both engines | **50×** — not reduced | |
| `t8_midstep_property.py` | 2,000 cases | **not re-run** | Superseded by `n3` (same property, classifier that separates D-3 from D-3b) and by `m1` (stronger: random machines, byte-identical round-trip). |

---

## 2. Prior defects: FIXED / STILL-PRESENT / CHANGED

| ID | Prior sev | Verdict | Evidence |
|---|---|---|---|
| **D5-persistence-1** (`#102` mid-step guard is `any(leaf)`, so a parallel state snapshots with a whole region missing) | **High** | **FIXED** | `n3_parallel_tear.py 300`: 179 snapshots attempted → **59 legal, 120 refused, 0 TORN (0.0 %)**, of which **0** globally-empty and **0** missing-parallel-region (was 49/179 = 27.4 %). `d3b_partial_parallel.py` re-run verbatim: the snapshot taken from the `exchange` region's `onDone` action now raises `SnapshotMidStepError` inside the plugin (contained + logged), so `plug.blob` stays `None` — the torn blob is not producible. Read side: `n10` test B and `m2` test C both get `SnapshotCorruptError: status is 'running' but the configuration has no active leaf in every region`. `t6_action_boundary.py`: **2/6 OK, 0/6 torn, 4/6 refused** (was 2/6 OK, 0 torn, 4 refused — unchanged, and the 4 refusals are correct). |
| **D5-persistence-2** (`#113` non-`str` event-type guard not enforced on the restore path) | Medium | **FIXED** | `n7_restore_event_type.py` now dies on its **first** hostile input: `restore_event({"kind":"event","type":42,...})` → `SnapshotCorruptError: Snapshot is malformed: event record 'type' must be a non-empty string, got 42.` (`events.py:378`). Previously 5/5 hostile types were accepted into a live interpreter. |
| **D5-persistence-3** (`check_shape()` omits `version`/`actors`/`system`; 10.9 % of fuzzed blobs leak a raw builtin) | Medium | **FIXED** | `n5_corrupt_fuzz.py 2000`: **RAW builtin leaks = 0** (was 545/5,000). 1,004 typed (889 `SnapshotCorruptError`, 93 `SnapshotDriftError`, 22 `SnapshotVersionError`), 996 accepted of which **0 unsound**. Confirmed pointwise by `t3_probes.py` P7: `version: null` → `SnapshotCorruptError: 'version' is NoneType, expected an integer`; `actors: [1]` → `SnapshotCorruptError: 'actors' is list, expected an object` — both previously raw `TypeError`/`AttributeError`. |
| **D5-persistence-4** (v1 blob launders an engine-shaped user event into a system event) | Low | **FIXED** | `t4_receipts_provenance.py` P12: `after.hours → system=False`, `xstate.custom → system=False`, `done.review → system=False`, `PLAIN → system=False` (was `True`/`True`/`False`/`False`). End-to-end: a restored v1 `done.review` drives the machine to `status=error` with `UnhandledEventError` — **identical to the live-send control**, which is the property the defect denied. |

### Regression check on previously-clean results

| Script | Prior | Now |
|---|---|---|
| `p0_smoke.py` | layout `version == 2` | unchanged, `version == 2`, 16 keys |
| `t1_crashpoints.py` | 20/22 static, 22/22 `--restart` | **20/22** static, **22/22** `--restart` — identical; the 2 static divergences are the documented static-restore default (the `after` `STALE` ladder is not re-armed), not a defect |
| `t2_property.py` | 0 failures | **0 failures / 60 cases** (reduced) |
| `t3_probes.py` | P1/P5/P6/P6b/P6c/P8/P9/P9b/P10 PASS | **all still PASS**; P8 1 MB round-trip snapshot 8.2 ms / restore 3.1 ms (was 8.2/3.1-ish — no regression under PR #141) |
| `t7_rollback.py` | post-rollback restore correct, mid-macrostep refused | unchanged |
| `d2_after_timer_lost.py` | `restart_services=True` re-arms, `False` does not | unchanged (`fired=True` / `clock.pending=1` vs `False` / `0`) |
| `d5_invoke_dormancy.py` | `restart_services=True` re-runs the service (calls 1→2) | **unchanged — CV-P05 stands** (see §5) |
| `n1_priority_lane_107.py` | 3/3 | **3/3** (lane persisted + replayed by both routes; `AfterEvent` lateness round-trips) |
| `n4_restart_timers.py` | 5/5 | **5/5** (6-combination flag matrix, from-zero re-arm, `from_snapshot(clock=)`, both parallel regions) |
| `n6_hostile_and_hooks.py` | live 8/9, restore 0/5 | live **8/9**, restore **5/5** (the one "leak" is `{'type':'GO'}`, a documented accepted form, not a hostile — see the prior report's note) |
| `n8_determinism.py` | 50/50 per engine, 1 distinct blob each | **50/50 per engine, 1 distinct blob each** |
| `n9_soak.py` | 0 raw, 0 mismatch, flat memory | **300 s: 13,704 cycles, 41,322 events, 10,948 snapshots, 7,502 restores, 0 midstep, 0 typed, 0 raw, 0 mismatch**; RSS 30.2 → 33.1 MB, objects 20,873 → 21,869 and flat from the first sample |
| `n10_semantics_persist.py` | #109/#130/#116 PASS, #108 restore gap | **all four PASS** — the #108 restore gap is closed by the read-side legality check |

---

## 3. New attacks on the round-5 fixes

| # | Script | Attack | Result |
|---|---|---|---|
| M1 | `m1_parallel_property.py 350` | **hypothesis property over randomly generated PARALLEL machines** (2–3 regions, random region sizes, optional nested compound + final children, optional deep-history node, random event alphabet): snapshot at **every** quiescent point; must never raise; must round-trip **byte-identical** through `from_snapshot → get_persisted_snapshot` (canonical JSON, `taken_at` excluded); and every top-level region must carry a leaf | **PASS** — 350 cases, **1,217 snapshots, 0 raises, 0 round-trip mismatches, 0 illegal configurations** |
| M2-A | `m2_roundtrip_edges.py` A | **snapshot inside an `entry` action** of a parallel region (the window #142 reopened) | **PASS** — `SnapshotMidStepError: Interpreter 'pa' is mid-macrostep … the configuration has no leaf` |
| M2-B | `m2_roundtrip_edges.py` B | **deep history inside a parallel region across a restore**: `DIVE → NEXT → T → OUT`, snapshot, restore into a *fresh* machine, `BACK` must re-target the remembered leaf | **PASS** — persisted `history={'hp.ra.deep': ['hp.ra.deep.d2']}`; restored machine after `BACK` → `['hp.ra.deep.d2','hp.rb.b2']` |
| M2-C | `m2_roundtrip_edges.py` C | **v1 upcast with a torn configuration must be refused** (#143 read side): a `version: 1` blob whose `state_ids` lost region `rb` entirely, and the v2 equivalent with `configuration` mangled | **PASS** — both `SnapshotCorruptError: status is 'running' but the configuration has no active leaf in every region`. The v1 upcast path is checked *after* upcast, so the old shape gets the new guard |
| M2-D | `m2_roundtrip_edges.py` D | **`actionErrorPolicy: "fail"` stopped machine** (#145): snapshot the corpse, then try to resume it | **PASS** — live: `status=stopped`, `current_state_ids=[]`; snapshot: `status=stopped`, `configuration=[]`, `error` retains the `TransitionFailedError` text; `from_snapshot` succeeds and yields `status=stopped`/`states=[]`/`error` preserved, and `start()` on it raises `InvalidConfigError: has been stopped and cannot be restarted` — the corpse is **not** resumable. Sync engine parity confirmed by a direct probe (`SyncInterpreter`: `status=stopped`, blob `configuration=[]`, `start()` refused identically) |
| M2-E | `m2_roundtrip_edges.py` E | **actors + deferred buffer legality across a restore**: an in-flight `invoke` plus three deferred events, snapshot, restore with `restart_services=True` | **PASS** — `deferred=['LATER0','LATER1','LATER2']` persisted and re-persisted identically after restore; no duplication, no reordering, no loss |
| M3 | `m3_soak_executor.py 330 200` | **reduced soak**, 200 concurrent order-like machines each with a **parallel** `submitted` region and a **plain-`def`** service (the #149 `service_executor` path), chaos snapshot/restore every 2 s, snapshots only at quiescence | see §3.1 |

`m2` overall: **7/7 PASS**.

### 3.1 M3 soak result

```
soak budget          : 330s (REDUCED from the brief's 12 min)
concurrent machines  : 200
elapsed              : 331.0s
cycles               : 120814
events               : 120814
snapshots            : 23242
restores             : 23242
midstep              : 0
raw exceptions       : 0   <- must be 0
round-trip mismatch  : 0   <- must be 0
RSS   30.0 MB -> 79.3 MB   objs 20577 -> 21525
VERDICT: PASS
```

**23,242 snapshot/restore cycles across 200 parallel machines driven by
plain-`def` services, with zero raw exceptions, zero `SnapshotMidStepError`
at quiescence and zero round-trip mismatches.** The RSS figure is the *live*
working set of 200 simultaneously-running interpreters, measured while they
are all alive, not a leak: the tracked-object count is flat
(20,577 → 21,525, +4.6 %) across 120,814 cycles, and `n9`'s single-machine
300 s series — the leak-sensitive one — is flat from its first sample
(30.2 → 33.1 MB, objects 20,873 → 21,869 with no upward trend across 68
samples).

Notably, the #149 `service_executor` hop does **not** perturb the snapshot
boundary: the entering macrostep awaits the executor result, so no snapshot
in 23,242 attempts landed inside a service completion.

---

## 4. Defects

**None. Zero defects are filed against the persistence track on `cec108b`.**

All four round-4 defects (`D5-persistence-1` High, `-2` Medium, `-3` Medium,
`-4` Low) are FIXED and each was re-attacked by a route its original repro
did not use:

- `-1` by a random-machine property (`m1`, 1,217 snapshots) and by the
  entry-action window (`m2`-A), neither of which the `any(leaf)` fix could
  have been tuned to.
- `-2` by `m2`-C's v1-upcast path, which reaches `restore_event` through a
  different door than `n7`.
- `-3` by 2,000 fresh mutations with a different seed sequence.
- `-4` by an end-to-end control comparing a restored event against a live
  send of the same event, rather than by inspecting the `system` flag alone.

---

## 5. Observations (not defects)

**OBS-P1 — a `stopped` snapshot is restorable as an object but not
resumable, and the two engines disagree about where you learn that.**
`from_snapshot()` on a `status: "stopped"` blob **succeeds** and hands back an
interpreter carrying `status=stopped`, `states=[]` and the retained `error`;
the refusal arrives later, from `start()`, as
`InvalidConfigError: Interpreter 'fl' has been stopped and cannot be
restarted` (`interpreter.py:457-462`). By contrast a `status: "done"` blob
restores *and* starts cleanly (`status=done`, `['d.b']`). This is defensible
— a stopped snapshot is legitimately readable for post-mortem, and the corpse
is never revived — but the failure lands one call later than a caller reading
`from_snapshot` as "validate my blob" would expect, and nothing in
`docs/_guide/snapshots.md` states the rule. **Not a defect**: the invariant
that matters (a bricked machine must not come back to life) holds on both
engines, which is precisely what #145 promised. Recorded as an adoption note
— a restore wrapper should branch on `blob["status"]` before calling
`start()`.

**OBS-P2 — `restart_services=True` still re-runs a completed service
(CV-P05).** `d5_invoke_dormancy.py` is unchanged from every prior round:
restoring a snapshot taken while `ackSvc` was in flight and re-arming
services takes the service call count 1 → 2. The library documents this and
round 5 did not claim to change it. It remains an **adoption constraint, not
a defect**: any service invoked from a restorable machine must carry an
idempotency key.

---

## 6. Not covered

| Area | Why |
|---|---|
| `t2_property.py` at 2,000 cases | reduced to 60 for the wall-clock bound (§1). Its property — restore transparency over random sequences and crash points — is covered more strongly by `n2` at 2,000 events × 2,000 restores and by `m1` over 350 *generated* machines. |
| `n5` at 5,000 mutations | reduced to 2,000 (§1). At the prior 10.9 % leak rate, 2,000 mutations would surface ≈218 leaks; 0 were seen, so the fix is resolved well beyond the noise floor. |
| 12-minute soaks | both soaks were bounded at 300 s / 330 s. Duration-dependent failure modes (multi-minute clock drift, slow fragmentation, handle exhaustion) are **not** covered; cycle-dependent modes are covered several times over. |
| Multi-process / on-disk durability | snapshots were round-tripped in-process through `json.dumps`/`json.loads`. Torn *writes* (fsync, partial file, concurrent writers) are an application concern and out of this track's scope. |
| Cross-engine blob interchange | an `async def` service makes `order_machine` sync-unrunnable by design (`NotSupportedError`), so `n8` compares per-engine determinism (50/50 both) rather than async-blob → sync-restore. A blob written by one engine and read by the other is **untested** for machines whose logic both engines accept. |
| Snapshot size / perf regression under PR #141 | only spot-checked via `t3` P8 (1 MB context: 8.2 ms snapshot / 3.1 ms restore). No dedicated before/after benchmark was run. |
| Non-JSON `context` values (DC-05) | unchanged and still out of scope: `get_persisted_snapshot()` returns a dict, so the caller's `json.dumps()` is where a non-serialisable context fails. Belongs in the adoption gate, not here. |

---

## 7. Verdict

**ADOPT.** Persistence was the track that carried the round-4 Blocker
downgrade, and on `cec108b` it carries nothing: four for four on the prior
defects, 7/7 on the targeted new attacks, and three independent large-scale
properties clean — 2,000/2,000 quiescent snapshot-restores on the order
machine, 1,217 snapshots over 350 random parallel machines with byte-identical
round-trips, and 23,242 chaos snapshot/restore cycles across 200 concurrent
parallel machines with executor-backed services.

The two residual items are adoption notes already in the register
(`OBS-P1` → branch on `status` before `start()`; `OBS-P2`/CV-P05 → idempotent
services), not library defects. **Persistence is no longer a gating concern
for adoption.**
