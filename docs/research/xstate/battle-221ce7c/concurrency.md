# Battle test (round 7) — CONCURRENCY, BACKPRESSURE & RESOURCE LIMITS

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`221ce7c`** (merge of #178, "loop-side RAISE refusals observable").
`__version__` still reads `0.8.0`; the `[Unreleased]` CHANGELOG block targets
0.8.1. Keyed on the commit, not the version string.

**Date:** 2026-09-20. **OS:** Windows 11 Pro 10.0.26200.
**Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python` — CPython
**3.13.7** (GIL build), env `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Predecessor:** `battle-cec108b/concurrency.md` (`D6-concurrency-1`, since
fixed as #171). Round-6 register: `38-r6-findings-register.md`.
**Scripts:** `battle-221ce7c/concurrency/*.py`; raw results in the sibling
`*.json`. Prior-round scripts were copied forward unmodified and re-run.

---

## 0. Bottom line

**Every prior defect on this track is FIXED.** The round-6 headline —
"every self-generated cycle is bounded on `Interpreter`" — **holds**: 500
fuzzed cyclic configs across both engines produced **zero livelocks**, the
trip is observable on both engines at the *same lap count*, and the 300 s
chaos soak and the 100 s / 200-machine shape soak both stayed CPU-bounded
with zero torn snapshots and zero task leaks.

**Three NEW defects.** One is a genuine liveness failure in production shape;
two are observability gaps.

| ID | Sev | One line |
|----|-----|----------|
| **D7-concurrency-1** | **High** | A self-re-arming *invoke* cycle under sustained external traffic never drains its inbox: 10/10 machines stopped answering `send(wait=True)` within 5 s, backlog grew monotonically to 20 207 events, `status` stayed `"running"`. |
| **D7-concurrency-2** | **Medium** | `get_persisted_snapshot()` from `on_action_execute` returns a **torn** blob (`status: "running"`, `state_ids: []`) on the async engine; the sync engine refuses the same call. Caught on restore by #143, so it is an observability/parity defect, not corruption. |
| **D7-concurrency-3** | **Low** | Call-site `QueueOverflowError` refusals from `send_threadsafe()` fire **no** `on_event_dropped` hook; only loop-side refusals do. 6 021 of 12 087 refusals were invisible to the hook in a 2 s, 16-thread run. |

**Verdict: READY for this track, conditional on D7-concurrency-1.** The
invoke-cycle shape must be kept out of the catalogue (or `maxIterations`
must be understood as a per-external-event re-buy) until it is fixed.

---

## 1. Method and reductions

Every prior script in `battle-cec108b/concurrency/` was copied into
`battle-221ce7c/concurrency/` **unmodified** and re-run. New attacks are the
`q*` files. Library source was never modified.

### 1.1 Reductions (stated as required)

| Item | Brief | Run | Why |
|------|-------|-----|-----|
| Chaos soak (`n9_soak_chaos.py`) | 12 min | **300 s** | 20 min whole-task bound; unreduced invariant set. **PASS**. |
| Shape soak (`q7_soak_round7_shapes.py`) | 12 min | **100 s**, 200 machines | 120 s per-script bound. Shape mix and invariants unreduced. |
| Livelock fuzz watchdog (`q4`) | 30 s | **6 s** | 500 configs × 2 engines × 30 s does not fit 120 s. Every livelock observed in this family hangs *indefinitely*; 6 s discriminates just as well, and the fuzz found **zero** timeouts either way. |
| Livelock fuzz configs | ≥500 | **500** | Unreduced. |
| Hook-snapshot property (`q2`) | ≥300 machines | **300** | Unreduced. |
| Memory probe (`f1_memory.py`) | 1 M events | **40 000 events, 25 machines, 5 batches** | The 1 M-event default exceeds 120 s on this host at `tracemalloc` depth 4. Growth is flat at this size (96.9 → 98.6 KiB traced across all three shapes), which is what the probe measures. |

### 1.2 Scripts adapted for documented-superseded behaviour (recorded)

- **`d3_snapshot_in_window.py` now exits 1 with an uncaught
  `SnapshotMidStepError`.** This is the **fix** (#169/#142) landing: the
  script was written against a build where the mid-step snapshot *returned*
  a torn blob, so it calls `get_persisted_snapshot()` unguarded inside the
  window. Recorded as **FIXED**, not as a failure. Left unmodified so the
  traceback is the evidence.
- **`e3_baseexception_case.py` takes the exception class as `argv[1]`**; it
  is a driver, not a self-contained probe. Run once per class (four runs).
  `KeyboardInterrupt` and `SystemExit` escape `asyncio.run` — correct and
  unchanged. `MemoryError` / `CancelledError` are contained, machine stays
  usable, `stop()` clean.
- **`n5_fuzz_snapshot_events.py` still exits 1** on exactly one sub-case:
  `empty_str` (`send("")`) is accepted with `error=None`. **Byte-identical
  to the round-6 result** — pre-existing, already registered off this track,
  not a regression. Snapshot-mutation half is clean (5 000 mutations, 0
  empty-configuration restores).

### 1.3 Commands

```bash
PY="_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
cd docs/research/xstate/battle-221ce7c/concurrency

# prior repros (all 30, batched)
for f in a1_bounded_fanin a2_block_edges b1_threadsafe b3_threadsafe_backpressure \
         c1_stop_leaks d1_block_fire_and_forget d2_block_stop_silent_drop \
         d2b_block_stop_attribution d3_snapshot_in_window d3b_midstep_snapshot \
         d4_plugin_cancellederror e1_plugin_hook_raises e2_plugin_containment_edges \
         g1_loop_blocking h1_free_threading h2_reader_race_gil probe_d_cancel \
         probe_d_empty_window n1_persist_property n2_per_task_gate \
         n3_block_16_producers n4_determinism n5_fuzz_snapshot_events \
         n5b_snapshot_corrupt_minimal n6_observability_matrix \
         n6b_cancel_before_first_turn n7_security_surface n8_semantics \
         n8b_escalate_needs_invoke_id p1_service_executor p1b_invoke_ordering \
         p2_threadsafe_die p3_parallel_persist_property p4_semantics_observability \
         p5_fuzz p6_determinism_surface; do timeout 115 $PY $f.py; done
for n in KeyboardInterrupt SystemExit MemoryError CancelledError; do $PY e3_baseexception_case.py $n; done
$PY f1_memory.py 40000 25 5
$PY n9_soak_chaos.py --seconds=300

# new attacks
$PY q1_chain_budget_external.py
$PY q1b_minimal_budget_reset.py
$PY q1c_engine_parity_amplification.py
$PY q2_hook_snapshot_property.py --n=300
$PY q2b_minimal_action_hook_torn.py
$PY q3_pool_counter_hooks.py
$PY q4_livelock_fuzz.py --n=500 --wd=4
$PY q4b_minimal_trip_observability_parity.py
$PY q4c_external_event_erases_trip.py
$PY q5_determinism_sentinel.py
$PY q5b_hashseed_sweep.py
$PY q6_semantics_security.py
$PY q6b_internal_threadsafe_depth_leak.py
$PY q7_soak_round7_shapes.py --seconds=100 --n=200
$PY q7b_minimal_invoke_cycle_unresponsive.py
```

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

The only *open* defect this track carried into round 7 was
`D6-concurrency-1` (merged into register item **R6-11**, fixed as #171).

| Prior ID | Round-6 claim | Probe re-run | Verdict |
|----------|---------------|--------------|---------|
| **D6-concurrency-1** (= R6-11) | `await Interpreter.start()` returns before the initial state's `invoke` children are registered and before a plain-`def` initial service completes; engines disagree on `start(); send(CANCEL)` ordering | `p1b_invoke_ordering.py`, `p1_service_executor.py`, `q6_semantics_security.py` (S2) | **FIXED** |

**Evidence.** `p1b_invoke_ordering.json` flipped completely against the
round-6 baseline: `done_first` went `false → true` in both single-shot
cases, the `race` disposition disappeared from the outcome set, and the
trial counters inverted — `done_first 0/40 → 40/40` and `0/20 → 20/20`,
`race_first 40 → 0` and `20 → 0`. `p1_service_executor.json`:
`done_before_queued_RACE` went `158/200 → 200/200`. Independently
confirmed by the new `q6` S2 probe, which runs `start(); send("CANCEL")`
20× on **each** engine and gets `{"done,cancel": 20}` on both —
deterministic and in parity, which is exactly the #116 contract.

**Score: 1 FIXED, 0 CHANGED, 0 STILL-PRESENT.**

### 2.1 Prior "clean" results — re-confirmed, no regressions

All 30 remaining prior scripts were re-run. Results are **byte-identical**
to the round-6 JSON for: `n3_block_16_producers`, `n4_determinism`,
`n6_observability_matrix`, `n6b_cancel_before_first_turn`,
`n7_security_surface`, `n8_semantics`, `n8b_escalate_needs_invoke_id`,
`p4_semantics_observability`, `p5_fuzz`, `p6_determinism_surface`,
`n5b_snapshot_corrupt_minimal`. The three that differ do so only in
sampling counts, not dispositions:

- `n1_persist_property` — 600 events / 600 snapshots OK (was 400/400); 26
  dormant timers observed (was 17). Zero failures both rounds.
- `p3_parallel_persist_property` — 865 quiescent points (was 879), all
  legal.
- `f1_memory` — reduced params (§1.1); traced growth flat.

`n5_fuzz_snapshot_events` reproduces the same single known `empty_str`
sub-case (§1.2) — unchanged, pre-existing, off-track.

`a1/a2/b1/b3` (backpressure edges), `c1` (stop leaks), `d1/d2/d2b`
(BLOCK + stop attribution), `d3b` (mid-step snapshot), `d4` +
`probe_d_cancel` + `probe_d_empty_window` (cancellation), `e1/e2`
(plugin containment), `g1` (loop blocking), `h1/h2` (free-threading /
reader race) all exit 0.

### 2.2 Round-6 fixes independently re-verified against this track's own probes

| Fix | Probe | Result |
|-----|-------|--------|
| #166/#167/#168 cycle bounding on `Interpreter` | `q4_livelock_fuzz.py` (500 configs × 2 engines) | **0 livelocks** in any shape |
| #168 "same lap count on both engines" | `q4b_minimal_trip_observability_parity.py` (6 rows) | **exact parity**: 51/51, 201/201, 1001/1001 laps, `RunawayChainError` on both |
| #169 entry/exit-action snapshot refusal at root | `q2b`, `q2` | refused on sync in **100 %** of hook calls; async refuses from `on_transition` and most of `on_action_execute` — **one window survives**, see D7-concurrency-2 |
| #170 `Receipt.denied is False` for a crashed guard | `q6` S1 async matrix | **confirmed**: `DENIED → (changed=False, denied=True, error=None)`, `CRASH → (False, False, RuntimeError)`, `UNKNOWN → (False, False, None)`, `OK → (True, False, None)` — four distinct signatures |
| #171 `start()` awaits initial invokes | §2 above | **FIXED** |
| #172 threadsafe in-flight counter balances | `q3` B, `q6b` | counter returns to **0** on every path tested (400-send burst, delivered + refused + cancelled) |
| #173 `service_pool_size` | `q3` A | `pool_1` and `pool_4` both stop cleanly mid-service; **thread delta 0**, task leftover 0 |
| #157 loop-side RAISE refusal observable | `q3` C | loop-side refusals **are** observable (6 066 hooks for 6 066 loop-side refusals) — but see D7-concurrency-3 |

---

## 3. New attacks (`q*`) — what each one found

| # | Attack | Result |
|---|--------|--------|
| **q1** | Chain/settle budget under **16 concurrent external senders** during a self-generated `always` chain | Trip observed in both quiet and loud runs, but laps to trip went **1 000 → 25 024** and the machine kept spinning to 72 071 laps afterwards. Root cause is the documented per-external-event reset; escalated into q1b/q1c. |
| **q1b** | Minimal: how little external traffic defeats the bound? | **One `POKE` per 100 ms** is enough: laps grow linearly for the whole 6 s window (6 005 → 57 056) and never settle. At 1 poke/s the machine does settle between pokes. |
| **q1c** | Engine parity for the amplification | **Both engines behave identically**: `GO` costs 1 000 laps, then **every** subsequent external event buys a *fresh* 1 001 laps. `engines_agree: true`. So the amplification is a **shared, documented design property** (`maxIterations` bounds a macrostep, not a lifetime) — recorded as a contract note, not an async regression. |
| **q2** | Property, 300 random nested+parallel machines, snapshot from `on_transition` / `on_action_execute` / `on_guard_evaluated` / `on_event_received`, 750 returned blobs restored and probed | **81 torn blobs**, *all* from `async:on_action_execute`. Sync engine refuses 100 % of its hook snapshots and produced zero torn blobs. → **D7-concurrency-2** |
| **q2b** | Minimal, deterministic version of the above | 5 `on_action_execute` calls on the async engine: **1 returns `{"status":"running","state_ids":[]}`**, 1 returns a legal blob, 3 are refused. Sync: 5/5 refused. Restoring the torn blob is **refused by `SnapshotCorruptError`** (#143 read-side guard works). |
| **q3 A** | `service_pool_size=1` and `=4`, 10 machines × 50 plain services, `stop()` mid-service | **PASS.** Both sizes: `stop` ok, thread delta 0, 0 leftover tasks, all `stopped`. |
| **q3 B** | `send_threadsafe(internal=True)` in-flight counter after a 400-send burst | **PASS.** `inflight=0`, `_raise_depth=0` at quiescence. |
| **q3 C** | Loop-side RAISE refusal hook, 16 threads × 2 s on a depth-4 inbox | 12 087 refusals total: 6 066 loop-side → **6 066 hooks** (exactly once); 6 021 call-side → **0 hooks**. → **D7-concurrency-3** |
| **q4** | Livelock fuzz, **500 configs × 2 engines**, shapes: `always_cycle`, `invoke_cycle`, `rollback`, `sendTo` self-loop | **0 livelocks, 0 `STOP_HUNG`.** The round-6 headline holds. |
| **q4b** | Trip observability parity at rest | **PASS**, 6/6 rows exact lap parity. |
| **q4c** | Does an external event erase the trip evidence? | **PASS** — `last_error` survives on both engines. (The 20 "disagreements" q4 reported are a probe artefact of sampling `last_error` after the external `TICK`; q4b/q4c disprove them. Recorded, not counted.) |
| **q5 D1** | 50× identical traces, both engines, incl. trip point | **PASS.** 1 distinct trace per engine, same trace across engines, lap count `{100}` on both, `context.n = 8` on both. |
| **q5 D2** | Perf-PR shared-sentinel aliasing (`_INIT_EVENT`) | **PASS.** Two concurrently-running machines see **different** `Event` objects (`same_event_object_across_machines: false`); a poisoned payload in machine 1 is invisible to machine 2. |
| **q5b** | `PYTHONHASHSEED` sweep (0, 1, 7, 12345, 99991) | **PASS.** `distinct_outcomes: 1`; identical traces, lap counts, trips and engine parity at every seed. |
| **q6 S1** | Guard-crash / denied / deferred / unhandled 4-way matrix | **PASS async** — four distinct `(changed, denied, error)` signatures. Sync returns `None` from `send()` so the discrimination is via **hooks + raised exception** instead (CRASH raises `RuntimeError`; DENIED and UNKNOWN both fire `on_unhandled_event(…, "deferred")`). Documented engine difference, not a new defect. |
| **q6 S2** | `start()` ordering vs #116 | **PASS**, 20/20 both engines, `done,cancel`. |
| **q6 S4** | Security surface | Secrets **not** leaked in `repr`/`str`. `__slots__` does **not** lock the instance (`has___dict__: true`, arbitrary attributes accepted) — but `Interpreter` never claimed to be a sealed object and the perf PRs' `__slots__` is documented as a layout optimisation, so this is **recorded, not a defect**. |
| **q6 S4b / q6b** | `internal=True` forgery from outside | `_raise_depth` sits at 100 after a 50-pair `internal=True` burst and only clears on the next external event. **Not exploitable**: a genuine cycle triggered *through* that leftover depth still gets its full 200 laps (measured at bursts 0/50/90 → 200/200/200 laps). Recorded as a cosmetic counter artefact. |
| **q7** | Soak, 200 machines, 4 shapes, executor services, chaos snapshot at quiescence, 100 s | CPU **1.11 s/wall s** (bounded — one core, not a busy-spin across 200 machines), RSS 40 → 61 MB, **0 torn snapshots** out of 10 690 taken, 0 leftover tasks, clean stop. **But 100/200 machines failed the 5 s liveness probe**, and exactly the 100 of the two invoke-cycle shapes. → **D7-concurrency-1** |
| **q7b** | Minimal isolation of the q7 liveness failure | A **single** invoke-cycle machine is fine (answers in 0.00 s even while driven). Under load: `plain` 0/10 wedged, backlog 0; `always_cycle` 0/10 wedged, backlog 0; **`invoke_pingpong` 10/10 wedged, backlog 20 207 and growing monotonically**. |

---

## 4. Defect register — `D7-concurrency-n`

### D7-concurrency-1 — a self-re-arming `invoke` cycle never drains its inbox under sustained external traffic: the machine is permanently unresponsive while reporting `status == "running"`

**Severity: High.** Liveness failure, silent, in a shape the round-6 fixes
explicitly targeted (#167 rollback-re-arm, #168 `ver -> arm -> ver`).

**Repro:** `q7b_minimal_invoke_cycle_unresponsive.py` (deterministic;
10/10 machines, every run). Discovered by
`q7_soak_round7_shapes.py --seconds=100 --n=200` (100/200 wedged).

```
shape                    machines  sent    backlog  not answering in 5 s
plain(control)             10      18 400     0            0
always_cycle(control)      10       6 200     0            0
invoke_pingpong            10      21 600  20 207         10
```

Inbox backlog trace for `invoke_pingpong`, sampled every 50 ms:
`200, 400, 597, 780, 970, 1160, 1364, 1553, 1742, 1935, 2130, 2323` —
strictly monotonic. Final statuses: all `"running"`. `stop()` is clean.

**Mechanism.** `interpreter.py:1650-1652` resets the settle budget when
"a user event (or anything the CALLER queued) starts a fresh settle
budget". For an invoke cycle that means: read one inbox event → reset
`_settle_iterations` → burn a full `maxIterations` laps of the cycle
(each lap costs an executor round-trip for the plain-`def` service) →
read the *next* inbox event. The service round-trip makes each lap far
more expensive than one inbound `send_threadsafe`, so the arrival rate
permanently exceeds the drain rate and the queue diverges. `always_cycle`
does **not** wedge because its laps are pure in-loop work and the trip
short-circuits them; `plain` has no cycle at all.

**Why a single machine looks healthy.** With one machine and one probe the
cycle trips (55 laps at `maxIterations: 50`) and the probe is answered in
0.00 s. The failure needs the queue to be *non-empty when the macrostep
ends* — i.e. real traffic. That is why q7 found it and the round-6
single-shot tests did not.

**File:line.** `src/xstate_statemachine/interpreter.py:1646-1652` (the
per-external-event budget reset) in combination with `:1580-1600` (the
drop-ends-chain reset). Both engines share the rule, but only the async
engine has an inbox that can grow, so only it wedges.

**Operational impact.** A catalogue machine that verifies-then-re-arms
via `invoke` becomes a black hole under load: events are accepted, never
processed, never dropped, no hook fires, `status` reads healthy, and
`last_error` reads `RunawayChainError` only between bursts. A health
check on `status` or `last_error` will not see it; only `queue_depth`
will.

---

### D7-concurrency-2 — `get_persisted_snapshot()` from `on_action_execute` returns a torn blob on the async engine; the sync engine refuses it

**Severity: Medium.** Observability + engine parity. Not corruption —
the #143 read-side guard rejects the blob on restore.

**Repro:** `q2b_minimal_action_hook_torn.py` (deterministic, 1 torn blob
per run). Property evidence: `q2_hook_snapshot_property.py --n=300` — 81
torn blobs out of 750 restored, **100 % of them from
`async:on_action_execute`**, 0 from any sync hook and 0 from any other
async hook.

```
async rows (5 on_action_execute calls, one STEP event):
  1  RETURNED  status=running  state_ids=[]        <-- TORN
  2  RETURNED  status=running  state_ids=[ord.top.one.deep]
  3  refused:SnapshotMidStepError
  4  refused:SnapshotMidStepError
  5  refused:SnapshotMidStepError
sync rows: 5/5 refused:SnapshotMidStepError
```

Dispositions across the 300-machine property run:

```
async:on_action_execute  refused 976   returned 375   <-- 81 of the sampled returns torn
async:on_event_received  refused   0   returned 710
async:on_transition      refused 639   returned 150
sync:on_action_execute   refused 1188  returned   0
sync:on_event_received   refused 596   returned   0
sync:on_transition       refused 535   returned 150
```

**Mechanism.** #169 armed the root refusal on "in flight" alone for
entry/exit actions. `on_action_execute` fires for **transition** actions
too, and for at least one of them the async engine is not flagged as in
flight while `_active_state_nodes` is already emptied by `_exit_states`.
The sync engine flags the whole `exit -> actions -> enter` transaction.

**Blast radius is bounded by #143:** restoring the torn blob raises
`SnapshotCorruptError: status is 'running' but the configuration has no
active leaf in every region`. So a torn blob cannot silently resurrect as
an inert machine — it fails loudly at restore time, which is why this is
Medium and not High. The defect is that a *monitoring* plugin gets a
blob it must itself know to distrust, and the two engines disagree.

**File:line.** `src/xstate_statemachine/base_interpreter.py:1393`
(`get_persisted_snapshot` refusal site) / the `_execute_transition`
`exit -> actions -> enter` transaction.

---

### D7-concurrency-3 — call-site `QueueOverflowError` refusals fire no `on_event_dropped` hook, so the shed rate is only half-observable

**Severity: Low.** Observability only; no event is lost silently from the
*caller's* point of view — the call site raises.

**Repro:** `q3_pool_counter_hooks.py`, part C (16 threads, 2 s, depth-4
inbox, `OverflowPolicy.RAISE`).

```
callsite_refusals   6 021      <-- raised QueueOverflowError at the call site
loopside_refusals   6 066      <-- error delivered on the returned future
total_refusals     12 087
queue_full_hooks    6 066      <-- exactly the loop-side half
other_drop_reasons  []
```

**Mechanism.** #157's fix added the hook to the **loop-side** refusal path
(`interpreter.py:1136-1137`). The optimistic call-site `qsize()` check
raises before anything is queued and never reaches that path, so it fires
no hook.

**Why this matters.** The #157 rationale was "correct load shedding with
a hidden shed rate". A plugin aggregating `on_event_dropped(queue_full)`
now sees a shed rate that is **~50 % of the truth** under the exact
conditions (16 concurrent producers) the hook was added for. An operator
reading only the hook under-counts backpressure by half.

**Counter-argument considered.** A call-site refusal raises into the
caller, which *is* a signal — that is the documented #157 contract. But
the hook is the only *aggregate* surface, and it is now inconsistent
between two paths that mean the same thing. Recorded as Low.

**File:line.** `src/xstate_statemachine/interpreter.py:1136-1137` (the
loop-side hook that exists) vs. the call-site `_check_strict`-adjacent
`qsize()` guard in `send_threadsafe` (no hook).

---

## 5. Contract notes — observed, deliberately NOT counted as defects

1. **`maxIterations` is a per-external-event budget, not a lifetime one.**
   `q1c` proves both engines re-buy a full `maxIterations` on **every**
   external event (`GO` = 1 000 laps, then 1 001 laps per subsequent
   `POKE`, identical on sync and async). `q1b` shows one external event
   per 100 ms is enough to keep an `always` cycle running indefinitely.
   This is the documented `#103/#151` rule working as specified — but the
   catalogue must not read `maxIterations: 1000` as "this machine can
   never burn more than 1 000 laps". It is "…per event". **Adoption-gate
   item:** any catalogue machine with a self-generated cycle needs a
   guard that terminates the cycle, not just a budget.

2. **Sync `send()` returns `None`, so the 4-way semantics matrix is
   discriminated differently per engine.** Async: via
   `(receipt.changed, receipt.denied, receipt.error)`. Sync: via a raised
   exception (guard crash) plus `on_unhandled_event` /
   `on_guard_error` hooks. A cross-engine abstraction must not read
   `Receipt` fields on the sync engine.

3. **`__slots__` on `Interpreter` does not seal the instance.**
   `has___dict__: true`; arbitrary attributes are accepted and the private
   budget counters (`_raise_depth`, `_chain_tripped`,
   `_settle_iterations`, `_threadsafe_self_sends_in_flight`) are writable
   from outside. PR #165/#176 introduced `__slots__` for layout/perf, not
   as a security boundary, and the docs do not claim otherwise.

4. **`_raise_depth` is not reset at quiescence after an
   `internal=True` threadsafe burst** (`q6b`: 100 after 50 pairs). It
   clears on the next external event, and a genuine cycle entered through
   that leftover depth still receives its **full** budget (measured:
   bursts of 0 / 50 / 90 pairs all yield 200/200 laps). Cosmetic.

5. **`send("")` is accepted with `error=None`** — unchanged from round 6,
   registered off this track.

6. **The `q4` "20 engine trip disagreements" are a probe artefact**, not a
   finding: the fuzz sampled `last_error` after an external `TICK` had
   already begun a new macrostep on the async engine. `q4b` (parity at
   rest, 6/6) and `q4c` (trip evidence survives an external event on both
   engines) disprove them. Recorded here so the raw `q4` JSON is not
   misread.

---

## 6. Coverage — what was NOT covered this run

- **Free-threaded (no-GIL) build.** `h1_free_threading.py` re-ran on the
  GIL build only; no 3.13t/3.14t interpreter is installed on this host.
  Every finding here is GIL-build evidence.
- **The full 12-minute soak.** Reduced to 300 s (`n9`, unchanged script,
  PASS) + 100 s × 200 machines (`q7`, new shapes). A 12-minute run could
  surface slow leaks neither window sees; RSS was flat-to-mildly-growing
  (40 → 61 MB over 100 s with 200 machines and 213 800 events) and task
  count returned to baseline, so no leak is *indicated*.
- **`restore + resume` trace parity** as an independent property. `q2`
  restores 750 hook-taken blobs and probes them with one event, and
  `n1`/`p3` cover quiescent-point persistence, but a full
  "run N events → snapshot → restore → run M more → compare traces"
  property was not written. Recommended for the next round.
- **Deferred-replay and `after`-timer callback as *named* snapshot
  points.** `q2` machines carry an `after: 60` and `onUnhandled: "defer"`
  and were driven through both, but the harness attributes snapshots by
  plugin hook, not by "inside the replay". A dedicated probe would
  tighten D7-concurrency-2's boundary.
- **Multi-process / multi-loop interpreters.** Single process, single
  loop throughout (plus worker threads and the service executor).
- **`done-callback double-fire`** was tested only indirectly, via the
  in-flight counter returning to 0 (`q3` B, `q6b`). No probe counts the
  callback invocations directly.

---

## 7. Verdict

**The round-6 concurrency work landed.** The one open prior defect is
FIXED and independently re-confirmed; no prior clean result regressed;
the headline claim — every self-generated cycle is bounded on
`Interpreter` — survived a 500-config × 2-engine fuzz with **zero**
livelocks, a 300 s chaos soak, and a 100 s / 200-machine / 213 800-event
shape soak that stayed at ~1 CPU-second per wall-second with zero torn
snapshots and zero task leaks. Determinism is exact across 50 runs, both
engines, and five hash seeds. The perf PRs' shared sentinels do not
alias.

**One finding blocks adoption of one shape.** `D7-concurrency-1` is a
real, reproducible liveness failure: a machine that re-arms an `invoke`
from its own `onDone` accepts events for ever and processes none once
inbound traffic exists, while `status` reads `"running"`. It is invisible
to every health surface except `queue_depth`. It was not caught earlier
because it does not reproduce on a single idle machine — it needs the
inbox to be non-empty at the end of a macrostep.

`D7-concurrency-2` (Medium) and `D7-concurrency-3` (Low) are
observability and parity gaps. Neither loses or corrupts data: the torn
blob is rejected at restore by #143, and the unhooked refusal still
raises at its call site.

**Recommendation for this track: READY, conditional on
D7-concurrency-1.** Concretely, before the catalogue adopts:

1. **Fix or forbid the self-re-arming `invoke` shape.** Either the
   settle budget must not be fully re-bought while the inbox is
   non-empty, or `docs/plan/28-statechart-catalogue.md` must exclude
   `onDone → always → back into the same invoke` and the adoption gate
   must assert it.
2. **Add `queue_depth` to whatever health surface the integration
   exposes.** It is the only signal that catches D7-concurrency-1.
3. Treat `maxIterations` as per-event (contract note 1) in every
   catalogue machine's budget calculation.

D7-concurrency-2 and -3 should be filed but need not gate.
