# Battle test (round 5) — CONCURRENCY, BACKPRESSURE & RESOURCE LIMITS

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`cec108b`** ("Merge pull request #164 from basiltt/fix/0.8.1-round5").
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`; **`__version__` still reports
`0.8.0`**, so this build is identified **by commit, never by version string**.

**Date:** 2026-09-19. **OS:** Windows 11 Pro 10.0.26200.
**Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python` — CPython
**3.13.7** (GIL build), env `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was not written to.

**Predecessor:** `battle-3ed3099/concurrency.md` (`D5-concurrency-1…4` plus the
carried-forward `D-concurrency-6`).
**Scripts:** `battle-cec108b/concurrency/*.py`; raw results in the `*.json`
beside them (`common.emit()`).

---

## 0. Bottom line

**Every prior defect on this track is FIXED. One NEW defect, Medium: a
cross-engine ordering/parity hole in `start()` for plain-`def` invoked
services introduced by the #149 executor hop.**

The round-5 work on this track is verified at the root, not by symptom:

- **`D5-concurrency-1` (Blocker) is closed.** The read side now enforces
  exactly-one-leaf-per-region. `p3`'s 300-case Hypothesis property over random
  **parallel** machines took 879 quiescent snapshots with 0 failures, 0
  instability, 0 round-trip mismatches, 0 byte-identity mismatches and 0
  region violations; every torn variant (`configuration` missing one region's
  leaf, `configuration`-only tear, v1 shape with torn `state_ids`,
  `status="error"` with no recorded error) is refused with
  `SnapshotCorruptError`.
- **`D5-concurrency-2` (High) is closed.** `p5` part B: 5,000 snapshot
  mutations produced **0** raw `TypeError`/`ValueError`/`AttributeError`;
  every failure is a named `XStateMachineError`
  (`SnapshotCorruptError` 2,726, `SnapshotDriftError` 355,
  `SnapshotVersionError` 154) and **0** mutations restored a `running`
  machine with no leaf.
- **`D5-concurrency-3` (High) is closed.** `n6b` now reports
  `publishes_114: true` for a cancel landing **before** the first scheduling
  turn; `p2` v3 shows `_die` is idempotent under 1/2/3 cancels — exactly one
  `on_error`, `status="error"`, `send(wait=True)` resolves rather than hangs.
- **`D5-concurrency-4` (Medium) is closed.** `n8b`'s matrix is 4/4: `escalate`
  reaches the parent's `onError` **without** a declared `invoke.id`.
- **`D-concurrency-6` (High, carried since `5e07ba8`) is closed.** `p2` v2:
  under `OverflowPolicy.RAISE` with 16 threads on a cap-32 inbox, **4,136 of
  4,800** calls raised `QueueOverflowError` **on the calling thread**; the
  full 4,800 are accounted (raised + future-failed + processed). Previously
  0 raised at the call site.

New capability holds under direct attack: 200 concurrent plain-`def` services
complete off the loop thread on 200 distinct executor threads (`p1` v1), a
caller-supplied executor is not shut down while an owned one is released
(`p1` v3), `stop()` during a running service returns in 1 ms with no leak
(`p1` v2), and 200 lifecycles leave a thread delta of −1. 500 mixed
start/stop cycles with cross-thread sends leave task and thread deltas of 0
(`p2` v4). The livelock fuzzer (#144/#151) settled **48/48** nested-invoke and
parallel-`always` cycle machines on the sync engine inside a 30 s watchdog —
0 livelocks, 0 raw exceptions. Determinism is exact (1 distinct trace hash in
50 per engine) and independent of `PYTHONHASHSEED` across 5 seeds. Semantics
and observability are 6/6 (`p4`): `guardErrorPolicy="raise"` takes the
unguarded fallback, `Receipt.denied` separates `guard_denied` from `ignored`,
`RootTargetError` is non-downgradable under `strictTargets=False`,
`actionErrorPolicy="fail"` gives `status="stopped"` with a cleared
configuration on **both** engines and fails the parent's invoke, and the
hook matrix fires exactly once for `unresolved_target`, `chain_budget` and
`on_invalid_event`. A 5-minute chaos soak: 9,021 cycles, 622,891 events,
9,021 quiescent snapshots, 2,720 restores, **0** on every invariant, RSS
+0.7 MB.

The one new defect is **D6-concurrency-1 (Medium)**: `Interpreter.start()`
does not await the #149 executor hop, so a plain-`def` service invoked by the
**initial** configuration has *not* completed when `await start()` returns,
while `SyncInterpreter.start()` has already completed it. An event sent
immediately after `start()` overtakes the `done.invoke` **40/40** times — the
exact ordering `#116` was written to make identical across engines. Inside the
run loop the ordering is correct (`p6`: both engines agree, 50/50 identical
traces), so this is confined to the startup macrostep.

§2 has the prior-defect table, §3 the new attacks, §4 the defect register,
§5 coverage and gaps, §6 the verdict.

---

## 1. Method and reductions

All commands were run from `battle-cec108b/concurrency/` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1` and
`PY=".../_ref/xstate-statemachine/.venv-main/Scripts/python"`, each under
`timeout` per the ≤120 s-per-script bound (the fuzz and soak scripts have
their own longer, explicitly-granted budgets; the livelock probe's watchdog
is 30 s per case as mandated).

### 1.1 Reductions (stated as required)

Every reduction is a **parameter** reduction; no invariant, accounting rule or
instrument was weakened.

| Script | Brief / prior | This run | Why |
|---|---|---|---|
| `a1_bounded_fanin.py` | 400×250×16 (prior) | **300 × 200 × 16 = 60,000 ev** per policy | Whole-track wall clock. The accounting identity is per-event. |
| `c1_stop_leaks.py` | 1,000 cycles | **300** cycles × 7 variants | Task-leak delta is before/after; 300 cycles covers every race phase. |
| `b1_threadsafe.py` | 32 × 2,500 | **32 × 800**, unpaced only | The unpaced max-rate case is the one that stresses ingest. |
| `f1_memory.py` | 60k × 20 (prior) | **40,000 ev × 15 machines** × 3 shapes | Growth is reported per-event, so comparable. |
| `g1_loop_blocking.py` | 7 scenarios | **3 scenarios** (s0 idle, s1 saturated, s6 blocking-action control), 2.0 s window | The three that bound the envelope; s2–s5 sit between them. |
| `n1_persist_property.py` | 600 events | **400 events**, full round-trip every 10th | Superseded as the *parallel* instrument by `p3` (300 Hypothesis cases, 879 quiescent points). |
| `p3_parallel_persist_property.py` | brief: ≥300 cases | **300 cases** (879 quiescent points) | At the brief's floor. |
| `p5` part A livelock fuzz | brief: "config fuzzer" | **48 cases** (24 seeds × 2 shapes), 30 s watchdog each | 48 × up-to-30 s is the most that fits; all settled in <0.1 s, so the watchdog was never binding. |
| `n9_soak_chaos.py` | brief: 12 min | **300 s (5 min)** | Whole-track wall-clock bound. Chaos mix and all six invariants unreduced. |
| `p6` hash-seed sweep | brief: "sweep" | **5 seeds** (0, 1, 2, 7, 12345) | Each seed is a subprocess running both engines. |
| `p2` v4 cycles / `p1` v1 | brief: 500 / 200 | **500** / **200** | At the brief's figures. |

### 1.2 Scripts adapted for superseded behaviour (recorded)

- **`a2_block_edges.py` line 103.** The original does
  `asyncio.create_task(i.send("PING"))`. On `cec108b` `send()` is a *regular*
  method that enqueues eagerly and returns an already-resolved `Future`
  (the #37/#104 design), and `create_task()` rejects a `Future` with
  `TypeError`. Changed to `asyncio.ensure_future(...)`, which accepts both
  shapes. **Harness artefact, not a behaviour change** — the eager-enqueue
  design is documented and is what closes `D-concurrency-1`.
- **`p4`'s `Rec.on_unhandled_event`.** First written against the prior
  `reason=` spelling; the hook's real signature is
  `(interpreter, event, active_state_ids, disposition)` (`plugins.py:356`).
  Adapted to the real signature — the `"guard_denied"` value arrives on
  `disposition`, which is the #153 contract.
- **`n1`, `d3_snapshot_in_window.py` → `d3b`, `d2` → `d2b`** carry forward the
  prior round's documented adaptations unchanged; see
  `battle-3ed3099/concurrency.md` §1.2.

### 1.3 Commands

```bash
# prior repros
$PY n5b_snapshot_corrupt_minimal.py ; $PY n6b_cancel_before_first_turn.py
$PY n8b_escalate_needs_invoke_id.py ; $PY d1_block_fire_and_forget.py
$PY d2b_block_stop_attribution.py   ; $PY d3b_midstep_snapshot.py
$PY d4_plugin_cancellederror.py     ; $PY b3_threadsafe_backpressure.py
$PY probe_d_cancel.py ; $PY probe_d_empty_window.py
$PY a2_block_edges.py ; $PY -W error -X dev c1_stop_leaks.py 300
$PY e1_plugin_hook_raises.py ; $PY e2_plugin_containment_edges.py
for c in KeyboardInterrupt CancelledError; do $PY e3_baseexception_case.py $c; done
$PY h2_reader_race_gil.py
for p in raise block drop_newest; do $PY a1_bounded_fanin.py $p 300 200 16 64; done
$PY b1_threadsafe.py 32 800 0 ; $PY b2_threadsafe_cost.py
$PY f1_memory.py 40000 15 15 --depth=4
for s in s0 s1 s6; do $PY g1_loop_blocking.py 2.0 $s; done
$PY n1_persist_property.py --events=400 ; $PY n2_per_task_gate.py
$PY n3_block_16_producers.py ; $PY n4_determinism.py
$PY n5_fuzz_snapshot_events.py ; $PY n6_observability_matrix.py
$PY n7_security_surface.py ; $PY n8_semantics.py
# new attacks
$PY p1_service_executor.py ; $PY p1b_invoke_ordering.py
$PY p2_threadsafe_die.py ; $PY p3_parallel_persist_property.py
$PY p4_semantics_observability.py ; $PY p5_fuzz.py
$PY p6_determinism_surface.py ; $PY n9_soak_chaos.py --seconds=300
```

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

| ID | Prior severity | Verdict | Evidence on `cec108b` |
|---|---|---|---|
| **D5-concurrency-1** — leafless `configuration` restores as a `running`, permanently-inert machine | Blocker | **FIXED** | `n5b`: `raw_exception_case_count: 0`, `silent_empty_config: []`, `result: PASS`. `p5` B: 5,000 mutations, `restored_running_with_no_leaf: 0`. `p3` T1/T1b: dropping one **region's** leaf from `configuration` (with or without a matching `state_ids` edit) → `SnapshotCorruptError`. The read side now applies the exactly-one-leaf-per-region rule (#142/#143). |
| **D5-concurrency-2** — `from_snapshot` leaks raw `TypeError`/`AttributeError`/`ValueError` | High | **FIXED** | `p5` B: `raw_unnamed_exceptions: {}`, `raw_total: 0` over 5,000 mutations (was 906/5,000). Named outcomes only: `SnapshotCorruptError` 2,726, `SnapshotDriftError` 355, `SnapshotVersionError` 154; 1,765 legitimately restored. `n5` A agrees: `raw_unnamed_exceptions: {}`, `restored_with_EMPTY_configuration: 0`. (#146/#158) |
| **D5-concurrency-3** — `#114` not published for a cancel before the run loop's first turn | High | **FIXED** | `n6b`: 3/3 cases `publishes_114: true`, `status="error"`, `send(wait=True)` resolves with `InterpreterStoppedError` — including `yield_before_cancel: false`. `n6` v8 `pass: true`. `p2` v3 adds double/triple cancel: exactly **one** `on_error` per case, never hung. (#148 `_die` done-callback, idempotent) |
| **D5-concurrency-4** — `escalate` needs an explicit `invoke.id` | Medium | **FIXED** | `n8b` matrix 4/4 including `escalate,id=False`; `escalate_works_without_id: true`. `n8` v130 `pass: true` for both child shapes. (#156 `_invoked_as`) |
| **D-concurrency-6** — `send_threadsafe` has no backpressure signal on the calling thread | High (carried from `5e07ba8`) | **FIXED** | `b3` v2 (cap 100, RAISE): **5,217 raised on the calling thread** vs 1,183 returning a future (was 6,400 / 0). `p2` v2 (cap 32, 16 threads, 4,800 calls): 4,136 raised at the call site, 321 failed only on a future, 343 processed — **4,800 accounted, 0 lost**. v1 unbounded backlog is no longer monotonic (peak 921, drains in 25 ms). (#157) |

**Score: 5 FIXED, 0 CHANGED, 0 STILL-PRESENT.** The Blocker and every High on
this track are closed at the root.

### 2.1 Prior "clean" results — re-confirmed

| Area | Result on `cec108b` |
|---|---|
| Fan-in accounting (`a1`, 3 policies × 60,000 ev) | `unaccounted_accepted_but_lost: 0`, `attempt_balance_ok: true` on all three |
| Cross-thread ingest (`b1`, 32 threads × 800, unpaced) | 25,600 attempted / 25,600 processed, **0** per-thread order violations, 0 unaccounted, 32/32 strict typos rejected on the calling thread, 8,318 ev/s |
| Stop/teardown races (`c1`, 7 variants × 300 cycles, `-W error -X dev`) | `task_delta: 0`, 0 `RuntimeWarning`s, 0 "Task destroyed", 0 loop exceptions — every variant |
| `BLOCK` delivery (`d1`, `d2b`, `n3`) | `d1` 10/10 delivered; `d2b` 0/5 parked events unattributed; `n3` 3,200/3,200 in both variants + 500/500 fire-and-forget |
| Mid-step snapshot (`d3b`) | Q1 refused with `SnapshotMidStepError`; Q3 quiescent round-trip clean. Q2 live-reader window persists (see §5) |
| Plugin containment (`d4`, `e1`, `e3`) | Hook-raised `CancelledError` contained, machine alive and answering; all 10 hooks contained; `KeyboardInterrupt`/`SystemExit` still escape by design |
| Per-task self-send gate (`n2`) | A 24/24, B 24/24 threads, C 72/72 actor-shaped — **0** spurious `chain_budget` drops; control D still trips at 9 runs with `RunawayChainError` |
| Determinism (`n4`) | 1 distinct trace hash in 50 per engine; batch ≡ singles on both |
| Memory (`f1`, 40,000 ev × 15 machines × 3 shapes) | `gc_objects` flat at 21,693 across all batches; `asyncio_tasks` flat at 16; RSS +~1 MB |
| Loop latency (`g1`) | s1 saturated: 14,443 ev/s, tick lateness p50 2.48 / p95 7.04 / max 16.0 ms, 0 slow-callback hits. s6 (20 ms blocking action control) p50 28.7 ms — by design |
| Reader race under GIL (`h2`) | 1,511,345 reads from 8 threads during 4,853 transitions, **0** reader exceptions |
| Cancellation of awaiters (`probe_d_cancel`) | 0 invariant violations, 0 leaked receipts, machine still running |
| Security surface (`n7`) | 0 secret values in the log corpus, `redact` pure, opt-out explicit, engine-named user `Event` still not a system event, 78 public names |

---

## 3. New attacks

| # | Script | Target (issue) | Result |
|---|---|---|---|
| P1 | `p1_service_executor.py` | #149 `service_executor` for plain-`def` services | **3 of 4 PASS** — v1 200 concurrent services: 200/200 completed on **200 distinct executor threads**, never the loop thread, loop kept turning; but only **158/200** saw `done.invoke` before an event queued right after `start()` → **D6-concurrency-1**. v2 `stop()` mid-service: returns in 1 ms, no hang, no leak. v3 a caller-supplied executor is still usable after `stop()` while an owned one is released. v4 200 lifecycles → thread delta **−1** |
| P1b | `p1b_invoke_ordering.py` | Minimal repro + sync control for the P1 v1 ordering gap | **FAIL (repro)** — after `await Interpreter.start()` the machine is still in `ord.run` with an empty trace for a 0 ms *and* a 20 ms service; `SyncInterpreter.start()` returns already in `ord.ok` with `["done"]`. Sweep: **0/40** (0 ms) and **0/20** (5 ms) async runs put `done` first |
| P2 | `p2_threadsafe_die.py` | #150 `internal=True` forgery, #157 RAISE at the call site under 16 threads, #148 `_die` under double cancel, 500 cycles | **PASS** — v1 200 forged-`internal` sends from 8 non-action threads: all 200 processed, machine alive, no wedge, no chain-budget trip, and a user `Event` is still not a system event. v2 4,800 calls: **4,136 raised on the calling thread**, 4,800 fully accounted. v3 1/2/3 cancels → exactly one `on_error`, `status="error"`, receipt resolves. v4 500 cycles → thread delta 0, task delta 0 |
| P3 | `p3_parallel_persist_property.py` | Hypothesis property over random **parallel** machines, 300 cases (#142/#143/#162) | **PASS** — 879 quiescent points: 0 snapshot raises, 0 unstable snapshots, 0 round-trip mismatches, **0 byte-identity mismatches**, 0 one-leaf-per-region violations. Torn cases: `T1` drop one region's leaf → `SnapshotCorruptError`; `T1b` `configuration`-only tear → `SnapshotCorruptError`; `T2` v1 upcast with torn `state_ids` → `SnapshotCorruptError`; `T2b` v1 intact → restores; `T3` `status="error"` with no error → `SnapshotCorruptError`; `T4` `stopped` → restores as stopped |
| P4 | `p4_semantics_observability.py` | #152 / #153 / #147 / #145 / #133 / #134 / #159 | **PASS (6/6)** — v1 raising guard cancels only its candidate, unguarded `invoke.onDone` fallback **is** taken, `on_guard_error` fires, `last_transition_ok=False` + `last_error` records it. v2 `Receipt.denied=True` + `disposition="guard_denied"` for a declared-but-refused handler vs `denied=False` + `"ignored"` for an undeclared one, one hook each. v3 `RootTargetError` on **both** `strictTargets=True` and `False`. v4 `"fail"` → `status="stopped"`, configuration cleared, `TransitionFailedError` on `.error`, parent reaches `onError` — async **and** sync. v5 `unresolved_target` ×1, `chain_budget` ×1 + `RunawayChainError`, `on_invalid_event` ×1 with `InvalidEventError` |
| P5 | `p5_fuzz.py` | Livelock config fuzzer (#144/#151), 5,000-mutation snapshot fuzz (#146), event-type fuzz (#113/#161) | **PASS** — A: **48/48** settled (24 nested-`invoke`-onDone-cycle + 24 parallel-`always`-cycle machines, `maxIterations` ∈ {5,20,50}) on the **sync** engine under a 30 s watchdog; 0 livelocks, 0 raw exceptions. B: 0 raw exceptions, 0 illegal restores (see §2). C: 14/15 hostile event shapes → `InvalidEventError` (also a `TypeError`), including a non-`str` dict key (#161); `""` accepted (see §5) |
| P6 | `p6_determinism_surface.py` | 50× traces both engines with **executor** services, hash-seed sweep, API/redaction surface | **PASS** — 1 distinct trace hash in 50 on each engine; final states and context **equal across engines**; 5 `PYTHONHASHSEED` values give 1 distinct (engine-hash, engine-hash) pair. Surface: 0 missing exports, 0 missing hooks, `Interpreter(service_executor=)` present, `Receipt.denied` present, **0** secret values in 28 DEBUG log lines including `get_snapshot()`/`get_persisted_snapshot()` (#160) |
| N9 | `n9_soak_chaos.py --seconds=300` | 5-min reduced chaos soak, 6 continuous invariants | **PASS** — see §3.1 |

### 3.1 Soak (N9)

300 s of continuous chaos: per cycle a fresh interpreter (random inbox cap of
16/64/unbounded) driven with a 20–120-event burst mixing `wait=True` and
fire-and-forget sends, a 2%-probability raising plugin hook, periodic hostile
event types, `after` timers, random `stop(drain=…)`, and a 30% chance of a
snapshot→restore→start→stop round trip (snapshots taken only at quiescence).

```
seconds 300.3   cycles 9,021   events_sent 622,891   processed_hook 617,115
S2 running-with-empty-configuration      : 0   (live AND restored)
S3 quiescent snapshot failures           : 0   (9,021 snapshots, 2,720 restores)
hostile event-type escapes               : 0
S4 asyncio task delta                    : 0
S5 RSS                                   : 30.11 MB -> ~30.8 MB  (+0.7 MB over 5 min)
S6 loop errors / "Task destroyed pending": 0 / 0
dropped_hook                             : 0
RESULT: PASS
```

As in the prior round, S1 (accepted-vs-lost) is **reported, not asserted** in
this script — the 5,776-event difference is the tail in flight at each cycle's
`stop()` plus the deliberately-hostile types refused at the call site. The
strict identity is asserted by `n3`, `a1` and `p2` v2, which control the stop
point.

---

## 4. Defect register — `D6-concurrency-n`

### D6-concurrency-1 — `Interpreter.start()` does not await the #149 executor hop, so a plain-`def` service invoked by the INITIAL state has not completed when `start()` returns (and the two engines disagree)

**Severity: Medium.**
**Repro:** `p1b_invoke_ordering.py` (deterministic, 60/60 trials); found by
`p1_service_executor.py` v1 (158/200 at scale — the 42 misses are the machines
whose `RACE` send landed first).

```
async : await Interpreter(m).start()
          current_state_ids -> ['ord.run']        context['seen'] -> []
        i.send("RACE"); await wait_done()
          context['seen'] -> ['race', 'done']     done_first = False
sync  : SyncInterpreter(m).start()
          current_state_ids -> ['ord.ok']         context['seen'] -> ['done']
          final order                             ['done']
sweep : service sleep 0 ms  -> done_first 0/40
        service sleep 5 ms  -> done_first 0/20
```

**Root cause.** `#149` moved plain-`def` services onto
`_get_service_executor()` and preserved `#116`'s ordering by having the
*entering macrostep* await the handoff: `_process_event_and_transient_
transitions()` calls `await self._await_inline_services()` twice
(`interpreter.py:1645` and `:1649`). `start()` enters the initial
configuration on a different path — `await self._enter_states([self.machine],
init_event)` then `await self._settle_transient_transitions()`
(`interpreter.py:487` and `:496`) — and **never calls
`_await_inline_services()`**. The future created by
`_invoke_plain_service_inline` (`interpreter.py:2417-2425`) is therefore left
in `self._inline_service_futures` and is only drained by the first *event*
macrostep, i.e. after `start()` has returned and after anything the caller
queued in between. `SyncInterpreter.start()` runs the service inline and has
no such window, so the two engines disagree on the machine's state the instant
`start()` returns — the precise property `#116` exists to guarantee.

**Why Medium, not High.** It is confined to the startup macrostep: inside the
run loop the ordering is correct and exact (`p6`: 50/50 identical traces per
engine, cross-engine states and context equal; `n8` v116 passes). It does not
lose the completion — `done.invoke` still arrives, just later — and it does
not corrupt state. But an adopter that treats `await start()` as "the machine
has settled" (which `start()`'s own docstring and the `#124`/settle-transients
work both encourage) will see a machine in its pre-invoke state, and an order
submitted immediately after startup can be processed **before** the startup
service's completion transition. On an order path that is an ordering
surprise, not a loss.

**File:line.** `src/xstate_statemachine/interpreter.py:487` and `:496`
(`start()` misses the drain), against `interpreter.py:1645` / `:1649` where
the run loop does it, and `interpreter.py:2365-2381`
(`_await_inline_services`, the correct routine, already present). Fix shape:
`await self._await_inline_services()` after `_enter_states(...)` and again
after `_settle_transient_transitions()` inside `start()`.

**Not a defect, for the record:** the residual 42/200 in `p1` v1 is the same
mechanism seen concurrently; `p1b` is the authoritative repro.

---

## 5. Coverage — and what was NOT covered

### Documented constraints (observed, deliberately not counted as defects)

- **The live-reader window inside an awaiting action persists.** `d3b` Q2:
  during any `await` inside a transition action, `current_state_ids == []`,
  `matches(x) == False`, `status == "running"`. Durability is closed by
  refusal (`SnapshotMidStepError`) and `probe_d_empty_window` v5 confirms the
  sync-action control shows **0** empty observations. Unchanged from the prior
  round and still a design constraint an adopter must observe via
  `on_transition` rather than by polling.
- **`send("")` is accepted** (`p5` C, `n5` B). `#113`/`#161` are about
  non-`str` types and non-`str` dict keys; `""` is a `str`. A stringified
  empty field therefore reaches the machine as a legitimate unhandled event.
  Reported, not counted — third consecutive round.
- **`KeyboardInterrupt` / `SystemExit` from a plugin hook still escape
  `asyncio.run`** (`e3`). Correct: these are `BaseException`s.
- **A synchronous plugin hook / blocking action is charged to the run-loop
  task** (`g1` s6: a 20 ms action gives 20.5 ms loop-turn gaps). By design.
- **`internal=True` from a foreign thread is accepted on the caller's word**
  (`p2` v1). This is the documented #150 escape hatch for a plain
  `threading.Thread`, and it routes to the *internal* queue, which is
  unbounded — so a hostile or buggy caller can bypass the inbox cap and the
  overflow policy. It does **not** forge system provenance (the event is still
  a user event) and it is charged to the chain budget, so a runaway is still
  cut. Recorded as an authority boundary, not a defect: `send_threadsafe` is
  already an in-process API with full access to the interpreter.

### Not covered this run

- **Free-threading build (track item h1).** The `.venv-ft` interpreter was not
  rebuilt for this commit; `h1_free_threading.py` was not run. The GIL-build
  counterpart `h2` is clean. Any claim about `Py_GIL_DISABLED` behaviour on
  `cec108b` is **unverified**.
- **Full-scale sweeps.** Per §1.1, fan-in ran at 60k rather than 1M events per
  policy, stop-races at 300 rather than 1,000 cycles, memory at 40k × 15.
  Rare-event tails needing 10–20× the volume are outside this run's
  resolution.
- **The soak is 5 minutes, not 12.** Degradation with an onset past 5 minutes
  is not covered, and its S1 total is reported rather than asserted.
- **`g1` scenarios s2–s5** were not run (3 of 7 scenarios).
- **Snapshot in an entry-action window was not attacked directly this round.**
  `d3b` covers the transition-action window; the *entry*-action variant named
  in the brief was exercised only indirectly, through `p3`'s quiescent-point
  property and the soak's chaos snapshots. A targeted entry-action probe is
  **not** in this run.
- **"Actors + deferred buffer legality" was covered only structurally.** `p3`
  round-trips whatever `actors` / `deferred` the random parallel machines
  produce and `p5` B fuzzes both keys, but no machine in this run held a
  *populated* deferred buffer together with live spawned child actors at the
  snapshot point. That specific combination is unverified.
- **`"fail"`-stopped snapshot refusal** was tested via the `status="error"`
  -with-no-error case (`p3` T3, refused) and the `stopped` case (T4, restores
  as stopped). A snapshot taken from a machine that was *actually* stopped by
  `actionErrorPolicy="fail"` mid-run was **not** captured and re-restored.
- **`SimulatedClock` + `restart_timers` determinism** across a restore is
  still unexercised (`n1` sees 17 dormant-timer observations but does not
  drive a deterministic replay); `from_snapshot(clock=)` (#117) untested.
- **Executor thread-context leakage** was tested only for the property that
  matters here — `p1` v1 shows services run on 200 distinct non-loop threads
  and `p2` v1 shows the self-send `ContextVar` gate is not confused by
  foreign threads. Whether an action's `contextvars` context is inherited by
  the **service** executor thread (and what a service could therefore observe
  or forge) was not measured.
- **Child-actor `#105` is still simulated, not spawned** (`n2` scenario C),
  carried forward from the prior round.
- **The API-surface diff vs `3ed3099` is by count, not by name-set.** Both
  commits report 78 public names and all required names are present; the
  exact added/removed sets were not diffed.

---

## 6. Verdict

**Round 5 closes this track's backlog completely. One new, narrow,
mechanically-small defect remains.**

Every defect this track has carried — the `D5-concurrency-1` Blocker, the two
Highs (`D5-concurrency-2`, `D5-concurrency-3`), the Medium
(`D5-concurrency-4`) and `D-concurrency-6`, which had survived two rounds
untouched — is fixed, and each is fixed at the root rather than masked. The
restore path now enforces the same exactly-one-leaf-per-region legality the
write path does, verified not by a single repro but by a 300-case property
over randomly-generated **parallel** machines snapshotted at all 879 of their
quiescent points with byte-identical round-tripping and by 5,000 hostile
mutations that produced **zero** raw exceptions and **zero** illegal restores.
`_die` is genuinely idempotent under repeated cancellation. `QueueOverflowError`
now lands on the calling thread, which is what makes a cross-thread producer
design viable at all. The two sync-engine livelocks are gone: 48 randomly
generated cycle machines — the nested-`invoke`-`onDone` and
parallel-`always` shapes that hung — all settled in under 0.1 s against a
30 s watchdog. Semantics and observability are 6/6 on the round's own new
contracts, determinism is exact and hash-seed independent, redaction covers
`get_snapshot()`, and a 5-minute chaos soak at 9,021 cycles and 622,891
events is clean on every invariant with a 0.7 MB RSS drift.

**D6-concurrency-1** is the only thing standing between this track and a
clean bill. It is a one-line-shaped omission with its own correct
implementation sitting 1,100 lines away in the same file: `start()` enters the
initial configuration without draining `_inline_service_futures`, so a
plain-`def` service invoked by the initial state completes *after* `start()`
returns on the async engine and *before* it returns on the sync engine. That
is a genuine cross-engine divergence in exactly the property `#116` was
written to establish, and it is deterministic — 0/60 async trials put the
completion first — but it loses nothing and corrupts nothing; it reorders the
startup boundary.

**Recommendation for this track: READY, conditional on D6-concurrency-1.**
Fix the `start()` drain and the concurrency, backpressure and resource-limit
surface has no known open defect on `cec108b`. Adopters should still design
around the two standing constraints: the live-reader window inside an awaiting
action (observe via `on_transition`, not by polling) and `send("")` reaching
the machine as a legitimate event. The §5 not-covered list — free-threading,
full-scale sweeps, the 12-minute soak, the entry-action snapshot window,
populated-deferred-plus-live-actors snapshots, and `SimulatedClock` restore
determinism — bounds the strength of this verdict and should be closed by a
later run rather than assumed.
