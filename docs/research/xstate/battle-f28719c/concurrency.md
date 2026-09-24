# Battle test (round 9) — CONCURRENCY, BACKPRESSURE & RESOURCE LIMITS

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`f28719c`** (merge of #202, "0.8.1 round-8 fixes": #192–#201 plus
reopened #181/#186). `__version__` still reads `0.8.0`; the `[Unreleased]`
CHANGELOG block targets 0.8.1. **Keyed on the commit.**

**Date:** 2026-09-22. **OS:** Windows 11 Pro 10.0.26200.
**Interpreter:** `.venv-main/Scripts/python` — CPython **3.13.7** (GIL
build), env `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Predecessor:** `battle-6db65d8/concurrency.md` (`D8-concurrency-1…5`).
Round-8 register: `48-r8-findings-register.md`.
**Scripts:** `battle-f28719c/concurrency/*.py`; raw results in the sibling
`*.json`. The round-8 corpus (78 files) was copied forward **unmodified**
and re-run; the new attacks are the `s*` files and are **standalone**
(stdlib + `xstate_statemachine` only, no `common2` import).

---

## 0. Bottom line

**Round 8 was the strongest round yet.** Four of the five prior defects are
**FIXED**, and the two that mattered — the blocker and the High — are fixed
at the root, not papered over.

- **D8-concurrency-1 (Blocker) is FIXED.** `send(priority=True)` from an
  action now trips at **lap 27** with `RunawayChainError` and one
  `on_event_dropped(chain_budget)` — byte-for-byte the behaviour of the
  non-priority control. `r8b` flipped FAIL → **PASS**, 0 livelocks.
- **D8-concurrency-2 (High) is FIXED for the *cancellation* half and now
  a documented contract for the *blocking* half.** #193 moved the executor
  handoff into the engine-held task; the remaining "a `def` service's
  entering step awaits it" is now the **stated** plain-`def` contract on
  both engines (Production Characteristics § 2), not a silent trap. `r2c`
  still reports the block, and that is the documented shape.
- **D8-concurrency-3 (High) is FIXED for the bound and the WARNING.** The
  bound is now **per child**: 50 coroutine children with 1 s entry actions
  settle in **0.31 s** against a 0.3 s bound (was 50.0 s aggregate in the
  worst case), and the WARNING **always** fires on overrun — including the
  non-yielding `def` case it used to suppress (`s2`, `r6b`).
- **D8-concurrency-4 (Medium) is FIXED.** `get_persisted_snapshot()` from
  `on_interpreter_start` is now **refused**, 3/3 cells, both engines
  (`r3b` FAIL → **PASS**). The property run agrees: **0 torn blobs** in
  `r3 --n=300` where round 8 had 600/600 torn.
- **D8-concurrency-5 (Low) is STILL-PRESENT**, unchanged in mechanism.

Against that, **two new findings**, one of them the round's headline.

| ID | Sev | One line |
|----|-----|----------|
| **D9-concurrency-1** | **High** | #195's trust boundary is a plain dict key. `restore_event({..., "engine": true})` mints a **trusted** `_EngineDone` from a hand-authored record; sent through the public `send()` it drives a real `onDone` **past `strict`** while the genuine service is still in flight, and the genuine result is then discarded. Async lane; the `def` lane is protected only by the incidental blocking of D8-2. |
| **D9-concurrency-2** | **Low** | `D8-concurrency-5` unchanged: call-site `QueueOverflowError` refusals fire no `on_event_dropped`. 78 105 of 78 274 refusals (**99.8 %**) invisible. |

Two round-8 results moved **without** being defects and are recorded as
such: `r10` now reports 4 distinct traces and a false engine-parity gap,
which `s7` proves is a **probe-window artefact** (the machine reaches rest
at 0.313 s but `r10` samples at 0.5 s *during* the chain on this build; at
a 1.5 s settle it is **1 distinct trace per cell, async 31 / sync 31,
exact parity**). And `r4`'s accepted-mutation set shrank from 6 cases to 2
— #198 closed `config_dropped` and `state_ids_emptied`, leaving only the
narrow `state_ids_rewritten` case of contract note 5.

**Verdict: READY on this track, conditional on D9-concurrency-1.** See §7.

---

## 1. Method and reductions

Every script in `battle-6db65d8/concurrency/` was copied into
`battle-f28719c/concurrency/` **unmodified** and re-run; results are
compared blob-to-blob against the round-8 JSON. Every new probe is an
`s*` file, is **standalone** (no `common2`), and runs **both** `def` and
`async def` service spellings. Library source was never modified.

### 1.1 Reductions (stated as required)

| Item | Brief | Run | Why |
|------|-------|-----|-----|
| Soak (`r12`) | 12 min | **150 s**, 200 machines | 120 s per-script bound raised to a 200 s `timeout` for this one probe; 20 min whole-task bound. Shape mix, async services, priority producer and chaos-snapshot invariants unreduced. **PASS**, 20 600 external events, 0 dropped, 4 800 snapshots 0 torn, CPU 0.94 s/wall s, 0 leftover tasks. |
| Livelock fuzz (`r8`) | ≥500 configs | **510** (3 shards × 170, seeds 7001/7002/7003) | Each shard fits the script bound; the union is the ≥500 asked for. Both kinds × both engines, unreduced. **0 timeouts, 0 unobservable trips** in all three. |
| Fuzz watchdog | 30 s | **3 s** + 0.05 s settle | Unchanged rationale from round 8: every livelock in this family hangs indefinitely, so 3 s discriminates identically. |
| Property (`r3`) | ≥300 machines | **300** | Unreduced. Parallel + nested + invoked children, both engines, both kinds. 1 356 blobs returned, **0 torn**; 2 923 refusals. |
| External priority rate (`s4`, `r5`) | 10 000/s | **target 10 000/s, achieved ~450 (`def`) / ~1 000 (`async def`)** | Host-limited by `send_threadsafe` cost from one producer thread, unchanged from round 8. The invariant (0 shed as `chain_budget`) is rate-independent and held in **all 4** `s4` cells. |
| `children_timeout` scale (`s2`) | 50 def + 50 async | **unreduced** — 50/0, 0/50 and the 50+50 mix | 1.0 s entry, 0.3 s bound. |
| Determinism (`r10`) | 50 runs | **50** (`r10`) + **12 @ 1.5 s settle** (`s7`) | `s7` is smaller *because* it settles; the 0.5 s window is what `r10` gets wrong, not the run count. |
| `s6` / `s1` forgery | — | 4 and 8 cells | Deterministic, no reduction. |

### 1.2 Scripts whose exit code is not a verdict (recorded)

- **`d3_snapshot_in_window.py` exits 1** — unchanged from rounds 7 and 8
  and still the **fix** (#169/#142) landing, not a failure.
- **`a1_bounded_fanin.py` and `b1_threadsafe.py` exit 124** (the 100 s
  `timeout`). Both are *rate* probes with no internal bound; round 8 ran
  them at a 115 s budget. They are throughput measurements, not
  invariants, and are not counted either way.
- **`n5_fuzz_snapshot_events.py` exits 1** on the same single known
  sub-case (`send("")` accepted with `error=None`). Pre-existing,
  registered off this track.
- **`q1`/`q1b`/`q1c` exit 1 by construction** — they assert the
  per-external-event budget re-buy, contract note 1.
- **`q6`/`q6b` exit 1** — recorded contract notes 3 and 4.
- **`r1`, `r2`, `r2c`, `r6b`, `r8c` exit 1** — all of them because they
  assert *against* the plain-`def` blocking contract, which #193 made
  explicit rather than removing. See §2.2.
- **`r4` exits 1** on the one remaining `state_ids_rewritten` case,
  contract note 5 (narrowed, not eliminated).

### 1.3 Commands

```bash
PY="_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
cd docs/research/xstate/battle-f28719c/concurrency

# round-8 corpus, copied forward unmodified
for f in a1_bounded_fanin a2_block_edges b1_threadsafe b3_threadsafe_backpressure \
         c1_stop_leaks d1_block_fire_and_forget d2_block_stop_silent_drop \
         d2b_block_stop_attribution d3_snapshot_in_window d3b_midstep_snapshot \
         d4_plugin_cancellederror e1_plugin_hook_raises e2_plugin_containment_edges \
         g1_loop_blocking h1_free_threading h2_reader_race_gil \
         probe_d_cancel probe_d_empty_window; do timeout 100 $PY $f.py; done
for f in r1_d7_1_both_service_kinds r5_external_priority_under_chain \
         r2_chain_owed_never_completing r8c_lap_parity_def_lane \
         r8b_priority_self_send_livelock r2c_def_service_blocks_loop \
         r6b_children_timeout_def_noop r3b_on_start_torn_minimal \
         r7_engine_marker_forgery r4_snapshot_readside_guards \
         r11_semantics_strict_wildcard; do timeout 115 $PY $f.py; done
$PY r3_hook_snapshot_property_both_kinds.py --n=300
for i in 1 2 3; do $PY r8_livelock_fuzz_both_kinds.py \
    --n=170 --wd=3 --settle=0.05 --seed=$((7000+i)) --tag=_s$i; done
$PY r9_observability_matrix.py --only=core ; $PY r9_observability_matrix.py --only=qf
$PY r10_determinism_and_hashseed.py --runs=50
timeout 200 $PY r12_soak_async_services.py --seconds=150 --n=200

# new attacks (standalone, both service kinds throughout)
$PY s1_engine_marker_persistence.py        # #195 persist/restore provenance
$PY s2_children_timeout_mixed.py           # #194 per-child bound, 50 def + 50 async
$PY s3_eventless_selection_matrix.py       # #196 SCXML 3.13 depth matrix
$PY s4_priority_provenance_roundtrip.py    # #192 provenance across a snapshot round-trip
$PY s5_snapshot_engine_forgery.py          # "engine": true in a snapshot + v1/v2 shapes
$PY s6_restore_event_forgery_minimal.py    # -> D9-concurrency-1 (minimal)
$PY s7_determinism_settled.py --runs=12 --settle=1.5   # r10's window artefact
```

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

| Prior ID | Sev (r8) | Probe re-run | Verdict @ `f28719c` |
|----------|----------|--------------|---------------------|
| **D8-concurrency-1** — action-issued `send(priority=True)` never charged; silent livelock | **Blocker** | `r8b`, `s4` | **FIXED** (#192) |
| **D8-concurrency-2** — a plain `def` service blocks the run loop | High | `r2c`, `r1`, `r5`, `r2` | **CHANGED → documented contract** (#193): the cancellation half is fixed, the blocking half is now stated |
| **D8-concurrency-3** — `children_timeout` a no-op on `def`; bound aggregate; WARNING suppressed | High | `s2`, `r6b`, `r6` | **FIXED for the bound and the WARNING** (#194); non-pre-emptibility of `def` remains, now documented |
| **D8-concurrency-4** — torn blob from `on_interpreter_start` | Medium | `r3b`, `r3 --n=300` | **FIXED** (#199) |
| **D8-concurrency-5** — call-site `QueueOverflowError` fires no hook | Low | `r9 --only=qf` | **STILL-PRESENT** → re-filed as D9-concurrency-2 |

**Score: 3 FIXED, 1 CHANGED (to a documented contract), 1 STILL-PRESENT.**

### 2.1 D8-concurrency-1 — the blocker is gone, root and branch

`r8b_priority_self_send_livelock.py` is the round-8 repro, unmodified. Its
JSON went from two `LIVELOCK` rows to none:

```
self_send  kind        outcome  laps  trip_observable  last_error          drops            stop
plain      def         bounded    27       True        RunawayChainError   chain_budget:1   ok  <- control
plain      async def   bounded    27       True        RunawayChainError   chain_budget:1   ok  <- control
prio       def         bounded    27       True        RunawayChainError   chain_budget:1   ok  <- WAS LIVELOCK
prio       async def   bounded    27       True        RunawayChainError   chain_budget:1   ok  <- WAS LIVELOCK
```

The defect row is now **identical to its own control in every field** —
same lap count, same error, same single shed event, same `stop_seconds:
0.0`. That is the strongest available form of the fix: the priority lane
and the plain lane are no longer distinguishable by the budget.

`s4_priority_provenance_roundtrip.py` confirms the *other* direction at
the same time, which is the pairing #192 had to get right:

```
case                               kind        laps  tripped  chain_budget_drops
action_issued_priority_charged     def          27    True     {"B": 1}
action_issued_priority_charged     async def    27    True     {"B": 1}

case                restored  version  ext_sent  ext_applied  shed_as_chain_budget
external_priority   false      -         3132       3132              0
external_priority   true       2         1617       1617              0
external_priority   false      -         2240       2240              0   (async def)
external_priority   true       2         2795       2795              0   (async def)
```

**Every external priority event sent was applied** — 9 784 of 9 784 across
the four cells — while a self-generated chain tripped beside them in the
same machine. And the invariant survives a **snapshot round-trip**: the
restored instances (`version: 2`) shed **0** external events as
`chain_budget` too. Provenance is not something the lane forgets at
`from_snapshot()`.

### 2.2 D8-concurrency-2 — reclassified, deliberately

#193 split round 8's single finding in two and fixed the half that was a
defect:

- **Fixed:** a `def` service armed by a transition that is then rolled
  back (`actionErrorPolicy: "rollback"`) or rolled forward (an `always`
  out of the state) is now **cancelled before the callable is submitted**,
  because the executor handoff moved into the task the engine holds. A
  result arriving for an exited state is ignored (SCXML §6.4.2).
- **Documented, not fixed:** the entering step still *awaits* the plain
  service, so an event cannot pre-empt it. The CHANGELOG states this is
  "the documented plain-`def` contract on **both** engines" and
  Production Characteristics § 2 now says so.

`r2c_def_service_blocks_loop.py` therefore still reports `result: FAIL`,
and the numbers are unchanged (probe latency 1.051 s / 1.011 s at pool
size 1 and 4; the `async def` control answers in 0.012 s). So do `r1`
(`def` machines backlog 4 447 / 3 759, `async def` drain to **0**) and
`r5` (`def`: 16 of 1 786 applied; `async def`: 3 858 of 3 858).

**This track does not re-file it as a defect.** The behaviour is now
written down, the dangerous *silent* part (a rolled-back invoke still
running) is gone, and the mitigation — mandate `async def` — is the same
one round 8 recommended and `r12` validates at 200 machines. It becomes an
**adoption-gate rule**, not a library defect. That is a judgement call and
it is recorded as one: an operator who reads only the type hints still
gets a blocking machine, and nothing at build time stops them.

### 2.3 D8-concurrency-3 — the bound is real now

`s2_children_timeout_mixed.py`, 1.0 s child entry actions, `children_timeout=0.3`:

```
n_def  n_async  start_s   warning  entered_at_start  first_send_s  scaling
   0      50      0.31      True          0             0.000        0.31x
  50       0     51.22      True         50             0.001       51.22x
  50      50     50.68      True         50             0.000       50.68x
```

Row 1 is the fix: **50 coroutine children settle in 0.31 s against a 0.3 s
bound** — the per-child semantics #194 promises. Round 8's aggregate bound
would have given 50 × 1 s here. `first_send_seconds` is 0.000 in all three
rows, i.e. the "bounded `start()` turns into an unbounded first send"
regression the CHANGELOG warns about did not happen.

Rows 2 and 3 are the non-pre-emptible `def` case, and the important change
is the last column of `r6b`: **`warning_logged` is now `true`** where round
8 measured `false`. The WARNING names cause and remedy verbatim (*"A
plain-`def` entry action that blocks cannot be pre-empted on the event loop
thread — make it `async def`, or offload the blocking call (#181 / #194)"*),
and reports the true elapsed time (51.212 s) rather than the bound. A 250×-over
`start()` that logged nothing was the defect; a 51 s `start()` that logs
exactly what happened is the documented single-thread limit. **FIXED.**

### 2.4 D8-concurrency-4 — write side and read side agree again

`r3b_on_start_torn_minimal.py` flipped FAIL → **PASS**: all three cells now
read `disposition: "refused"` where round 8 read `"returned"` with
`status: "running"`, `state_ids: []`. The property run is the stronger
evidence — `r3 --n=300`, 300 random nested/parallel/child machines × 2
engines × 2 kinds:

```
round 8: on_interpreter_start  returned 600   torn 600
round 9: on_interpreter_start  (absent — every call refused)
         on_transition         returned 600   torn   0
         on_event_received     returned 156   torn   0
         refusals                            2 923
```

**0 torn blobs of 1 356 returned**, on both engines and both service kinds.
#199 raises the in-flight flag before the hook, so the hook is now inside
#182's window.

### 2.5 Prior clean results — re-confirmed

`a2`, `b3`, `c1`, `d1`, `d2`, `d2b`, `d3b`, `d4`, `probe_d_*`, `e1`, `e2`,
`g1`, `h1`, `h2` all exit 0, dispositions unchanged. `r7_engine_marker_forgery`
is unchanged **except** that `private_budget_counter_writable_from_outside`
moved from `true` to `"refused:AttributeError"` — contract note 3 partially
closed. `r9 --only=core` is **PASS 6/6**. `r11` is **PASS**, unchanged.
`r12` soak **PASS** at 150 s (§3).

### 2.6 Round-8 fixes independently re-verified

| Fix | Probe | Result |
|-----|-------|--------|
| **#192** priority lane sheds by provenance | `r8b`, `s4`, `r5` | **HOLDS both ways** — action-issued priority trips at lap 27 with one shed event; 9 784/9 784 external priority events applied, **0** shed as `chain_budget`, including after a snapshot round-trip |
| **#193** `def` executor handoff inside the engine-held task | `r2c`, `r1`, `r8c` | **Cancellation half holds**; the blocking half is the stated contract (§2.2) |
| **#194** `children_timeout` per child + WARNING always | `s2`, `r6b`, `r6` | **HOLDS** — 50 coroutine children in 0.31 s vs a 0.3 s bound; WARNING fires on **every** overrun incl. the `def` case |
| **#195** private engine subclasses + `"engine": true` | `s1`, `s5`, `s6`, `r7` | **PARTIAL** — provenance round-trips correctly and a hand-built `DoneEvent` is refused under `strict`; but the flag is forgeable → **D9-concurrency-1** |
| **#196** `always` only in the eventless settle pass | `s3` (18 cells), `r8` fuzz | **HOLDS** — `named_ran == 1` in **all 18** cells of the depth matrix (always at same / deeper / shallower depth × guard on/off × both kinds × both engines), `last_error` clean, **0 engine-parity gaps** |
| **#196b** sync engine reaps invoked children on exit/stop | `c1`, `r12` | **HOLDS** — 0 leftover tasks after stop in the 150 s / 200-machine soak |
| **#198** v≥1 running snapshots need both configuration fields | `s5`, `r4` | **HOLDS** — `state_ids` emptied, `configuration` emptied and a v1 `state_ids`-only running blob are **all** `SnapshotCorruptError`, both kinds. `r4`'s accepted-mutation set shrank 6 → 2 |
| **#199** `on_interpreter_start` inside the in-flight window | `r3b`, `r3` | **HOLDS** — §2.4 |
| **#200** task-keyed `_chain_owed` | `r2`, `r12` | **HOLDS on the coroutine lane** — owed 0 on every path, 0 leftover tasks over 150 s × 200 machines |
| **#201** lap parity stated exactly | `r8c`, `s7` | **HOLDS** — `def` and `async def` identical in all 20 `r8c` cells; the async/sync delta is **0 at `maxIterations: 50`** (`invoke_cycle` 51/51) and −2 only at 25. `s7`: async 31 / sync 31, exact |
| **#185** hash drift | `r4` | **HOLDS**, unchanged — all 6 hash mutations `SnapshotDriftError` |
| **#189 / #190** receipt kill, wildcard vs strict | `r9 core`, `r11` | **HOLDS**, unchanged — 5/5 distinct async signatures, 12/12 strict cells |

---

## 3. New attacks (`s*`) — what each one found

| # | Attack | Result |
|---|--------|--------|
| **s1** | #195 provenance across `persist_event` / `restore_event` + `copy`/`deepcopy`/`pickle`/`dataclasses.replace`, 8 machine cells (2 kinds × strict on/off) | **Mixed.** Round-trip is correct: a genuine `_EngineDone` persists with `"engine": true` and restores as `_EngineDone`; a hand-built `DoneEvent` persists **without** the flag and restores as `DoneEvent` (user traffic). `replace` → `TypeError`; `copy`/`deepcopy`/`pickle` of a genuine event preserve the mark, as intended. **But** a hand-authored record with the flag restores as `_EngineDone` and is accepted by `send()` under `strict`. → **D9-concurrency-1** |
| **s2** | #194 `children_timeout` at scale: 50 async, 50 def, and a **50 + 50 mix**, 1 s entry, 0.3 s bound | **Per-child bound confirmed** (§2.3). 50 coroutine children in 0.31 s; WARNING on every overrun; `first_send` 0.000 s in all three rows. |
| **s3** | #196 / SCXML §3.13 selection matrix: `always` at **same / deeper / shallower** depth than the named handler × guard true/false × 2 kinds × 2 engines (18 cells) | **PASS 18/18.** `named_ran == 1` everywhere, `eventless_ran` matches the guard, `last_error` clean, and **0 engine-parity gaps**. The deeper-`always`-outranks-shallower-handler bug #196 describes does not reproduce at any depth. |
| **s4** | #192 provenance under a snapshot **round-trip**: action-issued priority must be charged; external priority must never be shed — both kinds, live and restored | **PASS 6/6** (§2.1). 9 784/9 784 external priority events applied, 0 shed; both charged cells trip at lap 27. |
| **s5** | `"engine": true` forged into a **snapshot** `pending_events` record, + v1 `state_ids`-only and v2 emptied-field restores, both kinds | **PASS 10/10** — and this is the interesting negative. The forged record restores but the machine is in `idle`, not `work`, so there is no live invoke for it to complete and `onDone` never runs (0/0 cells). `D`/`E` (emptied `state_ids` / `configuration`) are `SnapshotCorruptError`, i.e. **#198 holds**; so is the v1 running blob. The snapshot *file* is not the exploitable route — the in-process one is. |
| **s6** | **Minimal** D9-concurrency-1: `restore_event({... "engine": true})` → `send()` while the genuine service is in flight, 4 cells | **FAIL on `async def`.** The forged completion is `is_system_event: true`, `send()` returns `ACCEPTED`, the machine moves `s6.work → s6.done`, `onDone` runs with `{"v": "FORGED"}` and the genuine `{"v": "GENUINE"}` result is discarded. The unflagged control is `refused:UnknownEventError` in the same cell. |
| **s7** | `r10`'s determinism window, parameterised by settle time | **PASS at 1.5 s settle** — 1 distinct trace per cell over 12 runs, async 31 / sync 31 laps, exact parity. Time-to-rest measured at **0.313 s**, i.e. `r10`'s 0.5 s sample lands inside the chain on this build. `r10`'s FAIL is a probe artefact (§5 note 6). |

### 3.1 The soak

`r12_soak_async_services.py --seconds=150 --n=200`: 200 machines, `async def`
services, rollback+onDone / always→invoke / parallel shapes, an external
priority producer, and chaos snapshots at quiescence.

```
external_sent                20 600      drops_by_reason              {}
external_dropped_as_chain_budget  0      machines_not_answering_in_5s  0
final_backlog                     0      snapshots taken            4 800
snapshots torn                    0      snapshots refused              0
cpu_seconds_per_wall_second    0.94      leftover_tasks_after_stop      0
callsite_errors                  {}      stop                          ok
```

**PASS**, and better than round 8 on every comparable axis (20 600 vs
12 350 external events over a 1.9× window, 4 800 vs 3 080 snapshots, CPU
0.94 vs 1.01 per wall second). Zero leftover tasks confirms #196b's child
reaping and #200's task-keyed ledger together over 150 s.

### 3.2 The livelock fuzz

510 configs (3 shards × 170, seeds 7001–7003) × 2 service kinds × 2
engines, 5 shapes, 3 s watchdog: **0 timeouts, 0 unobservable trips** in
all three shards. Every trip carried `RunawayChainError` in `last_error`
or an `on_event_dropped(chain_budget)`. The `priority_self_send` shape
that round 8 had to *exclude* from the fuzz — because it starved the loop
so completely that the in-process watchdog could not fire — is now carried
by `r8b` as a **bounded** case (§2.1), so the exclusion no longer costs
anything.

---

## 4. Defect register — `D9-concurrency-n`

### D9-concurrency-1 — `restore_event` mints a **trusted** engine completion from any dict carrying `"engine": true`; the forged event drives a real `onDone` past `strict` and discards the genuine result

**Severity: High.** A privilege escalation across #195's own trust
boundary, exploitable entirely through public API, silent in every
observability surface, and it **corrupts application state** — the
transition fires with attacker-chosen `event.data` and the real service
result is dropped on the floor.

**Repro:** `s6_restore_event_forgery_minimal.py` (deterministic, the
`async def` cells fail every run; `result: FAIL`). Broader cells in
`s1_engine_marker_persistence.py`.

```
kind        record_engine_flag  restored_class  is_system  send       state_before  state_after  onDone_in_flight  payload_applied  ctx_seen
async def        true           _EngineDone       True     ACCEPTED   [s6.work]     [s6.done]          1            {"v":"FORGED"}   {"v":"FORGED"}   <- DEFECT
async def        false          DoneEvent         False    refused:   [s6.work]     [s6.work]          0             null            {"v":"GENUINE"}  <- control
                                                           UnknownEventError
def              true           _EngineDone       True     ACCEPTED   [s6.work]     [s6.work]          0             null            {"v":"GENUINE"}  <- masked by D8-2
def              false          DoneEvent         False    refused:   [s6.work]     [s6.work]          0             null            {"v":"GENUINE"}
```

The two `async def` rows differ by **one boolean in a dict literal**. The
machine is `strict: True`. The unflagged record is correctly refused with
`UnknownEventError` — that is #195 working. Add `"engine": true` and the
same record becomes a trusted engine completion: `is_system_event()` says
`True`, `strict` steps aside, the `onDone` transition to `s6.done` fires
with `data = {"v": "FORGED"}`, and when the genuine service finishes 0.6 s
later its `{"v": "GENUINE"}` result is discarded because the state has
already been left (SCXML §6.4.2, correctly). Final context reads
`{"v": "FORGED"}`.

**Mechanism.** `events.py:414`:

```python
trusted = record.get("engine") is True
return _restore(record, etype, kind, trusted=trusted)
```

and `_restore` (`:429/:438/:448`) then calls `engine_done` /
`engine_error` / `engine_after`, each of which stamps `_ENGINE_MARK`
(`:296`) onto a private subclass. `is_system_event` (`:283`) trusts that
subclass by `isinstance`. There is **no check that the record came from a
genuine snapshot round-trip** — `restore_event` is a pure dict→event
function, and `xstate_statemachine.events` is a public module (no leading
underscore) whose `restore_event`/`persist_event` pair is the documented
persistence surface.

The CHANGELOG anticipates exactly this and argues it away:

> "The flag is not a secret; what it closes is the accidental laundering
> of 'I have a dict shaped like a completion' into 'the engine said this
> happened'. A caller who can write arbitrary snapshot records already
> controls `state_ids` and `context` outright (#185), so this is the
> correct trust boundary."

**That argument covers the snapshot route and `s5` confirms it** — a
forged record inside a persisted blob is harmless there, because the
restored machine is not in the invoking state. It does **not** cover the
in-process route, which is what `s6` exercises: `restore_event` is called
directly, no snapshot is involved, no `state_ids` or `context` control is
required, and the target is a *live* machine in a *live* invoking state.
The premise "a caller who can do this already controls the snapshot" is
false for that path. And the round-8 fix's own stated goal — *"a
hand-built `DoneEvent(...)` bypassed `strict` and drove a real `onDone`
while the genuine service was still running"* — is reproduced verbatim by
`s6`, with four extra characters in the dict.

**File:line.** `src/xstate_statemachine/events.py:414` (`trusted =
record.get("engine") is True`), `:429`/`:438`/`:448` (the minting calls),
`:283` (`is_system_event` trusting the minted subclass by `isinstance`),
`:296` (`_ENGINE_MARK` stamp). The asymmetry is that #195 closed
`isinstance(DoneEvent)` as a trust test and replaced it with
`isinstance(_EngineDone)` — but left a public function that mints
`_EngineDone` on request.

**Why the `def` lane passes.** Not because it is protected: because the
plain-`def` service blocks the run loop (§2.2), so the forged event is not
processed until the genuine service has already completed the transition.
The `def` row is a **false negative of D8-concurrency-2**, not a second
mitigation. A `def` service fast enough to have returned, or any machine
whose invoking state persists, is exposed identically.

**Operational impact.** In an OMS this is "any code path that can call a
public serialisation helper can declare a fill." A plugin, an audit
replayer, a test fixture, or a deserialiser fed operator-supplied JSON can
mint `done.invoke.fill` with arbitrary `data` against a live order machine
in `strict` mode, move it to `filled`, and cause the genuine broker
response to be discarded as late. Nothing is logged, `last_error` stays
`None`, and no `on_event_dropped` fires — the forged event is *valid*
traffic by the engine's own test.

**Suggested shape of a fix** (not prescriptive): `restore_event` should
mint trusted classes only when called from the snapshot restore path —
e.g. an internal `_restore_event(record, *, trust_engine_flag)` used by
`base_interpreter.from_snapshot`, with the public `restore_event`
defaulting to `trust_engine_flag=False`. That preserves the genuine
round-trip #195 needs (`s1` `genuine_engine` still passes) and closes the
hand-authored route.

---

### D9-concurrency-2 — call-site `QueueOverflowError` refusals still fire no `on_event_dropped`; the hook now under-counts the shed rate by 99.8 %

**Severity: Low.** Observability only; the call site raises, so no caller
loses an event silently. Unchanged in mechanism from `D8-concurrency-5`
and `D7-concurrency-3` before it.

**Repro:** `r9_observability_matrix.py --only=qf` (6 threads, 1 s, depth-4
inbox, `OverflowPolicy.RAISE`).

```
                       round 7     round 8     round 9
callsite_refusals        6 021      85 256      78 105    <- raised, NO hook
loopside_refusals        6 066         255         169    <- error on the future, hooked
queue_full_hooks         6 066         255         169    <- exactly-once on the loop side
hook coverage            50.2 %        0.3 %       0.2 %
```

`loopside_hooked_exactly_once: true` — #157's half is exact, 169 refusals
→ 169 hooks. The optimistic `qsize()` check in `send_threadsafe` raises
before anything is queued and never reaches the hook.

**File:line.** `src/xstate_statemachine/interpreter.py:1136-1137` (the
loop-side hook that exists) vs the call-site `qsize()` guard in
`send_threadsafe` (no hook).

**Operational impact.** An operator aggregating `on_event_dropped(queue_full)`
as *the* backpressure metric under-reports by ~460×. `queue_depth` remains
the only reliable signal. Carried forward; does not gate.

---

## 5. Contract notes — observed, deliberately NOT counted as defects

1. **`maxIterations` is a per-external-event budget, not a lifetime one.**
   `q1c` unchanged, `engines_agree: true`. The catalogue must read
   `maxIterations: N` as "per event". **Adoption-gate item, carried forward.**

2. **Sync `send()` returns `None`,** so the 5-way receipt matrix is 5/5
   distinct on the async engine and 2/5 on the sync one (`r11`). A
   cross-engine abstraction must not read `Receipt` fields on the sync
   engine. Unchanged.

3. **`__slots__` on `Interpreter` still does not seal the instance**
   (`r7`: `has___dict__: true`), but the specific round-8 observation that
   the private budget counter is writable from outside is now
   **`refused:AttributeError`**. Partially closed; the layout is still not
   a security boundary and the library does not claim it is.

4. **`_raise_depth` is not reset at quiescence after an `internal=True`
   threadsafe burst.** `q6b` payload unchanged; `r7` F3 shows
   `internal=True` is accepted from outside and bumps the counter.
   Cosmetic, unchanged.

5. **#186/#198 is enforced in one direction, but the gap is now narrow.**
   `r4`'s accepted-but-should-refuse set shrank from **6 cases to 2**:
   `config_dropped` and `state_ids_emptied` are now refused (#198), and
   the disagreement fuzz accepted 8/400 instead of 17/400, all of them
   ancestor-supersets or true agreements. What remains is
   `state_ids_rewritten` — a `state_ids` list that is itself legal while
   `configuration` says otherwise: `configuration` silently wins
   (`base_interpreter.py:1722`, `snapshot.get("configuration") or
   snapshot["state_ids"]`; the two are still never *compared*). The
   machine always lands where `configuration` says, so no accepted case
   restored a wrong configuration. A *reader* of `state_ids` can still
   disagree with the restored machine, with no error. **Worth an issue;
   does not gate.**

6. **`r10` reports non-determinism and an engine-parity gap; it is a
   probe-window artefact.** `r10` samples 0.5 s after `start()` and now
   reads 4 distinct traces per async cell and `async_laps: 14` vs
   `sync_laps: 31`. `s7_determinism_settled.py` measures time-to-rest at
   **0.313 s** and, at a 1.5 s settle, gets **1 distinct trace in all four
   cells** with `async_laps: 31 == sync_laps: 31`. The machine is
   deterministic; the 0.5 s window straddles the chain on this build.
   Recorded so the `r10` FAIL is not misread. `distinct_outcomes_across_seeds:
   1` over `PYTHONHASHSEED ∈ {0,1,7,12345,99991}` in both probes.

7. **The engine marker is still reachable as
   `xstate_statemachine.events._ENGINE_MARK`** (`r7` F5). Unchanged from
   round 8 and still not counted on its own — but see D9-concurrency-1,
   which needs no private attribute at all.

8. **`send("")` is accepted with `error=None`** — `n5` unchanged, registered
   off this track.

9. **`a1_bounded_fanin` and `b1_threadsafe` hit the 100 s `timeout`** on
   this run's tighter per-script budget. Both are open-ended rate probes;
   §1.2.

---

## 6. Coverage — what was NOT covered this run

- **Free-threaded (no-GIL) build.** `h1_free_threading.py` re-ran on the
  GIL build only; no 3.13t/3.14t interpreter is installed on this host.
  Every finding here is GIL-build evidence. D9-concurrency-1 is a pure
  trust-boundary logic defect and is build-independent; D9-concurrency-2
  is a race whose *ratio* would change.
- **The full 12-minute soak.** Run at 150 s × 200 machines (PASS). A
  12-minute window could surface slow leaks this one cannot. The soak uses
  `async def` services by design; a `def`-service soak was again not run,
  because §2.2 makes the outcome a foregone conclusion. Deliberate.
- **D9-concurrency-1 on the sync engine.** `SyncInterpreter` was not
  probed with a forged completion against a live invoke. The defect is in
  `events.py`, shared by both engines, so the mechanism is engine-agnostic
  — but the *reachability* on the sync engine (which drains differently)
  is inference, not measurement.
- **D9-concurrency-1 via `engine_error` / `engine_after`.** Only the
  `done` kind was driven end-to-end. `restore_event` mints all three the
  same way (`events.py:438/448`), so a forged `error.platform.*` (to
  trigger an `onError` rollback) or a forged `after` (to fire a timer
  early) should behave identically; not measured.
- **`restart_services=True` / `restart_timers=True` restore paths.** `s4`
  and `s5` exercise the default static restore only. A forged record
  interacting with a re-driven dormant invoke is untested — and is the
  case where the snapshot route (`s5`, harmless today) could become live.
  **Recommended next round.**
- **`SimulatedClock` / `after`-timer interaction with the plain-`def`
  blocking contract.** A blocking service must also delay due timers;
  still not measured against that root cause. Carried forward from round 8.
- **Multi-process / multi-loop interpreters.** Single process, single loop
  throughout (plus worker threads and the service executor).
- **`a1` / `b1` throughput numbers.** Timed out at 100 s (§1.2); no
  round-over-round throughput comparison for those two.

---

## 7. Verdict

**Round 8's fixes are the real thing.** The blocker that defined round 8 —
`send(priority=True)` from an action spinning for ever with no trip, no
hook, no `last_error` and no `stop()` — is not merely bounded now, it is
**indistinguishable from its own non-priority control** in every field
`r8b` measures. #192 got both directions at once, which was the hard part:
the same run that charges 27 self-generated laps applies **9 784 of 9 784**
external priority events with zero shed, and keeps doing so after a
snapshot round-trip. #194 turned a decorative bound into a real per-child
one (50 coroutine children in 0.31 s against a 0.3 s allowance) and made
the overrun WARNING unconditional, so even the case a single thread cannot
pre-empt now *says* so. #199 closed the last torn-snapshot hook: 0 of 1 356
blobs torn across 300 random machines, both engines, both service kinds,
where round 8 had 600 of 600. #196 survives an 18-cell depth matrix with
zero parity gaps. The 150 s / 200-machine soak is clean on every axis and
cheaper than round 8's.

**One new defect, and it is in the fix that was hardest to get right.**
#195 correctly identified that `isinstance(DoneEvent)` was not a trust
test and replaced it with a private minted subclass — then left
`restore_event()`, a public function in a public module, minting that
subclass for anyone who puts `"engine": true` in a dict. `s6` reproduces
round 8's own words (*"a hand-built `DoneEvent` bypassed `strict` and drove
a real `onDone` while the genuine service was still running"*) with four
extra characters, against a `strict` machine, discarding the genuine
service result in the process. The CHANGELOG's defence — that anyone who
can write a snapshot record already controls `state_ids` — is sound for
the snapshot route (`s5` confirms it is harmless) and simply does not
apply to the in-process one.

**Recommendation for this track: READY, conditional on D9-concurrency-1.**

1. **Fix D9-concurrency-1** before adoption. The suggested shape is a
   private `_restore_event(..., trust_engine_flag=True)` used only by
   `from_snapshot`, with the public `restore_event` defaulting to `False`.
   `s1`'s `genuine_engine` round-trip cell is the regression test that the
   fix must keep passing; `s6` is the one it must flip.
2. **Mandate `async def` for every service in the catalogue**, and gate it
   mechanically. §2.2 is now a *documented* contract rather than a silent
   trap, which is why it is not re-filed — but documentation is not a gate,
   and the failure (a machine that answers nothing for the service's
   duration, `status: "running"`, `last_error: None`) is invisible in
   production. `r12` shows the all-`async def` configuration is sound at
   200 machines.
3. **Gate `children_timeout` the same way.** The bound is now genuinely
   per child *for coroutine entry actions*; a plain-`def` entry action
   still costs N × D and now logs a WARNING saying so. Catalogue children
   must use `async def` entry actions, and the WARNING should be alerted on.
4. **Add `queue_depth` to the health surface.** Carried forward from rounds
   7 and 8 and still the only reliable backpressure signal —
   `on_event_dropped(queue_full)` sees 0.2 % of refusals (D9-concurrency-2).
5. **Treat `maxIterations` as per-external-event** in every catalogue
   machine's budget calculation (contract note 1), unchanged.
6. **File contract note 5** (`state_ids` vs `configuration` never compared)
   as a follow-up issue. It narrowed considerably under #198 and does not
   gate.

`D9-concurrency-2` (Low) is an observability gap that should be filed but
need not gate. Note also for whoever schedules the next round: `r10` needs
its settle window widened to ~1.5 s (contract note 6) or it will keep
reporting a determinism failure that `s7` shows is not there.

**With D9-concurrency-1 fixed and the two `async def` rules enforced at
build time, this track's evidence supports READY.** That is a materially
stronger position than round 8, where three of five findings were open
liveness failures on a lane the type hints accept without ceremony.
