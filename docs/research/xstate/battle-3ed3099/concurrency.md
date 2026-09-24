# Battle test (re-run) — CONCURRENCY, BACKPRESSURE & RESOURCE LIMITS

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`3ed3099`** ("Merge pull request #139 from basiltt/fix/0.8.1-round4").
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`; **`__version__` still reports
`0.8.0`**, so this build is identified **by commit, never by version string**.

**Date:** 2026-09-19. **OS:** Windows 11 Pro 10.0.26200.
**Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python` — CPython
**3.13.7** (GIL build), env `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified (`git status --porcelain` in the library clone is
empty after the whole run). No `git` command was run in the CandleViewer
repository. GitHub was read-only throughout.

**Predecessor:** `battle-5e07ba8/concurrency.md` + `concurrency.triage.md`
(six defects, `D-concurrency-1…6`).
**Scripts:** `battle-3ed3099/concurrency/*.py`; raw results in the `*.json`
beside them (`common.emit()`).

---

## 0. Bottom line

**Round 4 landed. Four of six prior defects are FIXED, one CHANGED to pass,
one is STILL-PRESENT unchanged. Four NEW defects, one of them a Blocker.**

The two prior Blockers are gone and gone properly. `OverflowPolicy.BLOCK` now
enqueues eagerly (`d1`: 10/10 delivered, 0 `RuntimeWarning`s; `n3`: 3,200
events across 16 producers, 0 unaccounted, hook and context counters agree
exactly). The mid-macrostep snapshot window is closed by refusal —
`get_persisted_snapshot()` raises `SnapshotMidStepError` inside an awaiting
action, and at every one of 600 quiescent points of a property run the snapshot
succeeded, was JSON-serialisable and round-tripped to an identical
configuration and context (`n1`). The `#105` per-task self-send gate is
correct in all three shapes that could have tripped it — `create_task`
producers, 24 OS threads via `send_threadsafe`, and independent actor tasks —
with 0 spurious `chain_budget` drops, while a genuine action-issued self-send
chain is still cut and still attributable (`n2`). Determinism is exact: 50
repetitions produced 1 distinct trace on each engine; `send_events([…])` and
successive `send()` agree (`n4`). Redaction and the exported API surface are
clean: 0 secret values in 46 log lines across every `DEFAULT_REDACT_KEYS`
spelling, `redact` is pure, the opt-out is explicit, and a user-built
engine-named `Event` is still not forgeable into a system event (`n7`).
`#116`, `#109` and `#108` all hold (`n8`). A 7-minute chaos soak — 11,728
cycles, 810,981 events, 11,728 quiescent snapshots and 3,536 restores — ended
with 0 empty-configuration observations, 0 snapshot failures, 0 task delta,
0 loop errors and +0.79 MB RSS (`n9`). Task hygiene, memory and loop
latency remain excellent. That is a large, genuine round of work.

The four new defects all sit on the **restore** and **supervision** edges that
this round's new features introduced:

- **D5-concurrency-1 (Blocker).** `persistence.check_shape()` enforces the
  `#102` legality rule ("`running` must name a state") against `state_ids` but
  the restore then rebuilds the configuration from the **`configuration`** key,
  which is not checked for a leaf. Delete the leaf entry from `configuration`
  and `from_snapshot` accepts the blob silently: the machine starts, reports
  `status="running"` and `is_running=True`, has `current_state_ids == set()`,
  and answers every event with `Receipt(changed=False, error=None)` forever.
  This is the exact machine-shape `#102` was written to make unreachable,
  arriving through the corrupt-snapshot door instead of the mid-step door.
- **D5-concurrency-2 (High).** `from_snapshot` leaks **raw**
  `TypeError` / `AttributeError` / `ValueError` for malformed snapshots —
  906 of 5,000 fuzz mutations, and 13 deterministic single-key cases
  (`actors`, `history`, `system`, `deferred`, `status` retyped). `#110`
  promises `SnapshotCorruptError` precisely so a caller can `except` one thing.
- **D5-concurrency-3 (High).** `#114`'s "an externally cancelled run loop
  flips `status` to `error` and fails pending receipts" does not fire when the
  cancel lands **before the run-loop task's first scheduling turn** — the
  window an `asyncio.timeout()`/TaskGroup abort around startup occupies.
  Deterministic: without an intervening `await asyncio.sleep(0)`, 3/3 runs
  left `status="running"`, `error=None`, and `send(…, wait=True)` hanging.
- **D5-concurrency-4 (Medium).** `#130` `escalate`-to-parent-`onError` only
  works when the `invoke` declares an explicit `id`. `id` is optional; the
  library's own regression test supplies one. Without it the escalation is
  silently lost. A plain callable service's failure reaches `onError` in both
  shapes, so this is specific to the escalate path.

Plus one prior defect unchanged: **D-concurrency-6** (`send_threadsafe` has no
backpressure signal on the calling thread) reproduces verbatim.

§2 has the prior-defect table, §3 the new-attack table, §4 the defect register,
§5 coverage and gaps, §6 the verdict.

---

## 1. Method and reductions

All commands were run from `battle-3ed3099/concurrency/` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1` and
`PY=".../_ref/xstate-statemachine/.venv-main/Scripts/python"`, each under
`timeout` per the ≤120 s-per-script bound.

### 1.1 Reductions (stated as required)

Every reduction is a **parameter** reduction; no invariant, accounting rule or
instrument was weakened.

| Script | Original (5e07ba8) | This run | Why |
|---|---|---|---|
| `a1_bounded_fanin.py` | 2,000 interp × 500 ev × 16 prod = 1,000,000 ev | 400 × 250 × 16 = **100,000 ev** per policy | 1 M ev/policy exceeds 120 s. Accounting identity is per-event, so it holds at any N. |
| `c1_stop_leaks.py` | 1,000 cycles × 7 variants | **300** cycles × 7 | Task-leak delta is a before/after measurement; 300 cycles still exercises every race phase. |
| `b1_threadsafe.py` | 32 × 2,500 (+ 4 × 20,000) | **32 × 800**, unpaced only | Dropped the paced and 4-thread variants; the unpaced max-rate case is the one that stresses ingest. |
| `f1_memory.py` | 1,000,000 ev × 100 machines | **60,000 ev × 20 machines** × 3 shapes | 200k×40 overran 300 s. Growth is reported per-event (`traced_bytes_per_event`), so it is comparable. |
| `g1_loop_blocking.py` | 3.0 s window × 7 scenarios | **2.0 s** window × 7 | p50/p95 tick lateness converges well inside 2 s. |
| `n1_persist_property.py` | (new) — brief asked 2,000 events | **600 events**, full round-trip every 10th | Each event costs snapshot+restore+start+stop; 2,000 exceeds the budget. All 600 quiescent snapshots were taken; 60 full round-trips. |
| `n9_soak_chaos.py` | (new) — brief asked 12 min | **420 s (7 min)** | Whole-track wall-clock bound. Chaos mix and all six invariants unreduced. |

### 1.2 Scripts adapted for superseded behaviour

Two prior scripts assumed pre-`#102`/pre-`#129` behaviour and were **adapted,
not deleted** — the original is kept alongside so the delta is auditable.

- **`d3_snapshot_in_window.py` → `d3b_midstep_snapshot.py`.** The original
  takes a snapshot inside an awaiting action and then asserts on the restored
  machine; on `3ed3099` it dies with `SnapshotMidStepError` before printing a
  verdict. **Does the new behaviour meet the intent? Yes, for the durability
  half.** The intent was "an `await` in an action must not durabilise an empty
  configuration". Refusal achieves that. `d3b` therefore asks three questions
  instead: Q1 the refusal fires (**yes**); Q2 the live readers are *still*
  observably empty in the window (**yes** — `current_state_ids == []`,
  `matches(x) == False` for every `x`, `status == "running"`; `probe_d_empty_window`
  independently measures 17/17 samples empty over a 0.2506 s window for a
  0.25 s await); Q3 a quiescent snapshot round-trips (**yes**). The residual
  live-reader window is recorded as a **documented constraint**, not a new
  defect — see §5.
- **`d2_block_stop_silent_drop.py` → `d2b_block_stop_attribution.py`.** The
  original asserts `len(on_event_dropped) == 5`. On `3ed3099` `#129` also
  attributes the events already sitting in the inbox when `stop()` runs, so
  the raw count is 8 and the original's arithmetic (`5 - 8 = -3`) prints
  "FAIL" while the behaviour is in fact correct. `d2b` attributes **per event
  identity**: each parked producer's own `Event` object must be processed or
  dropped-with-a-hook. Result: **0/5 unattributed — PASS.**

### 1.3 Commands

```bash
# prior-defect repros
$PY d1_block_fire_and_forget.py
$PY d2_block_stop_silent_drop.py ; $PY d2b_block_stop_attribution.py
$PY d3_snapshot_in_window.py     ; $PY d3b_midstep_snapshot.py
$PY d4_plugin_cancellederror.py
# prior sweeps (reduced per §1.1)
for p in raise block drop_newest; do $PY a1_bounded_fanin.py $p 400 250 16 64; done
$PY a2_block_edges.py
$PY b1_threadsafe.py 32 800 0 ; $PY b2_threadsafe_cost.py ; $PY b3_threadsafe_backpressure.py
$PY -W error -X dev c1_stop_leaks.py 300
$PY e1_plugin_hook_raises.py ; $PY e2_plugin_containment_edges.py
for c in KeyboardInterrupt SystemExit MemoryError CancelledError; do $PY e3_baseexception_case.py $c; done
$PY probe_d_cancel.py ; $PY probe_d_empty_window.py
$PY f1_memory.py 60000 20 20 --depth=4
for s in s0 s1 s2 s3 s4 s5 s6; do $PY g1_loop_blocking.py 2.0 $s; done
$PY h2_reader_race_gil.py
# new attacks
$PY n1_persist_property.py --events=600
$PY n2_per_task_gate.py
$PY n3_block_16_producers.py
$PY n4_determinism.py
$PY n5_fuzz_snapshot_events.py ; $PY n5b_snapshot_corrupt_minimal.py
$PY n6_observability_matrix.py ; $PY n6b_cancel_before_first_turn.py
$PY n7_security_surface.py
$PY n8_semantics.py ; $PY n8b_escalate_needs_invoke_id.py
$PY n9_soak_chaos.py --seconds=420
```

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

| ID | Prior severity | Verdict | Evidence on `3ed3099` |
|---|---|---|---|
| **D-concurrency-1** — `BLOCK` silently discards fire-and-forget `send()` | Blocker | **FIXED** | `d1`: sent 10, processed 10, `context['n']=10`, 0 `RuntimeWarning`s, exit 0. Confirmed at scale by `n3` v3 (500 un-awaited `send()` on an empty inbox → 500 processed) and `n3` v1 (16 producers × 200 = 3,200 attempted, 3,200 processed, 0 unaccounted). Matches `#104`. |
| **D-concurrency-3** — `await` in an action durabilises an empty configuration | Blocker | **FIXED (durability); residual live-reader window is a documented constraint** | `d3b` Q1: `get_persisted_snapshot()` in the window raises `SnapshotMidStepError` (`base_interpreter.py:1158`). Q3: the quiescent snapshot restores to `['order.working']`, `fills=1`, `receipt.error=None`. `n1`: 600/600 quiescent snapshots succeeded, 0 mid-step-at-quiescence, 0 round-trip mismatches. **Residual:** Q2 still shows `current_state_ids == []` and `matches()==False` while `status=="running"` during the await (`probe_d_empty_window`: 17/17 samples empty over 0.2506 s). See §5. |
| **D-concurrency-4** — plugin-raised `CancelledError` kills the loop while `status` says "running" | High | **FIXED** | `d4`: `status=running`, `is_running=True`, run loop alive, `send(BACK, wait=True)` returns a real receipt (`changed=True`), `context['n']` advances to 2. `n6` v3: contained via `on_plugin_error` + `last_plugin_error`, machine alive. Matches `#114`. |
| **D-concurrency-2** — `BLOCK` inbox drop on `stop()` has no `on_event_dropped` | High | **CHANGED → passes** | `d2b` (per-identity accounting): **0/5** parked events unattributed; every one fires `on_event_dropped(reason="stopped")`. The original script now prints FAIL only because `#129` *added* attribution for the pre-filled inbox too (8 hooks vs its hard-coded 5) — a harness arithmetic artefact, not a defect. Full reasoning in §1.2. |
| **D-concurrency-5** — `async def` plugin hooks never run; contained failures have no programmatic surface | Medium | **FIXED** | `n6` v2: an `async def` hook now fires `on_plugin_error` with a `TypeError` naming the hook and telling the author to use plain `def`; `last_plugin_error` carries `('AsyncHook','on_transition',TypeError(...))`. `n6` v1: a raising sync hook does the same. Matches `#127`. (`e2`'s v2/v3 still print the old "no surface" text — that script reads only the receipt/`last_error`, never the new `last_plugin_error` attribute; `n6` is the current instrument.) |
| **D-concurrency-6** — `send_threadsafe` has no usable backpressure signal | High | **STILL-PRESENT (unchanged)** | `b3` v2 (cap 100, RAISE): **6,400** calls returned without raising on the calling thread; **5,344** later failed on an unread `Future`; `on_event_dropped` fired **0** times. v1 unbounded: backlog grew monotonically 0→20,196 with no producer-side signal. v3 `DROP_NEWEST` remains fully hooked (5,922). Not addressed by round 4; carried forward verbatim. |

**Score: 4 FIXED, 1 CHANGED-to-pass, 1 STILL-PRESENT.** Both prior Blockers are
closed.

### 2.1 Prior "clean" results — re-confirmed

| Area | Result |
|---|---|
| Fan-in accounting (`a1`, 3 policies × 100,000 ev) | `unaccounted_accepted_but_lost: 0`, `attempt_balance_ok: true` on all three. `drop_newest` hooked 74,400/74,400 drops. 24.7k–32.0k ev/s. |
| Stop/teardown races (`c1`, 7 variants × 300 cycles, `-W error -X dev`) | `task_delta: 0`, 0 `RuntimeWarning`s, 0 "Task was destroyed", 0 loop exceptions — every variant. |
| Cross-thread ingest (`b1`, 32 threads × 800, unpaced) | 25,600 attempted / 25,600 processed, 0 order violations, 0 unaccounted; 32/32 strict typos rejected on the calling thread. |
| Cancellation of `send(wait=True)` awaiters (`probe_d_cancel`) | 0 invariant violations, 0 leaked receipts, machine still `running`. |
| Plugin containment (`e1`, `e3`) | All 10 hooks contained; peer plugins still called. `KeyboardInterrupt`/`SystemExit` still escape `asyncio.run` **by design**; `MemoryError`/`CancelledError` contained, loop alive. |
| Memory (`f1`, 60,000 ev × 20 machines × 3 shapes) | `traced_bytes_per_event` 0.14–0.15 B; `gc_objects_growth: 0`; `asyncio_task_growth: 0` on all three shapes. Flat. |
| Loop latency (`g1`, 2 s × 7 scenarios) | Idle s0 `late_ms_max 0.075`. Saturated s1 `late_ms_p50 3.21 / p95 9.55 / max 21.0`. Worst (s6) `max 40.1`. 0 slow-callback hits. |
| Reader race under GIL (`h2`) | 1,078,507 reads from 8 threads during 1,994 transitions, 0 reader exceptions. |

---

## 3. New attacks

| # | Script | Target (issue) | Result |
|---|---|---|---|
| N1 | `n1_persist_property.py` | Snapshot at **every** quiescent point of a property run; `SnapshotMidStepError` must never fire at quiescence (#102, #107, #110, #117, #118, #128, #131) | **PASS** — 600/600 snapshots ok, 0 mid-step-at-quiescence, 0 serialization errors, 0 round-trip mismatches, 0 restored-event errors, 26 `has_dormant_timers` observations with `restart_timers=True` |
| N2 | `n2_per_task_gate.py` | `#105` per-task self-send gate under `create_task`, OS threads, actor tasks | **PASS** — A: 24 task producers, `n=24`, 0 `chain_budget` drops. B: 24 threads via `send_threadsafe`, `n=24`, 0 drops. C: 72 actor-shaped sends, `n=72`, 0 drops. **Control D**: a real action-issued self-send chain still trips at 9 runs (`maxIterations=8`) with `RunawayChainError` on `last_error` and 1 attributable drop |
| N3 | `n3_block_16_producers.py` | `#104` BLOCK under 16 producers, incl. a concurrent `stop(drain=True)` | **PASS** — v1 3,200/3,200; v2 (drain mid-flight) 3,200/3,200; v3 500 un-awaited sends on an empty inbox → 500. Hook and context counters agree in all three |
| N4 | `n4_determinism.py` | 50× byte-identical traces on both engines, incl. inline sync-service semantics (#116) | **PASS** — 1 distinct trace hash in 50 async runs, 1 in 50 sync runs; `send_events([…])` ≡ successive `send()`; states/context identical across engines (the `Receipt` surface differs by design, so cross-engine byte-equality is reported, not asserted) |
| N5 | `n5_fuzz_snapshot_events.py` | 5,000 snapshot mutations → `SnapshotCorruptError`; hostile event types → `InvalidEventError` (#110, #113, #131) | **FAIL** — A: 906/5,000 raw unnamed exceptions (`TypeError`/`AttributeError`/`ValueError`) → **D5-concurrency-2**; 29/5,000 silent empty-configuration restores → **D5-concurrency-1**. B: 12/14 hostile types correctly `InvalidEventError` (and `isinstance(TypeError)`); `""` accepted (see §5) |
| N5b | `n5b_snapshot_corrupt_minimal.py` | Minimal deterministic repros of the two N5 findings | **FAIL (by design — it is a repro)** — 13 single-key retype cases raise raw exceptions; `del snapshot["configuration"][1]` restores a `running`, empty, permanently-inert machine |
| N6 | `n6_observability_matrix.py` | Hook matrix for every new error class + `on_plugin_error`/`on_resolve_error` (#114, #127, #133, #134) | **7 of 8 PASS** — v1 sync-hook raise, v2 `async def` hook, v3 hook-raised `CancelledError`, v4 `on_resolve_error`, v5 `sendTo` unresolved target (`on_event_dropped("unresolved_target")` + `ActorSpawningError` on the receipt), v6 `on_guard_error`, v7 `on_action_error` all fire with a matching programmatic attribute and a surviving interpreter. **v8 external run-loop cancel FAILS** → **D5-concurrency-3** |
| N6b | `n6b_cancel_before_first_turn.py` | Minimal repro + control for the v8 failure | **FAIL (repro)** — 3/3 cancels before the first turn leave `status="running"`, `error=None`, `send(wait=True)` hung; 3/3 cancels after one `sleep(0)` correctly give `status="error"` and a resolved `InterpreterStoppedError` receipt |
| N7 | `n7_security_surface.py` | `LoggingInspector` redaction list (#126) + exported provenance API (#137) | **PASS** — 0 secret values in 46 log lines across all 13 `DEFAULT_REDACT_KEYS` in upper/lower/prefixed/`x-` spellings and nested in dicts and lists; non-secret values still logged; the `redact_keys=()` opt-out does leak (i.e. it is a real, explicit opt-in); `redact` is pure. All 9 required names in `__all__` and importable; `Event(...)` rejects a `system=` kwarg; an engine-named user `Event` is **not** a system event; `system_event()` mints provenance |
| N8 | `n8_semantics.py` | `#116` completion ordering, `#109` output, `#108` root target, `#130` escalate | **3 of 4 PASS** — #116: async and sync both `{ok: 10, cancel: 0}` (the engines now agree). #109: `done.invoke` data is `{'result': 'declared-output'}`, no private-context leak. #108: root target rejected at build with `InvalidConfigError` naming the reason. **#130 FAILS** → **D5-concurrency-4** |
| N8b | `n8b_escalate_needs_invoke_id.py` | Minimal repro + control for the #130 failure | **FAIL (repro)** — matrix: `callable,id=True` ✓, `callable,id=False` ✓, `escalate,id=True` ✓, **`escalate,id=False` ✗** |
| N9 | `n9_soak_chaos.py` | 7-min reduced chaos soak, 6 continuous invariants | **PASS** — see §3.1 |

### 3.1 Soak (N9)

420 s of continuous chaos: per cycle a fresh interpreter (random inbox cap of
16/64/unbounded) driven with a 20–120-event burst mixing `wait=True` and
fire-and-forget sends, a 2%-probability raising plugin hook, periodic hostile
event types, `after` timers, random `stop(drain=…)`, and a 30% chance of a
snapshot→restore→start→stop round trip. Invariants: S1 no accepted-and-lost
event, S2 never `running` with an empty configuration at quiescence (checked on
both the live and the restored machine), S3 quiescent snapshot never raises,
S4 bounded `asyncio.all_tasks()` delta, S5 bounded RSS, S6 no unhandled loop
exception and no "Task was destroyed but it is pending".

A 20 s smoke run of the identical script was clean on every invariant
(611 snapshots, 175 restores, `S2=0`, `S3=0`, `S4 task_delta=0`, `S6=0`,
RSS 30.3→31.1 MB). **The full 420 s run is clean on all six:**

```
seconds 420.2   cycles 11,728   events_sent 810,981   processed_hook 803,842
S2 running-with-empty-configuration      : 0   (live AND restored)
S3 quiescent snapshot failures           : 0   (11,728 snapshots, 3,536 restores)
hostile event-type escapes               : 0
S4 asyncio task delta                    : 0
S5 RSS                                   : 30.22 MB -> 31.01 MB  (+0.79 MB over 7 min)
S6 loop errors / "Task destroyed pending": 0 / 0
RESULT: PASS
```

(`events_sent 810,981` vs `processed_hook 803,842`: the 7,139-event difference
is the tail still in flight when each cycle's `stop()` ran, plus the
deliberately-hostile types correctly refused at the call site. **S1 is
therefore reported, not asserted, in this script** — the strict
accepted-vs-lost identity is asserted instead by `n3` and `a1`, which control
the stop point. S2–S6 are asserted.)

---

## 4. Defect register — `D5-concurrency-n`

### D5-concurrency-1 — a snapshot whose `configuration` has no leaf restores silently into a `running`, empty, permanently-inert machine

**Severity: Blocker.**
**Repro:** `n5b_snapshot_corrupt_minimal.py` (deterministic); found by
`n5_fuzz_snapshot_events.py` (29/5,000 mutations, all on the `delete` branch).

```
configuration: ['fz', 'fz.b']   state_ids: ['fz.b']
mutation      : del snapshot['configuration'][1]      # drop the leaf, keep the root
restore       : RESTORED (no exception)
  pre-start   : state_ids=[]  status=running
  post-start  : state_ids=[]  status=running  is_running=True
  send(GO, wait=True) -> Receipt(changed=False, error=None)
  context     : {'n': 1}   (frozen forever)
```

**Root cause.** `persistence.check_shape()`
(`src/xstate_statemachine/persistence.py:186-189`) enforces the `#102` legality
rule as:

```python
if status == "running" and not (
    snapshot.get("configuration") or snapshot["state_ids"]
):
    fail("status is 'running' but the configuration is empty")
```

— a *non-emptiness* test, satisfied by `["fz"]` (the machine root alone). The
restore then rebuilds from `configuration` in preference to `state_ids`
(`base_interpreter.py:1442`: `restore_ids = snapshot.get("configuration") or
snapshot["state_ids"]`), so `state_ids` — which still correctly names
`fz.b` — is never consulted, and the resulting `_active_state_nodes` contains
only the root. The engine already owns the correct predicate,
`_active_leaf_present()` (`base_interpreter.py:1112-1119`), and applies it on
the **write** side (`get_persisted_snapshot`, `base_interpreter.py:1158`). It
is never applied on the **read** side.

**Why Blocker.** This is the same machine shape the round's headline fix
(`#102`) exists to make unreachable — `running`, no configuration, every event
answered with a receipt indistinguishable from a legitimate no-op — reached
through a different door. Any storage-layer corruption, partial write, schema
migration or hand-edited blob that perturbs one list element produces a
permanently frozen order machine that every health probe (`status`,
`is_running`, receipt shape) reports as healthy. On an order path this is a
resting order that no cancel or replace can ever reach again, with zero
operator-visible signal. `docs/research/xstate/20-adoption-gate.md`'s
money-loss/silent-corruption bar is met exactly.

**File:line.** `src/xstate_statemachine/persistence.py:186-189` (check too
weak) and `src/xstate_statemachine/base_interpreter.py:1442` (restores from
the unchecked key). Correct predicate already present at
`base_interpreter.py:1112-1119`.

---

### D5-concurrency-2 — `from_snapshot` leaks raw `TypeError`/`AttributeError`/`ValueError` for malformed snapshots

**Severity: High.**
**Repro:** `n5b_snapshot_corrupt_minimal.py` (13 deterministic single-key
cases); `n5_fuzz_snapshot_events.py` (906/5,000 mutations).

Fuzz breakdown by mutation branch:

```
version:TypeError 167   version:ValueError 153   unicode:AttributeError 118
wrap:AttributeError 109 obj:TypeError 107        wrap:TypeError 77
retype:AttributeError 70 unicode:ValueError 35   obj:AttributeError 29
retype:TypeError 29     retype:ValueError 12          total 906 / 5,000
```

Deterministic minimal cases (retype one top-level key of a good snapshot):

| key | value | outcome |
|---|---|---|
| `actors` | `7` / `"junk"` | `AttributeError: 'int'/'str' object has no attribute 'items'` |
| `history` | `7` / `"junk"` | `AttributeError: … has no attribute 'items'` |
| `system` | `7` | `AttributeError: … has no attribute 'items'` |
| `deferred` | `null` | `TypeError: 'NoneType' object is not iterable` |
| `status` | `[]` / `{}` | `TypeError: unhashable type: 'list'/'dict'` |

**Root cause.** `persistence.check_shape()` (`persistence.py:149-196`) validates
exactly five keys — `status`, `context`, `state_ids`, `configuration`,
`pending_events`/`deferred` — and its own docstring says it runs "before any
field is read, so a corrupted blob cannot surface as a bare `KeyError`". But
`actors`, `history`, `system`, `output`, `error` and `machine_hash` are read
downstream with no shape check (`base_interpreter.py:1440-1500` region), and
`deferred=None` slips past the `val is not None` guard at `persistence.py:191`
into `for d in snapshot.get("deferred", [])` — `.get` returns the explicit
`None`, not the default. `status` is checked with `status not in
_VALID_STATUSES`, which is itself a raw `TypeError` for an unhashable value
before the check can fail cleanly.

**Why High and not Blocker.** The failure is loud — the caller does get an
exception, and the interpreter is never constructed. The harm is that `#110`'s
contract ("`except SnapshotCorruptError`") does not hold, so a recovery path
written to the documented API crashes on an unexpected type instead of taking
its fallback branch. Real, but it does not silently corrupt state the way
D5-concurrency-1 does.

**File:line.** `src/xstate_statemachine/persistence.py:149-196` (incomplete
shape check; `deferred=None` hole at :190-196); downstream unchecked reads in
`src/xstate_statemachine/base_interpreter.py:1440-1500`.

---

### D5-concurrency-3 — `#114` does not publish a cancel that lands before the run-loop task's first turn

**Severity: High.**
**Repro:** `n6b_cancel_before_first_turn.py` (deterministic, with control);
surfaced by `n6_observability_matrix.py` v8.

```
cancel before first turn  (3/3):  status=running  is_running=False  error=None
                                  send(GO, wait=True) -> HUNG (no receipt, no exception)
cancel after sleep(0)     (3/3):  status=error    is_running=False
                                  error=RuntimeError("… run loop was cancelled while running …")
                                  send(GO, wait=True) -> InterpreterStoppedError receipt
```

**Root cause.** `#114`'s publication happens in the
`except asyncio.CancelledError:` handler *inside* `_run_event_loop`
(`interpreter.py:1446-1462`), which calls `_die()` (`interpreter.py:1605-1620`)
to set `status="error"`, record the cause, fail every pending receipt and fire
`on_error`. `start()` creates that task with
`asyncio.create_task(self._run_event_loop())` (`interpreter.py:444`) and
returns without awaiting a scheduling turn for it. If the owner cancels in
that window, Python cancels a task whose coroutine has **never begun**, so the
handler body never executes and `_die()` never runs. The machine is left in
exactly the pre-`#114` state the fix was written to eliminate. One
`await asyncio.sleep(0)` between `start()` and `cancel()` flips the outcome
deterministically — which is what makes the mechanism certain.

**Why High.** The trigger is narrow in time but is precisely the shape a
supervisor produces: `async with asyncio.timeout(5): interp = await
Interpreter(m).start(); await first_work()` — a timeout firing during startup,
a `TaskGroup` aborting on a sibling's exception, or a graceful-shutdown handler
cancelling during boot. The consequence is the worst kind: `status` lies and
every `wait=True` awaiter hangs with no timeout of its own. It stays below
Blocker because `is_running` still tells the truth (`False`), giving a careful
health check a working signal — the same reasoning the prior register applied
to `D-concurrency-4`.

**File:line.** `src/xstate_statemachine/interpreter.py:444` (task created,
never given a turn) vs `interpreter.py:1446-1462` (where `#114`'s publication
lives) and `interpreter.py:1605-1620` (`_die`).

---

### D5-concurrency-4 — `#130` `escalate` reaches the parent's `onError` only when the `invoke` declares an explicit `id`

**Severity: Medium.**
**Repro:** `n8b_escalate_needs_invoke_id.py` (deterministic, with control).

```
matrix_reached_onError:
  callable,id=True   : true     <- control
  callable,id=False  : true     <- control
  escalate,id=True   : true
  escalate,id=False  : FALSE    <- parent sits in 'p.w' forever
```

**Root cause (mechanism confirmed, exact line not pinned).** `id` is optional
on an `invoke`; when omitted the engine synthesises one from the invoking
state — visible in the service-failure log line, which reads `Service 'kid'
(ID: 'kid')` when declared and `Service 'kid' (ID: 'p.w')` when not. The
callable-service failure path resolves `onError` correctly under both ids, so
the routing machinery handles the synthesised id in general; the `escalate`
built-in's parent lookup does not. The library's own regression test for
`#130` (`tests/test_round4_findings.py:1134-1157`,
`TestEscalateRoutesToOnError`) declares `"id": "kid"`, so the id-less shape is
not covered.

**Why Medium.** Silent loss of a child's failure signal — the parent waits in
the invoking state forever with no hook, no receipt error and no log line —
which is a genuine liveness hazard. But the trigger requires the author to
omit an optional field *and* use `escalate` rather than an exception, and a
one-character config change (`"id": "..."`) is a complete, discoverable
workaround. No state is corrupted and no event accounting is violated.

**File:line.** `escalate`'s parent-resolution path in
`src/xstate_statemachine/interpreter.py` (the `#130` handler); contrast with
the callable-service failure path at `interpreter.py:2025` region, which
resolves correctly under a synthesised id. Library test that misses the case:
`tests/test_round4_findings.py:1134-1157`.

---

### Carried forward: D-concurrency-6 (High, unchanged)

`send_threadsafe` still evaluates the overflow policy **after** the calling
thread has returned, so under `RAISE` the failure lands only on a `Future` the
documented `interp.send_threadsafe("X")` idiom never reads, and
`on_event_dropped` does not fire for it. `b3` v2, cap 100: 6,400 calls
returned without raising; 5,344 failed on an unread `Future`; 0 hooks. v1
unbounded: backlog grew monotonically to 20,196 with no producer signal.
Severity and root cause unchanged from `battle-5e07ba8/concurrency.triage.md`.

---

## 5. Coverage — and what was NOT covered

### Documented constraints (observed, deliberately not counted as defects)

- **The live-reader window inside an awaiting action persists.** `#102` closed
  the *durability* half of `D-concurrency-3` by refusing the snapshot. It did
  not make the transition atomic to concurrent readers: for the full duration
  of any `await` inside a transition action, `current_state_ids == set()`,
  `matches(x) == False` for every `x`, and `status == "running"`
  (`probe_d_empty_window`: 17/17 samples empty across a 0.2506 s window for a
  0.25 s await; `d3b` Q2). Anything that polls the interpreter from another
  task — a health endpoint, a metrics scrape, a UI binding — can observe
  "no state". This is now **bounded and non-durable**, which is a real
  improvement, and the engine offers `on_transition` as the correct
  observation point. Recorded as a constraint an adopter must design around,
  not as a new defect, because the defect the prior register raised (durable
  corruption) is genuinely closed.
- **`send("")` is accepted.** `n5` part B: an empty-string event type is not
  an `InvalidEventError`. `#113`'s contract is about non-`str` types, and `""`
  is a `str`, so this is arguably within spec — but it means a stringified
  empty field reaches the machine as a legitimate (unhandled) event rather
  than being refused at the call site. Reported, not counted.
- **`KeyboardInterrupt` / `SystemExit` from a plugin hook still escape
  `asyncio.run`** (`e3`). Unchanged from the prior round and correct: these are
  `BaseException`s that must not be swallowed.
- **A synchronous plugin hook is charged to the run-loop task** (`e2` v5:
  a 50 ms hook produced a 50.79 ms loop stall). By design; documented here so
  an adopter sizes hook work accordingly.

### Not covered this run

- **Free-threading build (track item h1).** The `.venv-ft` interpreter from the
  prior round was not rebuilt for this commit; `h1_free_threading.py` was not
  run. `h2_reader_race_gil.py` (the GIL-build counterpart) was run and is
  clean. Any claim about `Py_GIL_DISABLED` behaviour on `3ed3099` is
  **unverified**.
- **Full-scale sweeps.** Per §1.1 the fan-in ran at 100k rather than 1M events
  per policy, stop-races at 300 rather than 1,000 cycles, and memory at 60k ×
  20 rather than 1M × 100. Rare-event tails that need 10× the volume — a
  1-in-500k accounting slip, a slow leak below 0.15 B/event — are **outside
  this run's resolution**.
- **The soak is 7 minutes, not 12.** Degradation modes with an onset past
  7 minutes are not covered. Its S1 (accepted-vs-lost) total is reported
  rather than asserted, per §3.1; `n3` and `a1` carry that assertion.
- **`SimulatedClock` + `restart_timers` determinism.** `n1` exercises
  `restart_timers=True` and `has_dormant_timers` (26 dormant observations) but
  does **not** drive a `SimulatedClock` through a full deterministic replay of
  a restored machine's `after` deadlines. `from_snapshot(clock=)` (#117) was
  not independently exercised.
- **`D5-concurrency-4`'s exact source line** was not pinned. The behavioural
  matrix and the differing log-line ids establish the mechanism; the specific
  statement in the `escalate` handler that requires a declared id was not
  isolated.
- **Cross-engine byte-identical traces** are reported, not asserted: the sync
  engine's `Receipt` surface differs by design, so `n4` asserts within-engine
  determinism (1 distinct hash in 50, both engines) and cross-engine equality
  of states and context only.
- **Child-actor `#105` was simulated, not spawned.** `n2` scenario C uses N
  independent `asyncio` tasks — the same task-identity shape a spawned actor's
  `sendTo` presents to the gate — rather than N genuinely spawned child
  machines. The gate's per-task predicate (`_issued_from_own_action`,
  `interpreter.py:1622-1625`, a `ContextVar` check) is task-scoped, so the
  shapes are equivalent for this property, but a real spawn was not driven.
- **Prior defect `D-concurrency-6` was re-measured, not re-triaged.** No new
  source diff was taken against `send_threadsafe`.

---

## 6. Verdict

**Round 4 is a real, substantial fix round on this track, and it is not done.**

Both prior Blockers are closed at the root, not papered over: `BLOCK` enqueues
eagerly and holds under 16 concurrent producers with exact accounting, and the
mid-macrostep snapshot window is closed by an explicit, well-named refusal that
never once fired at quiescence across 600 property-run snapshots and 611 more
under chaos. The `#105` per-task gate, the `#116`/`#109`/`#108` semantics, the
`#126` redaction and the `#137` export surface all hold under direct attack.
Determinism is exact. Task hygiene, memory and loop latency remain excellent.
Four of six prior defects are fixed and a fifth passes once its harness is
corrected for the round's own improvement.

**But the adoption gate does not open.** `D5-concurrency-1` is a Blocker of the
same class and severity as the `#102` defect this round was built to fix: a
one-element perturbation of a persisted `configuration` restores, without any
exception, into a machine that reports `running` and `is_running=True`, holds
no state, and answers every order event with a receipt byte-identical to a
legitimate no-op. The engine already computes the correct predicate
(`_active_leaf_present`) and already applies it when writing a snapshot; it
simply does not apply it when reading one. Until the read path enforces the
same legality rule the write path does, a persistence-backed order machine can
be silently and permanently frozen by any storage-layer imperfection — which is
the exact failure mode an OMS cannot tolerate and cannot detect.

`D5-concurrency-2` (raw exceptions instead of `SnapshotCorruptError`, 906/5,000)
compounds it: the recovery path an adopter would write against the documented
`#110` contract is the path that crashes. `D5-concurrency-3` reopens `#114` in
the startup window a supervisor actually occupies, with a hanging awaiter as
the symptom. `D5-concurrency-4` is a narrower liveness hazard with a trivial
workaround. And `D-concurrency-6` — cross-thread backpressure with no signal on
the calling thread — is untouched from the previous round and remains relevant
to any design that feeds order events from worker threads.

**Recommendation: NOT READY.** Re-gate after (a) the restore path enforces
`_active_leaf_present()`, (b) `check_shape()` covers `actors` / `history` /
`system` / `output` / `error` and the `deferred: null` hole so `#110`'s
contract is total, and (c) `#114` publishes a cancel that lands before the run
loop's first turn. Those three are mechanically small and all three have their
correct implementation already present elsewhere in the same file. Given the
trajectory of this round — every one of the four fixed defects was fixed
properly and at the root, not masked — that re-gate is a realistic near-term
prospect rather than a rewrite.
