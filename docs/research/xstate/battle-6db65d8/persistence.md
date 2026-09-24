# Battle-test track: PERSISTENCE & crash consistency — re-run on `6db65d8`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`6db65d8`** ("Merge pull request #191 from
basiltt/fix/0.8.1-round7"), CHANGELOG `[Unreleased] — targeting 0.8.1`.
**`__version__` still reports `0.8.0`; this build is identified by commit,
never by version string.**

**Date:** 2026-09-21 · **Python:** CPython 3.13.7 · **OS:** Windows 11 Pro
10.0.26200 · **Interpreter:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was read-only throughout.

Scripts: `docs/research/xstate/battle-6db65d8/persistence/` (prior scripts
copied from `battle-221ce7c/persistence/`; new scripts are the `r*` series).
Raw output for every run is under `persistence/out/`; the plain-`def` service
lane writes `out/<script>.DEF.txt`.
Predecessor: `battle-221ce7c/persistence.md`.

---

## 0. Bottom line

**All three defects this track carried into round 7 are FIXED, and the
persistence core is sound at scale. The new findings are all on the
*boundary* of persistence — provenance, bounds and parity — and the two
serious ones are not persistence bugs at all but hold through the
persistence surface.**

- **Every prior defect is FIXED.** `D7-persistence-1` (async `start()` wrote
  an unrestorable blob) — the `q1b` minimal repro now prints
  `async=0 sync=0`, and the 320-machine hook property finds **0 torn in any
  window including `entry@start`**. `D7-persistence-2` (`machine_hash: None`
  disables drift) and `D7-persistence-3` (forged `configuration` wins) both
  refuse correctly. `t6_action_boundary` went 5/6 → **6/6 refused**.
- **The core property re-measured on BOTH service lanes.** 1,200 events with
  a snapshot *and a full restore-and-compare at every quiescent point*, run
  once with `async def` and once with `def` services → **1,200/1,200 OK, 0
  midstep, 0 mismatch in both lanes**. A new property over **320 generated
  machines with invoked children** (parallel regions, `after` timers, child
  machines whose entry action half-writes its context) → 5,046 snapshot
  attempts, **0 torn, 0 half-written child harvests, 0 round-trip
  mismatches, 0 raw exceptions**. A 424 s / 200-machine soak on the **async**
  service lane with an external priority producer → 19,530 snapshot+restore
  cycles, 0 midstep, 0 raw, 0 mismatch, **0 `chain_budget` drops out of
  92,394 external priority sends**.
- **`D8-persistence-1` (High, NEW).** `DoneEvent` and `AfterEvent` are
  `NamedTuple`s with **no provenance field and no `system` property at
  all** — the #85/#180 marker they are checked against does not exist on
  them. Any caller can construct `DoneEvent(type="done.invoke.k", ...)` and
  `send()` it; on the async engine it **drives the real `onDone` transition
  while the genuine service is still running**, and on both engines it is
  exempt from `strict` *and* `onUnhandled: "error"`, which reject the
  identical type sent as a plain `Event`. Round 7 hardened `Event` and left
  the two event classes that *mean* "the engine did this" unguarded.
- **`D8-persistence-2` (High, NEW).** The #185 fix moved the drift bypass
  from "`machine_hash` is absent" to "the payload declares version 0". Both
  fields are in the same JSON object and edited by the same hand, so the
  bypass survives verbatim as a **downgrade**: set `version: 0`, drop
  `machine_hash`, and a snapshot restores clean into a structurally
  different machine under the default `verify_machine_hash=True`. The
  restored machine then accepts an event the snapshotting machine never
  declared.
- **`D8-persistence-3` (Medium, NEW).** `start(children_timeout=)` is
  implemented as `asyncio.wait(..., timeout=)`, which can only cut a task at
  an `await`. A child whose entry action is a **plain `def`** blocks the
  loop thread, so `await start()` runs for the full `N × delay` **regardless
  of the bound and with no warning** — 20 children × 100 ms took 2.02 s at
  `children_timeout=0.05`, `0.2` *and* `1.0`. The `async def` twin honours
  every bound. This is #181 fixed on one service kind only.
