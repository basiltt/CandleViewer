# Battle test (round 8) — CONCURRENCY, BACKPRESSURE & RESOURCE LIMITS

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`6db65d8`** (merge of #191, "0.8.1 round-7 fixes": #179–#190 plus
reopened #167/#168/#175/#157). `__version__` still reads `0.8.0`; the
`[Unreleased]` CHANGELOG block targets 0.8.1. **Keyed on the commit.**

**Date:** 2026-09-21. **OS:** Windows 11 Pro 10.0.26200.
**Interpreter:** `.venv-main/Scripts/python` — CPython **3.13.7** (GIL
build), env `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Predecessor:** `battle-221ce7c/concurrency.md` (`D7-concurrency-1/2/3`).
Round-7 register: `43-r7-findings-register.md`.
**Scripts:** `battle-6db65d8/concurrency/*.py`; raw results in the sibling
`*.json`. Prior scripts were copied forward unmodified and re-run; the new
attacks are the `r*` files and share `common2.py`.

---

## 0. Bottom line

The round-7 fixes are **real on the `async def` lane and largely absent on
the plain `def` lane.** #179 rerouted every completion through one charged
lane and that worked: the coroutine lane, which was structurally blind in
round 6 and untested in round 7, is now the *healthy* one. It passed an
80 s / 200-machine soak with 12 350 external priority events, **0 dropped**,
**0 wedged**, **0 torn snapshots**, **0 task leaks**, CPU 1.01 s/wall s.

**The `def` lane did not move.** `D7-concurrency-1` (invoke cycle never
drains its inbox) is **STILL-PRESENT and now lane-specific**, and the root
cause turns out to be more general than round 7 diagnosed: a plain `def`
service blocks the run loop at `interpreter.py:1577`, so the machine
cannot process *any* event — not even the one that would exit the invoking
state — until the service returns. #181's `children_timeout` is a **no-op**
on the same lane for the same reason.

**Two NEW defects are engine-wide**, not lane-specific: an unbounded
`send(priority=True)` self-loop that livelocks hard enough to starve the
event loop, and `D7-concurrency-3` unchanged but measured **30× worse**.

| ID | Sev | One line |
|----|-----|----------|
| **D8-concurrency-1** | **Blocker** | A `send(priority=True)` issued from an action is never charged to the chain budget: unbounded self-feeding loop, `maxIterations` inert, `stop()` never returns, **no hook fires**, and the spin starves the event loop so an in-process watchdog cannot fire either. Both service kinds. |
| **D8-concurrency-2** | **High** | A plain `def` service **blocks the run loop** for its full duration (`interpreter.py:1577`, unbounded `await` before `_next_event()`). This is the true root cause of `D7-concurrency-1`, which is STILL-PRESENT on this lane only: 10/10 machines unresponsive, backlog 16 398. |
| **D8-concurrency-3** | **High** | `start(children_timeout=)` (#181) is a **no-op** when a child's entry action is a plain `def`: measured **15× and 75× over** the bound, no WARNING logged. Cost is N children × duration, serialized. |
| **D8-concurrency-4** | **Medium** | `get_persisted_snapshot()` from `on_interpreter_start` returns a blob with `status:"running"` and an **empty** configuration — 600/600 calls, **both engines**, both service kinds. #182 armed the flag for the descent but this hook fires outside that window. |
| **D8-concurrency-5** | **Low** | `D7-concurrency-3` unchanged and worse: call-site `QueueOverflowError` refusals fire **no** `on_event_dropped`. 85 256 of 85 511 refusals (**99.7 %**) invisible, vs ~50 % in round 7. |

**Verdict: NOT READY on the plain-`def` service lane; READY on the
`async def` lane conditional on D8-concurrency-1.** See §7.

---

## 1. Method and reductions

Every prior script in `battle-221ce7c/concurrency/` was copied into
`battle-6db65d8/concurrency/` **unmodified** and re-run. Per the brief,
every service-related probe was **additionally** re-run with `async def`
services — the lane #179 rewired and the one round 7 never exercised. That
is what `common2.make_service(kind)` exists for; every new `r*` probe is
parametrised over both spellings. Library source was never modified.

### 1.1 Reductions (stated as required)

| Item | Brief | Run | Why |
|------|-------|-----|-----|
| Soak (`r12`) | 12 min | **80 s**, 200 machines | 120 s per-script bound, 20 min whole-task bound. Shape mix, async services, priority producer and chaos-snapshot invariants all unreduced. **PASS**. |
| Livelock fuzz (`r8`) | ≥500 configs | **510** (3 shards × 170, distinct seeds) | Each shard fits the 120 s script bound; the union is the ≥500 the brief asks for. Both service kinds × both engines, unreduced. |
| Fuzz watchdog | 30 s | **3 s** + a 0.05 s settle | 510 configs × 2 kinds × 2 engines × 30 s cannot fit. Every livelock in this family hangs *indefinitely* (D8-concurrency-1 survives a 20 s **process** watchdog), so 3 s discriminates identically. |
| `priority_self_send` shape | in the fuzz corpus | **excluded from `r8`, carried by `r8b`** | It starves the event loop so completely that an in-process `asyncio.wait_for` never fires; left in, it consumed the entire fuzz budget with no result. `r8b` measures it under a **process-level** watchdog instead, which is the stronger evidence. Recorded, not hidden. |
| Hook-snapshot property (`r3`) | ≥300 machines | **300** | Unreduced. Parallel + nested + invoked children, both engines, both kinds. |
| `_chain_owed` probe (`r2`) | 100 concurrent | **100** | Unreduced. |
| External priority rate (`r5`) | 10 000/s | **target 10 000/s, achieved 1 937 (`def`) / 966 (`async def`)** | Host-limited by `send_threadsafe` cost from one producer thread, not by a probe reduction. The invariant (0 shed as `chain_budget`) is rate-independent and held. |
| `q4b` 1000-lap rows | — | window widened 0.4 s → 3.0 s | Not a reduction: see §2.2, a probe artefact. |

### 1.2 Scripts whose exit code is not a verdict (recorded)

- **`d3_snapshot_in_window.py` exits 1** with an uncaught
  `SnapshotMidStepError` — unchanged from round 7 and still the **fix**
  (#169/#142) landing, not a failure. Left unmodified so the traceback is
  the evidence.
- **`n5_fuzz_snapshot_events.py` exits 1** on the same single known
  sub-case: `send("")` accepted with `error=None`. Byte-identical to
  rounds 6 and 7 — pre-existing, registered off this track.
- **`q1`/`q1b`/`q1c` exit 1 by construction** — they *assert* the
  per-external-event budget re-buy, which §5 note 1 records as a documented
  contract, not a defect. Their dispositions are unchanged from round 7.
- **`q6_semantics_security.py` / `q6b` exit 1**; both JSON payloads are
  **byte-identical** to round 7 (verified by `diff`), i.e. the recorded
  contract notes 3 and 4, not regressions.

### 1.3 Commands

```bash
PY="_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
cd docs/research/xstate/battle-6db65d8/concurrency

# prior repros (36, batched exactly as round 7 ran them)
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
         p5_fuzz p6_determinism_surface \
         q1_chain_budget_external q1b_minimal_budget_reset \
         q1c_engine_parity_amplification q2b_minimal_action_hook_torn \
         q3_pool_counter_hooks q4b_minimal_trip_observability_parity \
         q4c_external_event_erases_trip q5_determinism_sentinel q5b_hashseed_sweep \
         q6_semantics_security q6b_internal_threadsafe_depth_leak \
         q7b_minimal_invoke_cycle_unresponsive; do timeout 115 $PY $f.py; done
$PY q2_hook_snapshot_property.py --n=300
$PY q4_livelock_fuzz.py --n=500 --wd=4

# new attacks (both service kinds throughout)
$PY r1_d7_1_both_service_kinds.py          # D7-1 on def AND async def
$PY r2_chain_owed_never_completing.py      # 100 never-completing services
$PY r2b.py ; $PY r2c_def_service_blocks_loop.py     # isolation -> D8-2
$PY r3_hook_snapshot_property_both_kinds.py --n=300
$PY r3b_on_start_torn_minimal.py           # -> D8-4
$PY r4_snapshot_readside_guards.py         # #185 / #186
$PY r4b_186_minimal.py ; $PY r4c_186_state_ids_silently_loses.py
$PY r5_external_priority_under_chain.py    # #180 at 10k/s
$PY r6_children_timeout_50_slow.py         # #181, 50 slow children
$PY r6b_children_timeout_def_noop.py       # -> D8-3
$PY r7_engine_marker_forgery.py            # security: forge the marker
for i in 1 2 3; do $PY r8_livelock_fuzz_both_kinds.py \
    --n=170 --wd=3 --settle=0.05 --seed=$((7000+i)) --tag=_s$i; done
$PY r8b_priority_self_send_livelock.py     # -> D8-1
$PY r9_observability_matrix.py --only=core
$PY r9_observability_matrix.py --only=qf   # -> D8-5
$PY r10_determinism_and_hashseed.py --runs=50
$PY r11_semantics_strict_wildcard.py
$PY r12_soak_async_services.py --seconds=80 --n=200
```

---

## 2. Prior defects - FIXED / STILL-PRESENT / CHANGED

| Prior ID | Sev (r7) | Probe re-run | Verdict @ `6db65d8` |
|----------|----------|--------------|---------------------|
| **D7-concurrency-1** - self-re-arming `invoke` cycle never drains its inbox | High | `q7b`, `r1` (both kinds) | **STILL-PRESENT on `def`, FIXED on `async def`** - and re-rooted, see D8-concurrency-2 |
| **D7-concurrency-2** - torn blob from `on_action_execute` on the async engine | Medium | `q2b`, `r3` (300 machines, both engines, both kinds) | **FIXED** (#187) - 0 torn from any action hook in 600 returned blobs; superseded by a *different* hook, D8-concurrency-4 |
| **D7-concurrency-3** - call-site `QueueOverflowError` fires no hook | Low | `q3` C, `r9 --only=qf` | **STILL-PRESENT, worse** -> re-filed as D8-concurrency-5 |

**Score: 1 FIXED, 1 STILL-PRESENT (lane-split), 1 STILL-PRESENT (worse).**

### 2.1 D7-concurrency-1 - the lane split is the headline

`r1_d7_1_both_service_kinds.py` runs the exact round-7 storm (10 machines,
~6 s of `send_threadsafe` traffic, then a concurrent 5 s `send(wait=True)`
probe on every machine) **once per service spelling**:

```
shape               kind        sent    backlog  wedged  tripped   laps
always_cycle        def          2000        0     0       10    103010
invoke_pingpong     def         16800    16398    10        0     21230   <-- STILL
rollback_ondone     def         17600    17171    10        0     22555   <-- STILL
always_cycle        async def    1800        0     0       10     92810
invoke_pingpong     async def   18000        0     0        0      6540   <-- FIXED
rollback_ondone     async def   17200        0     0        0     22630   <-- FIXED
```

Same machine, same traffic, same engine: **only the spelling of the
service differs**, and it decides whether 17 000 events drain or pile up.
The `async def` rows drain to a backlog of **0**. That is #179 working.

**Round 7's mechanism was wrong.** It attributed the wedge to the
per-external-event budget reset at `interpreter.py:1646-1652`. But the
budget rule is *shared* by both spellings (SS5 note 1, `q1c`
`engines_agree: true`, unchanged this round) - and the `async def` lane
does not wedge. Isolation in `r2b`/`r2c` finds the real cause, filed as
**D8-concurrency-2**: the plain-`def` service blocks the run loop outright.

### 2.2 Prior clean results - re-confirmed

All 36 copied-forward scripts were re-run. Dispositions are unchanged
against round 7 for every one. `q6_semantics_security.json` and
`q6b_internal_threadsafe_depth_leak.json` are **byte-identical** to the
round-7 payloads (`diff` clean), i.e. contract notes 3 and 4 hold exactly.
`a1/a2/b1/b3`, `c1`, `d1/d2/d2b`, `d3b`, `d4` + `probe_d_*`, `e1/e2`,
`g1`, `h1/h2`, and the whole `n*`/`p*` block exit 0.

Two results moved and neither is a regression:

- **`q4b` reported 2 parity violations at `maxIterations: 1000`** -
  `async_laps` 406 vs `sync_laps` 1001, `async_trip_observable: false`.
  This is a **probe-window artefact**: `q4b` samples 0.4 s after `start()`
  and the async engine is slower per lap on this host than in round 7
  (`q1c` wall time 0.27 s -> 0.52-0.86 s across three repeats, same
  `total_laps: 6005`). Re-running the identical probe with a 3.0 s window
  (`q4b_long.py`) gives **PASS, 0 violations**. Recorded, not counted.
- **`q1_chain_budget_external`** - `external_sent` 714 -> 4 701 and
  `seconds_to_trip` 0.75 -> 7.21 s, same dispositions. Throughput, not a
  disposition change.

### 2.3 Round-7 fixes independently re-verified

| Fix | Probe | Result |
|-----|-------|--------|
| **#179** one charged lane for every completion | `r1`, `r5`, `r12`, `r8` | **HOLDS on the coroutine lane** - the shapes that wedged in round 7 drain to backlog 0, and `def`/`async def` cycles trip at the *same* lap count (`r8c`, 20 cells, exact parity) |
| **#180** external priority sends never charged | `r5` (10 k/s target, both kinds) | **HOLDS** - `external_dropped_as_chain_budget: 0` on both; `async def`: 3 863 sent, **3 863 applied**, 0 residual. But the *converse* fails -> **D8-concurrency-1** |
| **#181** `start(children_timeout=)` | `r6` (50 slow children), `r6b` | **HOLDS on `async def` entry actions** (0.213 s vs a 0.2 s bound, WARNING logged); **no-op on `def`** -> **D8-concurrency-3** |
| **#182/#187** in-flight flag over `start()` + every action hook | `r3` (300 machines x 2 engines x 2 kinds) | **HOLDS** - 0 torn blobs from `on_action_execute`/`on_transition`/`on_event_received`; 2 323 refusals. One hook outside the window -> **D8-concurrency-4** |
| **#183** child mid-step refused instantly | `r9 --only=core` | **HOLDS** - `refused:SnapshotMidStepError` on both kinds |
| **#185** null/absent hash on a versioned blob is drift | `r4` | **HOLDS** - `v2_hash_null`, `v2_hash_absent`, `v2_hash_empty_str`, `v2_hash_wrong`, `v1_hash_null`, `v1_hash_absent` **all** `SnapshotDriftError`, both engines, both kinds. Only the genuinely unversioned v0 blob is bypassed, as documented |
| **#186** configuration vs state_ids must agree | `r4`, `r4b`, `r4c` | **PARTIAL** - see SS5 note 5 |
| **#188** sync per-step scopes cleared every step | `n8`, `p4` | **HOLDS**, unchanged |
| **#189** `onUnhandled: "error"` kill on the sender's receipt | `r9 --only=core`, `r11` | **HOLDS** - `Receipt.error is UnhandledEventError` on both kinds, `status` `error` |
| **#190** wildcard does not defeat strict | `r11` (12 cells) | **HOLDS** - `wildcard_only` + `UNDECLARED` -> `UnknownEventError` on both engines; `wildcard_only` + `KNOWN` also refused (strict is about *declaration*) |
| **#157** loop-side RAISE refusals observable | `r9 --only=qf` | **HOLDS** - 255 loop-side refusals, 255 hooks, exactly-once. Call-site half still unhooked -> **D8-concurrency-5** |

---

## 3. New attacks (`r*`) - what each one found

| # | Attack | Result |
|---|--------|--------|
| **r1** | D7-concurrency-1 re-run on **both** service spellings, 3 shapes x 10 machines x 2 kinds | **Lane split** (SS2.1). `def` wedges 10/10 with a 16-17 k backlog; `async def` drains to 0. |
| **r2** | `_chain_owed` under **100** concurrent never-completing services + state exit + `stop()` | **`async def`: PASS** - owed 1 while armed, **0** after the exit, the cycle still trips at exactly 50 laps, `stop` 0.00 s, 0 leftover tasks. **`def`: the machine never processes the `LEAVE` at all** - the D8-2 symptom. |
| **r2b/r2c** | Isolate the `def` wedge: loop starvation vs `chain_owed` | **`_chain_owed` is innocent** (0 on every path). `r2c` is decisive: a 2 s `def` service makes a probe sent 0.2 s after start time out at **1.0 s** and leaves the machine in the *invoking* state, at `service_pool_size` 1 **and** 4; the `async def` control answers in **0.001 s**. -> **D8-concurrency-2** |
| **r3** | Snapshot from every hook incl. initial descent + child entry, **300** random nested/parallel/child machines, 2 engines x 2 kinds | 600 returned blobs, **600 torn - all from `on_interpreter_start`**, and **0** from any other hook on either engine. 2 323 refusals. -> **D8-concurrency-4** |
| **r3b** | Minimal + the severity question: does the torn blob restore? | Deterministic, 3/3 cells torn (`status: running`, `state_ids: []`, `configuration: []`). **Restore is refused** with `SnapshotCorruptError: status is 'running' but the configuration is empty` - the #143 read-side guard holds, so this is observability/parity, not corruption. |
| **r4** | 17 snapshot mutations x 2 engines x 2 kinds + a 400-trial disagreement fuzz | **#185 fully holds** (6/6 hash mutations -> `SnapshotDriftError`). #186 partial: 3 mutations accepted (SS5 note 5). Fuzz: 17/400 accepted, all of them ancestor-supersets or true agreements. |
| **r4b** | #186 minimal, flat machine | **PASS**, 8/8 refused - a `configuration` that names a *different* leaf is `SnapshotCorruptError` on both engines, both kinds. |
| **r4c** | #186, the "silently lose" half | An **emptied** `state_ids` is accepted (configuration wins) and a **dropped** `configuration` is accepted (v0 fallback); a *rewritten* `state_ids` is refused. Narrow. SS5 note 5. |
| **r5** | External `send(priority=True)` at a 10 k/s target **during** a live invoke-driven chain, both kinds | **`external_dropped_as_chain_budget: 0` on both** - #180 holds. `async def`: 3 863 sent / **3 863 applied** / 0 residual / no drops at all. `def`: 7 747 sent, **61 applied, 7 686 stuck in the queue** - D8-2 in its purest form. |
| **r6** | `start(children_timeout=0.2)` with **50** slow (1 s) children | `async def` entry: **0.213 s**, WARNING logged, 50 registered, first send 0.003 s. `def` entry: **50.03 s** (= 50 x 1 s, serialized), no WARNING; `children_timeout=None` is identical. -> **D8-concurrency-3** |
| **r6b** | Minimal, 1 and 5 children, 3 s entry, bound 0.2 s | `async def`: 0.21 s / 0.20 s (bounded). `def`: **3.0 s (15x) and 15.0 s (75x)**, no WARNING. Perfectly linear in N. |
| **r7** | **Security:** 6 forgery routes for the engine-completion marker, + redaction + `__slots__` | **Every public route refused.** An `Event` subclass overriding `.system` -> the engine still says `False` (provenance, not the property); an arbitrary `_provenance` -> `False`; `dataclasses.replace` -> `TypeError`. Only `events._ENGINE_MARK` via the private module attribute works, which is not a public surface. No secret in `repr`/`str`. SS5 notes 3-4 unchanged. |
| **r8** | Livelock fuzz, **510 configs** x 2 kinds x 2 engines, 5 shapes | **0 timeouts, 0 unobservable trips.** Every trip carried `RunawayChainError` in `last_error` or an `on_event_dropped(chain_budget)`. |
| **r8b** | The 6th shape, `priority_self_send`, under a **process** watchdog | **LIVELOCK on both service kinds** - no trip, no hook, `stop()` never returns, and the spin starves the loop so an in-process `wait_for` cannot fire. The plain-`send` control **trips at 27 laps** with `chain_budget: 1`. -> **D8-concurrency-1** |
| **r8c** | Trip lap-count parity, 5 shapes x 2 budgets x 2 kinds, at rest (1.5 s settle) | `def` and `async def` are **identical in all 20 cells** - #179's parity claim holds *between service kinds*. Three invoke-driven cells differ from the **sync** engine by 2-3 laps at `maxIterations: 25` only. SS5 note 6. |
| **r9 core** | Observability matrix: chain_budget (async lane), child=True refusal, #189 kill - both kinds | **PASS 6/6.** `chain_budget` trip observable on both kinds; child snapshot refused with `SnapshotMidStepError`; `Receipt.error is UnhandledEventError`, `status` `error`. |
| **r9 qf** | `queue_full` exactly-once + call-site, 6 threads x 1 s, depth-4 inbox | Loop-side **exactly-once** (255/255). Call-site: **85 256 refusals, 0 hooks**. -> **D8-concurrency-5** |
| **r10** | 50x identical traces, 2 engines x 2 kinds, incl. the trip lap count; hash-seed sweep | **PASS.** 1 distinct trace in all four cells; async/sync lap counts **both 31**, both tripped; `distinct_outcomes_across_seeds: 1` over `PYTHONHASHSEED` in {0,1,7,12345,99991}. |
| **r11** | 5-way receipt matrix + strict/wildcard matrix, both kinds | **PASS.** Async gives **5/5 distinct** signatures (`OK`/`DENIED`/`CRASH`/`UNKNOWN`/`ERROR_KILL`), identical on both service kinds - #170 + #189 together. Strict/wildcard 12/12 correct. Sync gives 2/5 (contract note 2, unchanged). |
| **r12** | **Soak:** 200 machines, `async def` services, rollback+onDone / always->invoke / parallel shapes, external priority producer, chaos snapshot at quiescence | **PASS.** 12 350 external events, **0 dropped**, 0 machines wedged, **0 torn** of 3 080 snapshots, 0 refused, CPU **1.01 s/wall s**, RSS **34 -> 34 MB**, 0 leftover tasks, clean stop. |

---

## 4. Defect register - `D8-concurrency-n`

### D8-concurrency-1 - `send(priority=True)` from an action is never charged to the chain budget: unbounded, silent livelock on both engines and both service kinds

**Severity: Blocker.** Unbounded self-feeding loop with **no** observable
signal and no recovery: `maxIterations` is inert, `last_error` stays
`None`, no `on_event_dropped` fires, `stop()` never returns, and the spin
starves the event loop hard enough that an in-process `asyncio.wait_for`
watchdog cannot fire either. This is the failure `maxIterations` exists to
prevent, on the one lane that bypasses it.

**Repro:** `r8b_priority_self_send_livelock.py` (deterministic; 2/2
defect cells livelock, 2/2 control cells bounded, every run). Discovered by
the `r8` fuzz, where this shape consumed the entire budget with no result.

```
self_send  kind        outcome    laps  trip_observable  last_error            stop
plain      def         bounded      27       True        RunawayChainError     ok     <- control
plain      async def   bounded      27       True        RunawayChainError     ok     <- control
prio       def         LIVELOCK      -       False       -                     never  <- DEFECT
prio       async def   LIVELOCK      -       False       -                     never  <- DEFECT
```

The two rows differ by **one keyword argument**. The machine is identical
(`maxIterations: 25`, two states whose entry action sends the event that
flips to the other); `send("P")` trips at 27 laps and sheds one event as
`chain_budget`, while `send("P", priority=True)` never stops.

**Mechanism.** #180 states the rule correctly: *"Accounting is by who
issued it: only engine completions and self-raised events count."* The
implementation decides "engine vs external" with the `engine_completion`
keyword on `_deliver_priority` (`interpreter.py:2342-2375`), which is
`False` for **every** `send(priority=True)` - including one the machine
issued from its own action, which is self-raised by #180's own definition.
The non-priority path does make that distinction: at
`interpreter.py:898-908` a send issued from an action is detected by
`_issued_from_own_action()`, routed to the internal queue, and
`_raise_depth` is incremented. `priority=True` never reaches that branch.

So #180 fixed a false positive (external traffic wrongly charged) and
opened a false negative (self-traffic wrongly exempted). The `q6b`
observation that `_raise_depth` is writable/leaky was recorded in round 7
as cosmetic; this is the same accounting surface failing in the direction
that matters.

**File:line.** `src/xstate_statemachine/interpreter.py:2342-2375`
(`_deliver_priority`, `engine_completion=False` for all caller sends) vs
`:898-908` (`_issued_from_own_action()` on the non-priority path), which is
the distinction the priority lane is missing.

**Operational impact.** One `send(priority=True)` in an entry action - the
idiom for "this is urgent, jump the queue" - turns the process into a
busy-spin that no health check, hook, log line or timeout can see. The
whole event loop is starved, so *every other machine in the process* stops
too. There is no in-process mitigation: only an external supervisor killing
the process recovers it.

---

### D8-concurrency-2 - a plain `def` service blocks the run loop for its entire duration, so the machine processes no events at all while it runs

**Severity: High.** Liveness failure, silent, and the true root cause of
`D7-concurrency-1` (which round 7 mis-attributed to the budget reset).

**Repro:** `r2c_def_service_blocks_loop.py` (deterministic; 2/2 `def`
cells fail, 2/2 `async def` cells pass, every run).

```
kind        pool  start_s  probe_answered_within_1s  probe_latency_s  state_after_probe
async def     1    0.000            True                  0.001        r2c.other
async def     4    0.000            True                  0.001        r2c.other
def           1    0.009            False                 1.001        r2c.hold    <- DEFECT
def           4    0.000            False                 1.000        r2c.hold    <- DEFECT
```

A 2 s service is armed on entry. A `PING` that targets a *different state*
is sent 0.2 s later and awaited for 1.0 s. On the coroutine lane it is
applied in 1 ms and the machine leaves `hold`. On the plain lane it is not
processed at all - the machine is still in `hold` when the deadline
expires. `service_pool_size` is irrelevant, which rules out executor
starvation: the block is on the loop, not on the worker pool.

**Mechanism.** `interpreter.py:1577`, at the top of the run loop:

```python
if self._inline_service_futures:
    await self._await_inline_services()   # <-- before _next_event()
event, from_inbox = await self._next_event()
```

`_await_inline_services` (`:2713-2735`) gathers every inline service future
to completion, and it sits **before** the inbox is read. The comment at
`:1569-1576` explains the intent - #116 requires a plain service's
`done.invoke` to land ahead of any event already queued - and asserts *"The
loop stays live: this is an await, not a block."* The loop task indeed does
not block the OS thread, but it cannot reach `_next_event()`, which is the
only thing that ever drains the inbox. For the machine the two are the
same. The `async def` path has no equivalent gate: its completion arrives
via `_publish_completion` on a later turn while the loop keeps reading
events.

Consequences chain from there:

- **`D7-concurrency-1`** (`r1`): 10/10 `def` machines unresponsive with a
  16 398-event backlog; the identical `async def` machines drain to 0.
- **`r5`**: at a 10 k/s external priority rate the `def` machine applies
  **61 of 7 747** events - the other 7 686 sit in the queue. `async def`
  applies 3 863 of 3 863.
- **`r2`**: with a never-completing `def` service the machine cannot even
  process the event that would *exit* the invoking state and cancel it, so
  the state is unescapable from inside. (`stop()` still works, and
  `_chain_owed` is correctly 0 throughout - the debt accounting is not
  implicated.)

**File:line.** `src/xstate_statemachine/interpreter.py:1577` (the
unconditional `await` before `_next_event()`) and `:2713-2735`
(`_await_inline_services`). The tension with the #116 ordering guarantee is
inherent: the two cannot both hold unconditionally.

**Operational impact.** Any catalogue machine invoking a plain `def`
service - the spelling the type hints accept without ceremony, and the one
every round-6/7 pin was written in - stops answering for the service's
whole duration. `status` reads `"running"`, `last_error` is `None`, no hook
fires; only `queue_depth` moves. With a 200 ms broker call this is a 200 ms
stall per invoke; under sustained traffic the arrival rate exceeds the
drain rate permanently and the queue diverges.

---

### D8-concurrency-3 - `start(children_timeout=)` is a no-op when a child's entry action is a plain `def`

**Severity: High.** The bound #181 introduced does not exist on this lane,
and the overrun is N children x duration, serialized - so it grows without
limit with the size of the initial configuration.

**Repro:** `r6b_children_timeout_def_noop.py` (deterministic, 2/2 `def`
cells fail every run). At scale: `r6_children_timeout_50_slow.py`.

```
entry_kind  children  entry_s  children_timeout  start_s   bounded  overrun  warning
async def       1       3.0          0.2           0.21     True      1.0x    True
async def       5       3.0          0.2           0.20     True      1.0x    True
def             1       3.0          0.2           3.00     False    15.0x    False   <- DEFECT
def             5       3.0          0.2          15.00     False    75.0x    False   <- DEFECT

r6, 50 children x 1 s entry, children_timeout=0.2:
  async def entry -> start 0.213 s, WARNING logged, 50 registered
  def       entry -> start 50.034 s, NO warning; identical with timeout=None
```

**Mechanism.** #181 implements the bound as
`asyncio.wait_for(self._await_actor_bringups(...), timeout)` at
`interpreter.py:601`. `wait_for` can only pre-empt a task at an `await`
point. A bring-up awaits `child_interpreter.start()`
(`interpreter.py:2973`), which runs the child's entry actions; a plain
`def` entry action executes **on the loop thread** inside that call and
yields nothing, so the timeout has no point at which to fire. The children
are also brought up one after another, hence the exact N x duration scaling
(1 -> 3.0 s, 5 -> 15.0 s, 50 -> 50.0 s at 1 s each).

The WARNING is emitted on the same timeout path, so a `def` entry action
suppresses the observability too: `start()` takes 250x its bound and logs
nothing.

**File:line.** `src/xstate_statemachine/interpreter.py:601`
(`await self._await_actor_bringups(timeout=children_timeout)`),
`:2737-2775` (`_await_actor_bringups`), `:2973`
(`await child_interpreter.start()`). Same family as D8-concurrency-2:
`await` on user code that never yields.

**Operational impact.** `DEFAULT_CHILDREN_TIMEOUT = 2.0` reads as a
guarantee that bring-up is bounded. On this lane it is decorative. A
supervisor that invokes 50 children whose entry actions each do 1 s of
synchronous work blocks for 50 s at startup with no log line - and if the
caller wraps `start()` in its own timeout, it gets a cancellation mid
bring-up instead.

---

### D8-concurrency-4 - `get_persisted_snapshot()` from `on_interpreter_start` returns a blob with `status: "running"` and an empty configuration, on both engines

**Severity: Medium.** Observability; the blob is **refused on restore**
(#143), so it cannot corrupt state - but a monitoring plugin cannot tell
that from a healthy blob without knowing to look.

**Repro:** `r3b_on_start_torn_minimal.py` (deterministic, 3/3 cells).
Property evidence: `r3_hook_snapshot_property_both_kinds.py --n=300` -
**600 of 600** `on_interpreter_start` returns are torn, and 0 of the 1 356
returns from every other hook are.

```
engine  kind       disposition  status    state_ids  configuration  healthy   restore
async   def         returned    running      []          []        [r3b.a]  refused:SnapshotCorruptError
async   async def   returned    running      []          []        [r3b.a]  refused:SnapshotCorruptError
sync    def         returned    running      []          []        [r3b.b]  refused:SnapshotCorruptError

r3 dispositions across 300 machines x 2 engines x 2 kinds:
  async:*:on_interpreter_start   returned 300   torn 300
  sync:*:on_interpreter_start    returned 300   torn 300
  async/sync:*:on_transition     returned 600   torn   0
  async:*:on_event_received      returned 156   torn   0
  async/sync:*:on_action_execute refused 2323   torn   0   <- #187 working
```

**Mechanism.** #182 sets `_processing` for the whole `start()` descent, so
a snapshot taken from an initial *entry action* is correctly refused - `r3`
confirms 2 323 such refusals and **zero** torn action-hook blobs, which is
`D7-concurrency-2` genuinely fixed. `on_interpreter_start` fires
**outside** that window: `status` has already been flipped to `"running"`
but `_active_state_nodes` is still empty, so the write-side #102 leafless
check does not apply and the blob is produced.

The write side and the read side now disagree: `get_persisted_snapshot()`
emits a blob that `from_snapshot()` refuses as malformed
(`SnapshotCorruptError: status is 'running' but the configuration is
empty`). That inconsistency is the defect.

Note this is **both engines**, unlike D7-concurrency-2 which was an async
parity gap - so a cross-engine abstraction cannot use the sync engine as
the reference here.

**File:line.** `src/xstate_statemachine/base_interpreter.py:1391` (the
`get_persisted_snapshot` refusal site, in-flight test) and `:1443-1456`
(the blob builder, which has no "configuration is empty" guard on the write
side) vs `:1747-1756` (the read-side guard that rejects the same blob).

**Operational impact.** A plugin that snapshots on start - a reasonable
"record the initial state" audit hook - persists a blob that is silently
unusable. It fails at restore, not at write, so the failure surfaces during
recovery.

---

### D8-concurrency-5 - call-site `QueueOverflowError` refusals still fire no `on_event_dropped`; the hook now under-counts the shed rate by 99.7 %

**Severity: Low.** Observability only - the call site raises, so no caller
loses an event silently. Re-filed from `D7-concurrency-3`: unchanged in
mechanism, an order of magnitude worse in measurement.

**Repro:** `r9_observability_matrix.py --only=qf` (6 threads, 1 s, depth-4
inbox, `OverflowPolicy.RAISE`).

```
                       round 7        round 8
callsite_refusals        6 021         85 256     <- raised, NO hook
loopside_refusals        6 066            255     <- error on the future, hooked
total_refusals          12 087         85 511
queue_full_hooks         6 066            255     <- exactly-once on the loop side
hook coverage            50.2 %           0.3 %
```

**Mechanism.** Unchanged from round 7: #157 added the hook to the
**loop-side** refusal path (`interpreter.py:1136-1137`); the optimistic
call-site `qsize()` check in `send_threadsafe` raises before anything is
queued and never reaches it. The exactly-once property of the loop-side
hook is **confirmed** (255 refusals -> 255 hooks).

**What changed is the ratio.** The call-site check now wins the race far
more often on this build (the loop turns less often between refusals), so
the fraction of refusals the hook can see collapsed from ~50 % to **0.3 %**.
An operator aggregating `on_event_dropped(queue_full)` as the backpressure
metric under-reports by **334x**.

**File:line.** `src/xstate_statemachine/interpreter.py:1136-1137` (the
loop-side hook that exists) vs the call-site `qsize()` guard in
`send_threadsafe` (no hook).

**Counter-argument considered, unchanged from round 7.** A call-site
refusal raises into the caller, which *is* the documented #157 signal. The
hook remains the only aggregate surface, and it is now inconsistent between
two paths that mean the same thing. Still Low.

---

## 5. Contract notes - observed, deliberately NOT counted as defects

1. **`maxIterations` is a per-external-event budget, not a lifetime one.**
   `q1c` re-run: `GO` costs 1 000 laps, then every subsequent external
   event buys a fresh 1 001, `engines_agree: true`, `total_laps: 6005`
   identical to round 7. Unchanged documented behaviour (#103/#151). The
   catalogue must read `maxIterations: 1000` as "per event".
   **Adoption-gate item, carried forward unchanged.**

2. **Sync `send()` returns `None`,** so the 5-way semantics matrix is
   discriminated differently per engine: async via
   `(receipt.changed, receipt.denied, receipt.error)` - **5/5 distinct** in
   `r11`, on both service kinds - sync via a raised exception plus hooks
   (2/5 signatures). A cross-engine abstraction must not read `Receipt`
   fields on the sync engine. Unchanged from round 7.

3. **`__slots__` on `Interpreter` does not seal the instance.** `r7`
   re-confirms `has___dict__: true` and that `_chain_owed` (the new #179
   counter) is writable from outside, like `_raise_depth` before it. The
   perf PRs documented `__slots__` as a layout optimisation, not a security
   boundary. Recorded, unchanged.

4. **`_raise_depth` is not reset at quiescence after an `internal=True`
   threadsafe burst.** `q6b` payload byte-identical to round 7; `r7` F3
   confirms `internal=True` is still accepted from outside and bumps the
   counter. Not exploitable for budget evasion (round 7 measured full
   budgets at bursts 0/50/90). Cosmetic, unchanged.

5. **#186 is enforced in one direction only.** A `configuration` that names
   a *different* legal leaf is refused (`r4b`: 8/8 `SnapshotCorruptError`;
   `r4`: `config_rewritten_other_leaf`, `config_subset_one_region`,
   `config_emptied`, `config_bogus_id` all refused, both engines, both
   kinds). But the two fields are never **compared**:
   `base_interpreter.py:1722` is still
   `snapshot.get("configuration") or snapshot["state_ids"]`. What refuses
   the tampering above is the older #143 *legality* check at `:1747-1756`,
   which only asks whether the winning list has one leaf per region. So
   three cases are still accepted (`r4c`):
   an **emptied** `state_ids` (configuration wins silently), a **rewritten**
   `state_ids` that is itself legal, and a **dropped** `configuration` (the
   documented v0 fallback). Not counted as a defect: no accepted case
   restored the machine to a wrong configuration in 400 fuzz trials plus 16
   targeted mutations - the machine always lands where `configuration`
   says, which is the field the blob is built from. The gap is that a
   *reader* of `state_ids` and the restored machine can disagree with no
   error. **Worth a follow-up issue; does not gate.**

6. **Trip lap counts differ from the SYNC engine by 2-3 laps for
   invoke-driven cycles at `maxIterations: 25`.** `r8c`, at full rest
   (1.5 s settle), deterministic across repeats:

   ```
   shape                 it   async  sync   delta
   invoke_cycle          25     25     27    -2
   nested_invoke_cycle   25     25     27    -2
   rollback_ondone       25     37     40    -3
   (every shape at it=50, and always_cycle / sendto_self_loop
    at every budget: exact parity)
   ```

   Not counted for three reasons: `def` and `async def` are **identical in
   all 20 cells**, so #179's actual claim ("both service kinds trip at the
   same lap count") holds; both engines **do** trip and both are observable;
   and the async engine trips *earlier*, i.e. conservatively. The residual
   is an off-by-a-microstep in where the invoke completion lands relative to
   the budget test, visible only at small odd budgets. Recorded so the 60
   `r8` lap mismatches are not misread as non-determinism - `r10` proves
   determinism separately (1 distinct trace per cell over 50 runs).

7. **The engine-completion marker is reachable as
   `xstate_statemachine.events._ENGINE_MARK`** and, once obtained, forges
   `is_system_event() == True` for an arbitrary `Event` (`r7` F5). Every
   *public* route is closed: an `Event` subclass overriding `.system` does
   not fool `is_system_event` (F1), an arbitrary `_provenance` value does
   not (F1b), and `dataclasses.replace` raises `TypeError` (F2). A private
   module attribute is not a security boundary in Python and the library
   does not claim it is. Recorded, not counted. `copy`/`deepcopy`/`pickle`
   of a *genuine* engine event correctly preserve the mark, which is the
   intended `__reduce__` behaviour.

8. **`send("")` is accepted with `error=None`** - `n5` unchanged from
   rounds 6 and 7, registered off this track.

---

## 6. Coverage - what was NOT covered this run

- **Free-threaded (no-GIL) build.** `h1_free_threading.py` re-ran on the
  GIL build only; no 3.13t/3.14t interpreter is installed on this host.
  Every finding here is GIL-build evidence. D8-concurrency-1 and -2 are
  loop-scheduling failures and would be expected to reproduce, but that is
  inference, not measurement.
- **The full 12-minute soak.** Run at 80 s x 200 machines (`r12`, PASS, RSS
  flat 34 -> 34 MB). A 12-minute window could surface slow leaks this one
  cannot. Note the soak used `async def` services **by design** (the brief
  asked for it); a `def`-service soak was not run because
  D8-concurrency-2 makes the result a foregone conclusion - the machines do
  not drain. That is a deliberate omission, not an oversight.
- **D8-concurrency-1 at scale.** Measured on a single machine under a
  process watchdog. Its effect on a multi-machine process (loop starvation
  should stop every co-resident machine) is argued from the mechanism, not
  measured - a probe would have to survive its own starvation.
- **`restart_services=True` / `restart_timers=True` restore paths.** `r4`
  and `r3b` exercise the default static restore only. The dormant-invoke
  re-drive path is untested on this track.
- **`SimulatedClock` / `after`-timer interaction with D8-concurrency-2.**
  A `def` service blocking the loop must also delay due timers; #174
  measured timer lateness on the fixed tree but not against this root
  cause. Recommended next round.
- **Multi-process / multi-loop interpreters.** Single process, single loop
  throughout (plus worker threads and the service executor).
- **`priority_self_send` on the sync engine.** `SyncInterpreter` has no
  priority lane, so D8-concurrency-1 has no sync counterpart to compare
  against; the `def`/`async def` split in `r8b` is the parity axis that
  applies.

---

## 7. Verdict

**#179 and #180 did real work, and the evidence is the lane that was blind
before.** The `async def` service lane - untested in round 6, untested in
round 7, and the spelling the library's own docs recommend - is now the
healthy one. It carried a 200-machine soak with 12 350 external priority
events at **0 dropped**, 0 wedged, 0 torn snapshots of 3 080 taken, 0 task
leaks, and 1.01 CPU-seconds per wall second. `_chain_owed` settles to 0
under 100 never-completing coroutine services and does not poison the
budget afterwards. Determinism is exact across 50 runs, both engines, both
service kinds and five hash seeds. The 5-way receipt matrix is 5/5
distinct. #185 (hash drift) and #190 (wildcard vs strict) hold without
qualification.

**Three findings say the plain-`def` lane was not brought along**, and they
are one mechanism: the engine `await`s user code that never yields, on the
loop task, before the inbox is read. `D8-concurrency-2` is that at
`interpreter.py:1577` (the service), `D8-concurrency-3` is the same shape at
`:601`/`:2973` (a child's entry action). `D7-concurrency-1` is
STILL-PRESENT as a consequence, not as an independent defect - round 7's
diagnosis (the budget reset) was wrong, which matters because the budget
rule is shared by both lanes and the coroutine lane does not wedge.

**One finding is engine-wide and worse than anything on the prior
register.** `D8-concurrency-1`: `send(priority=True)` from an action is
self-generated work that the chain budget does not charge, so it spins for
ever with no trip, no hook, no `last_error`, no `stop()`, and it starves
the event loop so thoroughly that an in-process watchdog cannot fire. The
control - the same machine with `priority=False` - trips at 27 laps and
sheds one event observably. #180 corrected a false positive and introduced
the matching false negative.

**Recommendation for this track: NOT READY.** Concretely, before adoption:

1. **Fix D8-concurrency-1.** `_deliver_priority` must apply the same
   `_issued_from_own_action()` test the non-priority path applies at
   `interpreter.py:898-908`. Until then the adoption gate must assert that
   **no catalogue machine issues `send(priority=True)` from an action** -
   this is mechanically checkable and should be checked, because the
   failure mode is process-wide and silent.
2. **Fix or document D8-concurrency-2.** Either the inline-service await at
   `:1577` must not preclude draining the inbox, or the documentation must
   state plainly that **a plain `def` service makes the machine
   unresponsive for its duration** and the catalogue must mandate
   `async def` for every service that can block. Given `r12`, mandating
   `async def` is a sufficient and immediately available mitigation - but
   it must be a written, gated rule, because today the `def` spelling is
   accepted silently and its failure is invisible.
3. **Fix D8-concurrency-3**, or document that `children_timeout` bounds
   only coroutine entry actions. As written, `DEFAULT_CHILDREN_TIMEOUT = 2.0`
   is a guarantee the library does not keep.
4. **Add `queue_depth` to the health surface.** Carried forward from round
   7 and now more important: it remains the only signal that catches
   D8-concurrency-2, and `on_event_dropped` catches 0.3 % of backpressure
   (D8-concurrency-5).
5. Treat `maxIterations` as per-event (contract note 1) in every catalogue
   machine's budget calculation - unchanged from round 7.

`D8-concurrency-4` (Medium) and `D8-concurrency-5` (Low) are observability
gaps that should be filed but need not gate. Contract note 5 (#186 enforced
in one direction) is worth an issue.

**If the catalogue commits to `async def` services and no
`send(priority=True)` from actions, this track's evidence supports READY.**
Both conditions are mechanically checkable at build time, and the soak
shows the resulting configuration is sound. Neither is currently enforced
anywhere.