- **`D8-persistence-4` (Medium, NEW).** `#179`'s "both service kinds trip at
  the same lap count" does not hold for the invoke ping-pong (#168) and
  rollback+`onDone` (#167) shapes: 500 fuzzed configs show `def` → TRIP
  50/50 and `async def` → no trip 50/50 for both. The chain *is* bounded and
  *is* eventually observable via `on_event_dropped`, but the caller's
  `await send(..., wait=True)` receipt resolves **ok** after 1 lap while the
  cycle runs 26 more behind it.
- **`D8-persistence-5` (Low, NEW).** `state_ids: []` beside a populated
  `configuration` is not a contradiction the #186 checker recognises, so a
  forged `configuration` still relocates the machine (`m.a` → `m.b`). The
  symmetric case (`configuration` forged, `state_ids` intact) is correctly
  refused.

**Defects filed this round: 5 new. All three carried defects: FIXED.**

**Verdict for this track: ADOPT WITH A WRAPPER** — upgraded in substance
(the persistence core is now clean where it was not) but unchanged in form,
because the wrapper is still required, for different reasons than last round.

---

## 1. Method

Machine, harness and comparison technique are unchanged from
`battle-221ce7c/persistence.md` §1.

### Exact command shape

```
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
PYTHONPATH=_ref/xstate-statemachine/src:. \
[XS_SVC=def] ".venv-main/Scripts/python" <script> [args]
```

`run.sh` / `rund.sh` in the script directory wrap this.

### The `def` / `async def` lane (the brief's standing requirement)

`order_machine.py` — the machine behind `t1`, `t4`, `t6`, `n2`, `n3`, `n5`,
`d5` — had a single `async def ack_service`. A plain-`def` twin
(`ack_service_sync`) was added beside it, selected by `XS_SVC=def`, and
every service-bearing prior script was re-run in both lanes. This is a
harness change in **our** copy of the machine, not the library. New scripts
parametrise over both kinds internally.

### Parameter reductions (stated as required by the brief)

| Script | Brief | Run here | Cost of the reduction |
|---|---|---|---|
| `r6_child_hook_property.py` | ≥300 machines | **320** (160 per kind) — not reduced | |
| `r12_livelock_fuzz.py` | ≥500 configs × {def, async} × both engines | **500** async-engine configs, 250 of them also on the sync engine — not reduced | The sync engine cannot take an `async def` service (`NotSupportedError`, documented), so the `sync × async-service` cell does not exist |
| `r8_soak_async.py` | 12 min, 200 machines | **424 s, 200 machines** | Task wall-clock bound. Machine count, async services, chaos snapshot/restore and the external priority producer are **not** reduced; the reduction costs duration-dependent coverage (slow leaks), not cycle coverage — 19,530 snapshot+restore cycles and 92,394 external priority sends were executed |
| `n2_quiescent_property.py` | 2,000 events, restore at every point | **1,200 / `--restore-every 1`, twice** (once per service kind) | Run in both lanes inside the same budget the single 2,000-event run used; 2,400 total restore-and-compare cycles, more than the prior round's 2,000 |
| `n5_corrupt_fuzz.py` | 5,000 mutations | **2,000 async lane + 1,200 def lane** | Exceeds the 120 s script bound; 0 raw / 0 unsound in both |
| `r11_determinism.py` | 50× both engines both kinds | **50×** — not reduced | |
| `q1_hook_snapshot_property.py` | 320 machines | **320** — not reduced; superseded by `r6` (adds invoked children) | |

### Scope note

This report covers the **persistence** track. The brief's concurrency, fuzz,
determinism, semantics, observability and security families were executed
**only where they hold through the persistence surface** — the marker
forgery (`r9`/`r10`) because a forged completion is what a snapshot's
`pending_events` replays; the livelock fuzz (`r12`/`r13`) because a machine
that never trips never reaches a snapshottable quiescence; the determinism
sweep (`r11`) because a non-reproducible blob is not a checkpoint. The rest
is in §5.

---

## 2. Prior defects: FIXED / STILL-PRESENT / CHANGED

### 2.1 Defects carried into this round

| ID | Prior sev | Verdict on `6db65d8` | Evidence |
|---|---|---|---|
| **D7-persistence-1** (async `start()` writes a snapshot its own reader refuses; #182) | High | **FIXED** | `q1b_start_entry_window_min.py`: `write-accepted / read-refused blobs: async=0 sync=0`, VERDICT PASS (was `async=1`). `q1 320 7`: **TORN by window `{}`**, 0/7,622 (was 720/7,622, all in `entry@start`). `t6_action_boundary.py`: **6/6 refused** in both service lanes (was 5/6). Fix confirmed at `interpreter.py:580` — `self._processing = True` now wraps the initial `_enter_states` descent, exactly the suggested fix. |
| **D7-persistence-2** (`machine_hash: None`/absent disables drift; #185, `R6-07`) | High | **FIXED — for versioned payloads.** See `D8-persistence-2` for the residue. | `q2_readside_gaps.py`: all three rows now `SnapshotDriftError` (was 2 ACCEPTED). `r2_readside_matrix.py` §1: every `version ∈ {1,2} × hash ∈ {none, removed}` cell → DRIFT, 16/16. |
| **D7-persistence-3** (contradictory `configuration` wins over `state_ids`; #186, `R6-16`) | Medium | **FIXED — for the filed direction.** See `D8-persistence-5` for the mirror case. | `q2_readside_gaps.py`: both rows now `SnapshotCorruptError` (was ACCEPTED, one of them *relocating* the machine). `r2` §2: `empty`, `contradict`, `leaf stripped`, `superset` all refused. |

### 2.2 Round-5 defects — regression check (both service lanes)

| ID | Verdict | Evidence |
|---|---|---|
| **D5-persistence-1** (`#102` mid-step guard is `any(leaf)`) | **FIXED (holds)** | `n3_parallel_tear.py 300`: 179 attempts → **0 TORN**, 179 refused. Identical in the `def` lane. |
| **D5-persistence-2** (`#113` non-`str` event type on restore) | **FIXED (holds)** | `n7_restore_event_type.py` dies on the first hostile input with `SnapshotCorruptError`; non-zero exit is PASS for this script. |
| **D5-persistence-3** (raw builtins leak from `from_snapshot`) | **FIXED (holds)** | `n5_corrupt_fuzz.py 2000` (async lane): **RAW = 0**, 1,078 typed, 922 accepted of which **0 unsound**. `def` lane at 1,200: RAW = 0, 0 unsound. |
| **D5-persistence-4** (v1 provenance laundering) | **FIXED (holds)** | `t4_receipts_provenance.py` P12 in both lanes: `after.hours`, `xstate.custom`, `done.review`, `PLAIN` all → `system=False`; the restored `done.review` errors the machine exactly as the live control does. |

### 2.3 Regression check on previously-clean results

| Script | Prior (`221ce7c`) | Now (`6db65d8`) | `def` lane |
|---|---|---|---|
| `p0_smoke.py` | version 2, 16 keys | unchanged | — |
| `t1_crashpoints.py` | 20/22 static | **20/22** — identical; the 2 divergences are the documented static-restore timer default | **20/22**, byte-identical divergence text |
| `t3_probes.py` | P1/P5/P6/P8/P9/P10 PASS | all still PASS | — |
| `t6_action_boundary.py` | 1/6 OK, 5 refused | **0/6 OK, 0 torn, 6/6 refused** — the #187 improvement | identical |
| `t7_rollback.py` | post-rollback restore correct | unchanged | — |
| `d2_after_timer_lost.py` | `restart_services` re-arms | unchanged | — |
| `d5_invoke_dormancy.py` | `restart_services=True` re-runs the service | **unchanged — CV-P05 stands** | **confirmed in the `def` lane: service calls 1 → 2** |
| `n1_priority_lane_107.py` | 3/3 | **3/3** | — |
| `n2_quiescent_property.py 1200 --restore-every 1` | 2,000/2,000 | **1,200 snapshots, 0 midstep, 0 raises, 1,200 restores, 0 mismatches, 24.8 s** | **1,200/1,200, 0/0/0, 21.6 s** |
| `n4_restart_timers.py` | 5/5 | **5/5** | — |
| `n5_corrupt_fuzz.py` | 0 raw, 0 unsound | **0 raw, 0 unsound** | **0 raw, 0 unsound** |
| `n6_hostile_and_hooks.py` | redaction targeted, 13/13 API | unchanged; secrets LEAKED `[]`, `qty` still visible | — |
| `n8_determinism.py` | per-engine determinism PASS | **PASS** | superseded by `r11` (adds kind parity + hash-seed sweep) |
| `n10_semantics_persist.py` | all four PASS | **all four PASS** | — |
| `m1_parallel_property.py 350` | 1,406 snapshots, 0/0/0 | **1,196 snapshots, 0 raises, 0 mismatches, 0 illegal** | superseded by `r6` |
| `m2_roundtrip_edges.py` | 7/7 PASS | **7/7 PASS** (A/B/C/D all PASS) | — |
| `q1_hook_snapshot_property.py 320 7` | 720 torn | **0 torn, 0 mismatch, 0 raw** | superseded by `r6` |
| `q2_readside_gaps.py` | 4/4 gaps present | **VERDICT PASS** — all four refused | — |
| `q3_resume_parity_sentinel.py` | PASS | **PASS** — 9 crash points × 2 engines, 0 divergences; no `__slots__` aliasing | — |

---

## 3. New attacks on this round's machinery

| # | Script | Attack | Result |
|---|---|---|---|
| R2 | `r2_readside_matrix.py` | **#185 x #186 cross product**: `version` in {absent,0,1,2} x `hash` in {honest,wrong,none,removed} x target in {same,drifted} (32 cells), plus 9 `configuration`/`state_ids` mutations | **FAIL** — 31/32 hash cells correct; the v0/absent-version rows accept into the drifted machine (by design, but reachable — `D8-persistence-2`). 8/9 configuration cells correct; `state_ids: []` relocates (`D8-persistence-5`) |
| R3 | `r3_version_downgrade.py` | **Version downgrade**: strip/zero `version`, strip `machine_hash`, restore into a structurally different machine, then send an event only the *new* machine declares | **FAIL — `D8-persistence-2`.** 3/3 downgrade forms ACCEPTED into the drifted machine; control (intact blob) correctly `SnapshotDriftError` |
| R4 | `r4_round7_machinery.py` | **#183/#184** (snapshot the parent while an invoked child is inside its entry action), **#181** (`children_timeout` with 50 slow children), **#179** (`_chain_owed` under 100 never-completing coroutine services + `stop()`) — all on both service kinds | **A: PASS** (refused `child=True`, worst latency **0.3 ms**, no half-applied harvest). **C: PASS** (`_chain_owed` 100 -> 0, `stop()` in 0.01 s, no hang, no leak). **B: FAIL — `D8-persistence-3`** |
| R5 | `r5_children_timeout_def.py` | **Minimal `children_timeout`**: hold N and delay fixed, sweep the bound across {0.05, 0.2, 1.0, None} on both service kinds | **FAIL — `D8-persistence-3`.** `def`: 2.02 s at *every* bound, 0 warnings. `async`: 0.05 / 0.11 / 0.11 s, warning fires |
| R6 | `r6_child_hook_property.py 320 11` | **Snapshot from every hook, WITH invoked children.** 320 generated parallel machines (1-3 regions, `after` timers, split `onUnhandled`), each invoking a `def` service, an `async def` service or a **child machine whose entry action half-writes its own context**. 5 accept criteria incl. "no child actor caught half-written" and byte-identical round-trip | **PASS** — 5,046 attempts, 4,406 refused, 640 accepted, **0 torn, 0 half-written child, 0 mismatch, 0 raw**; windows incl. `entry@start` 634, `unhandled` 1,222, `quiescent` 320 |
| R7 | `r7_child_actor_restore.py` | **Invoked child machine across a restore**, both kinds x `restart_services` in {False, True}, with a field-level diff of the `actors` record | **PASS** — child `state_ids` and context survive (`kid.s2`, `{'v': 1}`); every field equal across the restore. The apparent round-trip mismatch is the child's **nested `taken_at`**, a harness artefact, now stripped recursively in `r6` |
| R8 | `r8_soak_async.py 420 200` | **200-machine soak on the ASYNC service lane** with parallel regions, chaos snapshot/restore at quiescence, and an external `send(priority=True)` producer (#180: 0 charged drops) | **PASS on every persistence criterion** — see 3.3 |
| R9 | `r9_marker_forgery.py` | **Forge the engine-completion marker**: removed `system=` kwarg, `Event` subclass overriding `.system`, `dataclasses.replace`, `_provenance`/`__dict__`/`object.__setattr__`, copy/deepcopy/pickle+retype, sentinel theft, and snapshot `pending_events` laundering — each checked **end-to-end** against `strict` + `onUnhandled: "error"` | **`Event` is sound; `DoneEvent`/`AfterEvent` are not** — see 3.2 and `D8-persistence-1` |
| R10 | `r10_doneevent_forgery.py` | **Minimal `DoneEvent` forgery** on a `strict` machine whose service **hangs**, so reaching the `onDone` target can *only* be the forged event. Controls: the real completion, and the same type as a plain `Event`. Both kinds | **FAIL — `D8-persistence-1`.** 6 failures across both lanes |
| R11 | `r11_determinism.py` | **Determinism**: 50 identical runs per (engine x service kind) cell; service-kind parity; engine parity; `PYTHONHASHSEED` sweep on `machine_hash` | **PASS** — 1 distinct blob in every cell; `def`-blob == `async`-blob on the async engine; **async-engine blob == sync-engine blob**; `machine_hash` identical across all 4 hash seeds |
| R12 | `r12_livelock_fuzz.py 500 5` | **Livelock fuzzer**, 30 s watchdog: `always` cycles, invoke ping-pong, rollback+`onDone`, `sendTo` self-loops, `raise` self-sends x {def, async def} x both engines. Every trip must be observable | **0 HANGS, 0 SILENT trips** — but a systematic service-kind parity gap, `D8-persistence-4` |
| R13 | `r13_chain_parity_min.py` | **Minimal parity probe** for the two gap shapes: one character differs (`def` vs `async def`); measures trip, lap count, whether the cycle is *still turning* 1 s later, and whether the trip becomes observable late | **FAIL — `D8-persistence-4`**, with the mitigating detail in 3.4 |

### 3.1 R6 — hook property with invoked children

```
machines               : 320  (160 per service kind, seed 11)
snapshot attempts      : 5046
  refused (legal)      : 4406
  accepted             : 640
TORN / inconsistent    : 0   <- must be 0
half-written child     : 0   <- must be 0
round-trip mismatches  : 0   <- must be 0
RAW exceptions         : 0   <- must be 0
windows exercised      :
    entry                    850
    entry@start              634
    exit                     850
    on_transition            850
    on_transition@start      320
    quiescent                320
    unhandled                1222
TORN by window         : {}
VERDICT: PASS
```

This is strictly stronger than round 7's `q1` — it adds `invoke`, child
machines, and the half-written-child criterion — and the window that carried
all 720 of last round's torn blobs (`entry@start`, 634 attempts here) is
clean.

### 3.2 R9 — what the provenance marker does and does not cover

```
  1. Event(type=..., system=True)       refused  TypeError: unexpected keyword
  2. Event subclass overriding .system  FORGED (the OBJECT lies)
  4. _provenance =                      refused  FrozenInstanceError
  4. __dict__ update                    refused
  4. object.__setattr__                 refused

=== end-to-end: does the forged event bypass strict/onUnhandled? ===
  control: plain UNDECLARED             raised UnknownEventError (enforced)
  subclass claiming system=True         raised UnknownEventError (enforced)
  forged _provenance sentinel           raised UnknownEventError (enforced)

surface check:
  DoneEvent   has .system=False has ._provenance=False type=tuple
  AfterEvent  has .system=False has ._provenance=False type=tuple
  Event       has .system=True  has ._provenance=True  type=object
```

Route 2 is **not** a breach: the object lies about itself, but the engine
does not ask it — the end-to-end row shows `strict` still rejecting it. The
`Event` hardening from #85/#180 holds against every route tried. The surface
check is the finding: the two classes that *mean* "the engine produced this"
are `tuple` subclasses with no marker to check.

### 3.3 R8 — 200-machine soak on the async service lane

```
services             : ASYNC def (the #179 charged-completion lane)
soak budget          : 420.0s (REDUCED from the brief's 12 min)
concurrent machines  : 200
elapsed              : 424.2s
cycles               : 30798
snapshots            : 19530
restores             : 19530
midstep              : 0
ext_sent             : 92394
ext_dropped          : 1
raw exceptions       : 0   <- must be 0
round-trip mismatch  : 0   <- must be 0
drop reasons         : {'stopped': 1}
RSS   30.4 MB -> 160.6 MB   objs 20672 -> 21473
```

**19,530 snapshot+restore cycles across 200 machines with `async def`
services, zero raw exceptions, zero `SnapshotMidStepError` at quiescence,
zero round-trip mismatches.** The script's own verdict prints FAIL only
because it treats *any* drop as fatal; the one drop is `reason='stopped'`
(an external send racing `stop()` at teardown), **not** `chain_budget`.
**#180 holds: 0 of 92,394 external priority sends were charged.** The
leak-sensitive figure is the tracked-object count, flat at **+3.9 %
(20,672 -> 21,473)**; RSS is the live working set of 200 simultaneous
interpreters. CPU stayed bounded; no livelock.

### 3.4 R13 — the service-kind parity gap, in full

```
maxIterations = 25; the ONLY difference between the two async-engine
rows of each block is `def svc` vs `async def svc`.

=== invoke_pingpong
  [invoke_pingpong sync ] tripped=True  laps=28  status=running
       late-observable after +1s: last_error=None drops=1
  [invoke_pingpong def  ] tripped=True  laps=27  after +1s laps=27  still_turning=False
       late-observable after +1s: last_error=None drops=1
  [invoke_pingpong async] tripped=False laps=1   after +1s laps=27  still_turning=True

=== rollback_ondone
  [rollback_ondone def  ] tripped=True  laps=0   still_turning=False
       late-observable after +1s: last_error=None drops=1
  [rollback_ondone async] tripped=False laps=0   still_turning=False
```

Read carefully, this is **less bad than the fuzzer's summary suggests, and
is filed as Medium, not High**:

- The async lane **is bounded** — it reaches 27 laps, the same total as the
  `def` lane, and then stops (`still_turning` is measured across a further
  second of wall clock). There is no unbounded livelock.
- The trip **is** eventually observable: the `late-observable` line shows
  `drops=1` on the lanes that print it, i.e. `on_event_dropped` fires.
- What differs is **when the caller learns**. On the `def` lane
  `await send("PING", wait=True)` returns after the chain has run and the
  receipt carries the error. On the `async def` lane the same call returns
  **ok after 1 lap**, and the remaining 26 laps run behind the caller's
  back. Sync-vs-async-`def` also differs by one lap (28 vs 27).

So #179's bound is real on both kinds; its **parity claim** ("both service
kinds now trip at the same lap count as the sync engine") is not.

---

## 4. Defects

### D8-persistence-1 — `DoneEvent` / `AfterEvent` carry no provenance and are exempt from `strict` (High, NEW)

**Severity: High.** A caller can fabricate a service completion. On the async
engine it drives the real `onDone` transition **while the genuine service is
still running**, so an order can be advanced past a settlement step that
never completed — and the same forged event is invisible to `strict` and to
`onUnhandled: "error"`, the two mechanisms that exist to catch exactly this.
Not a Blocker only because it requires code inside the process that already
holds the interpreter handle.

**Repro:** `battle-6db65d8/persistence/r10_doneevent_forgery.py` (minimal,
both kinds, service hangs so the target is unreachable by any other route);
`r9_marker_forgery.py` for the surrounding surface.

**Observed** (`out/r10_doneevent_forgery.txt`):

```
  [def  ] control: Event('done.invoke.k')    ['sec.a'] -> ['sec.a']  status=running
  [def  ] FORGED DoneEvent('done.invoke.k')  ['sec.a'] -> ['sec.a']  status=running
        ^ silently swallowed: strict did NOT reject it and onUnhandled:'error' did NOT fire
  [async] control: Event('done.invoke.k')    ['sec.a'] -> ['sec.a']  status=error
  [async] FORGED DoneEvent('done.invoke.k')  ['sec.a'] -> ['sec.done_']  status=running
        ^ the forged completion DROVE the onDone transition while the real
          service is still running
  [async] FORGED DoneEvent(no such actor)    ['sec.a'] -> ['sec.a']  status=running
        ^ silently swallowed
```

The `[async] control` row is the discriminator: the **identical type**
(`done.invoke.k`) sent as a plain `Event` errors the machine, and sent as a
`DoneEvent` moves it.

**Root cause.** `src/xstate_statemachine/events.py:125-135` — the
`_provenance` field and the `system` property are defined on the `Event`
**dataclass** only. `DoneEvent` (`events.py:145`) and `AfterEvent`
(`events.py:453`) are `NamedTuple`s:

```
  DoneEvent   has .system=False has ._provenance=False type=tuple
  AfterEvent  has .system=False has ._provenance=False type=tuple
  Event       has .system=True  has ._provenance=True  type=object
```

`hasattr(ev, "system")` is `False` for both, so every `getattr(ev, "system",
...)`-style check and every `strict` / `onUnhandled` gate keyed on event
provenance either short-circuits or treats the class itself as the
authority. #85 hardened the class a user was *expected* to construct and
left the two classes that assert engine authorship constructible by anyone.

**Suggested fix:** give `DoneEvent`/`AfterEvent` the same `_provenance`
sentinel (or make the engine stamp completions with a wrapper it checks on
receipt), and make `strict` treat a `DoneEvent` whose `src` names no live
actor as unknown rather than as privileged.

**Wrapper mitigation (ours):** never expose the raw `send()` to order-flow
code; the adapter accepts a typed command object and constructs the event
itself. This is already our shape for CV-C07.

### D8-persistence-2 — the #185 drift bypass is reachable by version downgrade (High, NEW)

**Severity: High.** Drift verification is still one edit away from off, under
the default `verify_machine_hash=True`. #185 closed the "delete one key"
form and left the "delete two keys" form, because the discriminator it moved
to (`version`) is in the same attacker-controlled object as the thing it
guards.

**Repro:** `battle-6db65d8/persistence/r3_version_downgrade.py`; matrix
context in `r2_readside_matrix.py` part 1.

**File:line:** `src/xstate_statemachine/persistence.py:323-336`
(`snap_hash = snapshot.get("machine_hash")` / `versioned = bool(version)` /
`if snap_hash is None: if not versioned: return  # v0: nothing to check`).

**Observed** (`out/r3_version_downgrade.txt`):

```
snapshot version=2 hash='510abea7b8ae24b2'
machine A hash=510abea7b8ae24b2  machine B hash=bf69643ef9e9a900
CONTROL intact -> SnapshotDriftError (correct)
  version=0 + hash removed            ACCEPTED into DRIFTED machine: ['m.a'] -> after JUMP ['m.c']
  version key removed + hash removed  ACCEPTED into DRIFTED machine: ['m.a'] -> after JUMP ['m.c']
  version=0 + hash=None               ACCEPTED into DRIFTED machine: ['m.a'] -> after JUMP ['m.c']
```

`JUMP` is an event machine A never declared; the restored interpreter is
live and running machine B's chart with machine A's state.

**Suggested fix:** the v0 bypass cannot be keyed on anything inside the
payload. Either require the caller to opt into legacy reads explicitly
(`allow_unversioned=True`, defaulting `False`), or — since v0 predates this
library's own `SNAPSHOT_VERSION = 2` — retire the bypass.

**Wrapper mitigation:** assert `blob["version"] == 2 and
blob["machine_hash"] == machine.structure_hash` before calling
`from_snapshot`. Unchanged from last round; our snapshots are
integrity-protected at rest anyway, which makes this defence-in-depth rather
than the only defence.

### D8-persistence-3 — `children_timeout` does not bound a plain-`def` child entry action (Medium, NEW)

**Severity: Medium.** `start()` is unbounded for a whole class of child, and
**silently** so — the warning #181 added does not fire, so a caller who
passed a bound has no signal that it was exceeded. It is the #179/#182
pattern once more: fixed on one service kind, structurally blind to the
other.

**Repro:** `battle-6db65d8/persistence/r5_children_timeout_def.py 20 100`
(minimal, sweeps the bound); `r4_round7_machinery.py` probe B at 50
children.

**File:line:** `src/xstate_statemachine/interpreter.py:2753-2757` —
`done, not_done = await asyncio.wait(pending, timeout=max(0.0, remaining))`.
`asyncio.wait` yields to the loop; a child whose entry action is a plain
`def` never yields, so the timeout callback is not scheduled until the work
is already done.

**Observed** (`out/r5_children_timeout_def.txt`), 20 children x 100 ms:

```
kind    bound     start() s  warn     verdict
def     0.05      2.02       0        UNBOUNDED
def     0.2       2.02       0        UNBOUNDED
def     1.0       2.02       0        UNBOUNDED
def     None      2.02       0        ok
async   0.05      0.05       1        ok
async   0.2       0.11       0        ok
async   1.0       0.11       0        ok
async   None      0.11       0        ok
```

The elapsed time is **independent of the bound** for `def` and tracks it for
`async def`, which rules out "the bound was simply generous".

**Suggested fix:** run a non-coroutine child bring-up on
`_get_service_executor()`, as #149 already does for plain services, so the
`asyncio.wait` bound is meaningful; or document that `children_timeout`
applies to coroutine entry actions only.

**Wrapper mitigation:** our child entry actions are `async def` by
convention; add a lint. Note this also makes `DEFAULT_CHILDREN_TIMEOUT = 2.0`
misleading as a safety net for anyone following the library's own `def`
examples.

### D8-persistence-4 — #179 service-kind parity does not hold for invoke ping-pong and rollback+onDone (Medium, NEW)

**Severity: Medium** (not High: the chain **is** bounded and the trip **is**
eventually observable via `on_event_dropped` — see 3.4). The defect is that
the caller's receipt resolves **ok** while 26 more laps run behind it, so
`await send(..., wait=True)` is not a synchronisation point on the
`async def` lane the way it is on the `def` lane and the sync engine.

**Repro:** `battle-6db65d8/persistence/r13_chain_parity_min.py` (minimal, one
character differs); `r12_livelock_fuzz.py 500 5` for the systematic view.

**Observed** — 500 fuzzed configs, perfectly consistent:

```
outcome by shape x kind (async engine):
    always_cycle       async  TRIP      50      always_cycle    def  TRIP    50
    invoke_pingpong    async  running   50      invoke_pingpong def  TRIP    50
    rollback_ondone    async  running   50      rollback_ondone def  TRIP    50
    sendto_selfloop    async  TRIP      50      sendto_selfloop def  TRIP    50
    raise_selfsend     async  running   50      raise_selfsend  def  running 50
HANGS (watchdog 30s) : 0   <- must be 0
SILENT trips         : 0   <- must be 0
lap-count mismatches : 50  (all invoke_pingpong: async=27 vs sync=28)
```

The two shapes that diverge are exactly the two the CHANGELOG names as
reopened (#167 rollback re-arming an invoke, #168 invoke ping-pong).
`always_cycle` and `sendto_selfloop` have full parity, so the budget itself
works; what does not carry is the `_chain_owed` hand-off to the caller's
receipt when the completion is a coroutine's.

**Also:** the sync engine runs **one more lap** than the async engine's
`def` lane (28 vs 27) on every ping-pong config — a standing off-by-one in
the same claim.

**Wrapper mitigation:** do not treat an ok receipt as "the chain finished";
observe `on_event_dropped` / `last_error` out of band. We already require a
drop-rate metric for CV-C07.

### D8-persistence-5 — `state_ids: []` beside a populated `configuration` is not a contradiction (Low, NEW)

**Severity: Low.** The mirror of the case #186 fixed. The checker
(`persistence.py:208-228`) asks "is every leaf in `state_ids` present in
`configuration`?", which is vacuously true when `state_ids` is empty, so
`configuration` decides alone and a one-key edit relocates the machine.

**Repro:** `r2_readside_matrix.py` part 2, rows `state_ids emptied` /
`state_ids forged m.b`; `r3_version_downgrade.py` final block.

**File:line:** `src/xstate_statemachine/persistence.py:216-228` —
`leaves = set(snapshot["state_ids"])` ... `missing = leaves - full`.

**Observed:**

```
=== #186 asymmetric half: state_ids=[] beside a forged configuration
  ACCEPTED -> leaves=['m.b'] (snapshot said m.a)
```

The symmetric case is correctly refused, so this is a gap in the predicate,
not a missing check: `full - leaves` is never examined, and an empty
`state_ids` on a `running` blob is not itself refused.

**Suggested fix:** require `status == "running"` to imply a non-empty
`state_ids`, and compare the *leaf sets* both ways rather than one.

**Wrapper mitigation:** same as last round — cross-check or strip
`configuration` before restore.

---

## 5. Not covered

Recorded rather than half-executed, so the gap is visible to the synthesis.

**Other tracks' remit** (attacked here only where the property holds through
the persistence surface; nothing here pre-empts a sibling track's verdict):

- **Concurrency:** external priority sends at **10 k/s** during self-generated
  chains was executed only at the soak's aggregate rate (92,394 external
  priority sends across 200 machines in 424 s, 0 charged drops) — not as a
  single-machine 10 k/s burst. `service_pool_size=1` with `stop()`
  mid-service, and done-callback double-fire, were not attacked.
- **Semantics:** the 5-way receipt matrix (guard-crash / denied / deferred /
  unhandled / error-kill) and the `strict` + wildcard matrix (#190) were
  **not** run — `r10` touches `strict` only through the forged-completion
  route. `start()` ordering vs #116 was covered only in its persistence
  aspect (`n10` D).
- **Observability:** the full hook matrix (exactly-once, ordering, both
  engines, every reason incl. `chain_budget` on the async lane and
  `queue_full` loop-side) was **not** run as a matrix; `r12`/`r13` observe
  `on_event_dropped` and `r4` observes the #181 warning, but exactly-once
  and ordering were not measured. The #181 warning's **absence** on the
  `def` lane is filed as `D8-persistence-3`.
- **`RAISE` loop-side refusals exactly-once** (#157) was not attacked.

**Inside this track, deliberately not re-run or not reached:**

- `r8_soak_async.py` at 12 min — wall-clock bound; run at 424 s. The
  reduction forfeits slow-leak / multi-minute-drift coverage only.
- `m3_soak_executor.py` (the `def`-service soak) was **not** re-run this
  round; `r8` supersedes it on the lane that was blind, and round 7's
  26,009-cycle `def` result stands unchallenged by anything observed here.
- `n9_soak.py`, `t2_property.py`, `t8_midstep_property.py` — superseded by
  `r8`, `q3` and `r6` respectively.
- **`RealClock` persistence.** Every run uses `SimulatedClock`. Timer
  lateness across a restore under a real clock is not a result this round.
- **Cross-version migration.** v0->v2 and v1->v2 upcast are exercised only
  through `n5`'s fuzz, `m2-C` and `r2`'s version column; a curated corpus of
  genuine older-version blobs does not exist.
- **Multi-process / concurrent snapshot of one interpreter.** All snapshots
  are taken from the owning thread or its plugin hooks. The #183
  cross-thread child branch (`_await_settled_for_snapshot` on a non-blocking
  sync actor) is therefore **not** exercised — `r4` probe A hits only the
  same-thread branch, which is the one that refuses instantly.
- **Snapshot during `stop()` teardown** was not attacked.

---

## 6. Verdict

**ADOPT WITH A WRAPPER.** The same words as last round, for materially
better reasons.

**What improved.** All three carried defects are genuinely fixed, and the
fixes are the ones that were suggested: `_processing` now wraps the async
initial descent (#182), the hash bypass is keyed on the declared version
(#185), and `configuration`/`state_ids` must agree (#186). The core property
an OMS depends on — *a snapshot taken at quiescence round-trips exactly* —
is now measured clean on **both service lanes** and with **invoked children
in the blob**, which rounds 6 and 7 never did: 2,400 restore-and-compare
cycles at every quiescent point (`n2`, both lanes); 5,046 hook-window
attempts across 320 machines with child actors, 0 torn (`r6`); 19,530
snapshot+restore cycles across 200 machines on the async service lane, 0
mismatch, flat object count (`r8`); full determinism including **engine
parity** and a clean `PYTHONHASHSEED` sweep (`r11`); and no livelock, no
hang, no silent trip across 500 fuzzed cycle configs (`r12`).

**What did not.** Five new findings, and the shape of three of them is the
one this project has now named in three consecutive rounds — *"fixed" means
"fixed on the artefact the issue was filed against"*:

1. **`D8-persistence-1` (High)** — #85 hardened `Event`; `DoneEvent` and
   `AfterEvent`, the classes that *assert engine authorship*, have no marker
   at all, and a forged one drives a real `onDone` past `strict`.
2. **`D8-persistence-2` (High)** — #185 moved the drift bypass from one
   attacker-controlled key to another attacker-controlled key.
3. **`D8-persistence-3` (Medium)** — #181's bound holds for `async def`
   child entry actions and is inert, silently, for `def` ones.
4. **`D8-persistence-4` (Medium)** — #179's *bound* carries to both service
   kinds; its *parity* claim does not, on exactly the two shapes
   (#167, #168) the CHANGELOG lists as reopened.
5. **`D8-persistence-5` (Low)** — #186's predicate is one-directional.

**Adoption position for this track.** None of the five can lose, duplicate
or strand a settled order, and none is on the steady-state snapshot write
path: two are on the *read* path, one on the *start* path, one on the
*receipt* path, one on the *event-construction* path. All five are cheaply
wrappable, and four of the five mitigations are lines the adapter already
needs for CV-P05 (`restart_services=True` re-runs services — re-confirmed
unchanged this round, in both service lanes) and CV-C07. **Persistence is
not a gating concern for adoption.** The gating question this round is not
persistence at all — it is `D8-persistence-1`, which belongs to whoever owns
the security verdict, and which surfaced only because the brief forced the
forged-completion probe through the persistence surface.
