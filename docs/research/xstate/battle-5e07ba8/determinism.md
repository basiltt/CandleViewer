# Battle-test track: **DETERMINISM & REPLAY** — `xstate-statemachine` @ `5e07ba8`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `5e07ba8` (merge of PR #101, `fix/round3-ride-alongs`). `CHANGELOG.md`
`[Unreleased] — targeting 0.8.1`; **`__version__` still reports `0.8.0`**, so
this build is identified **by commit**, never by version string.

**Date:** 2026-09-18 · **Python:** CPython 3.13.7 · **OS:** Windows 11 Pro 10.0.26200
**Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the adopting
project's repository. GitHub was read-only throughout.

**Why this track exists.** The adopting project must be able to replay recorded
market/exchange event streams and obtain byte-identical machine behaviour, and
its audit logs must be reproducible from the recorded stream alone. Anything
that makes two runs of the same input differ — or makes a recorded trace
unreproducible — is a defect on a path that handles real money, regardless of
whether the library documents it as "unspecified".

---

## 0. Bottom line

**Given a fixed event script and a `SimulatedClock`, the async engine and the
sync engine are each internally deterministic in state, context, transitions,
actions, plugin hooks and snapshot bytes — with exactly one exception, and it is
a real one: `Receipt.deferred` is nondeterministic run-to-run.** The remaining
findings are not run-to-run instability but two harder problems for a replay
pipeline:

1. **`Receipt.deferred` is nondeterministic** (D-determinism-1, **High**). It is
   the only field in the entire comparison surface that differs between two runs
   of one identical script on one engine. Root cause is an `id()`-keyed `Set`
   that leaks: `base_interpreter.py:465` / `:3335` add, but only a resolved
   receipt discards (`interpreter.py:1278-1279`, `sync_interpreter.py:512-513`),
   and a *replayed* deferred event never resolves a receipt. CPython address
   reuse then flips the flag on unrelated, fully-handled events. On the sync
   engine a three-line script produces **2 998 false positives in 3 000 cycles**
   (`d2c`). This is the same `id()`-keying defect class that `#75` fixed for
   receipts, reintroduced by `#84`.

2. **A pure asyncio-scheduling perturbation changes the OUTCOME, not just the
   timing** (D-determinism-2, **High**). With the event script, the machine and
   the simulated clock all held fixed, varying only how many `await sleep(0)`
   turns a service burns and how many turns the *producer* waits between two
   sends yields **11 distinct final contexts** across a 64-point grid
   (`d3c`) — from `20 filled / 0 aborted` to `0 filled / 20 aborted`. A replay
   harness that re-feeds a recorded script cannot reproduce the recorded run,
   because the deciding variable is not in the recording.

3. **The two engines are not replay-equivalent on the same script**
   (D-determinism-3, **High**). A plain *sync* `invoke` src completes inside the
   entering macrostep on `SyncInterpreter` but only after a loop yield on
   `Interpreter` (`sync_interpreter.py:1367-1375` vs `interpreter.py:1771`).
   On `10x (GO, CANCEL)` the sync engine records `ok=10, cancel=0`; the async
   engine records anything from `ok=0, cancel=10` to `ok=10, cancel=0` depending
   only on producer gap (`d8`). An audit trail replayed on the "other" engine
   is not the same trail.

4. **The sync engine emits one `on_transition` record the async engine never
   emits** (D-determinism-4, **Medium**): the synthetic
   `___xstate_statemachine_init___` transition, fired at
   `sync_interpreter.py:336-339` with no counterpart in `Interpreter.start()`.
   Every cross-engine hook trace we captured diverges at index 0 for this reason
   alone (`d7`).

5. **`from_snapshot()` cannot take a clock** (D-determinism-5, **Medium**):
   `base_interpreter.py:1103` has no `clock=` parameter and `:1189` constructs
   `cls(machine)`, so a restored interpreter always gets a `RealClock`. Virtual
   time cannot survive a restore, so a replay harness cannot checkpoint and
   resume — which is exactly what an audit pipeline does (`d9` R3).

6. **`send_threadsafe()` does not order against `send()`**
   (D-determinism-6, **Medium**). It does not enqueue; it schedules a coroutine
   on the loop (`interpreter.py:909-914`), so the ordering point is when the
   loop runs that coroutine, not the call site. With strictly alternating call
   sites, processed order equalled arrival order in **0 of 8 runs**, with **8
   distinct orders** (`d10b` case 2).

**What is clean and worth saying so.** The delivery-lane total order is fully
specified and **stable in all 13 cases across 15 repeats each** (§4). Parallel
region entry/exit order, guard evaluation order, invoke start order, actor
teardown order, snapshot `configuration`, snapshot `value` key order and
`structure_hash` are all **invariant under `PYTHONHASHSEED` 0–5** (§5). Single
inbox FIFO holds perfectly under 8 concurrent asyncio senders and under 8 OS
threads via `send_threadsafe` (2 400 events/run, 10 runs, 0 lost, 100 % FIFO).
Snapshot bytes are stable and round-trip losslessly on one engine (§6).

---

## 1. Method

### 1.1 The fixture

`determinism/dmachine.py` defines one machine and one event-script generator,
shared by every whole-system script in the track.

The machine (`oms`) is a **parallel root** with three regions, chosen to put
every delivery lane in the same trace:

| region | what it exercises |
|---|---|
| `trading` | `idle`/`pending`; `pending` has an `entry` `raise` (internal queue), an `invoke` of a *sync* callable service with `onDone`/`onError`, an `after: {50}` timer, and a `sendTo` action |
| `risk` | runs in lockstep on the same events, so parallel-region ordering is observable |
| `actors` | hosts a permanently-live invoked child machine under `systemId: "kid"`, the `sendTo` target |

Machine-level `onUnhandled: "defer"` is set, and the event pool contains one
name (`NOPE`) that no state declares, so the deferral buffer and its replay are
continuously exercised.

**Constraints that make the two engines comparable.** Every service is a plain
sync callable (the sync engine refuses `async def`); every delay is driven by
`SimulatedClock`, never wall clock; the script is generated from a seeded
`random.Random(20260918)`, so it is byte-identical in every process regardless
of `PYTHONHASHSEED`. Guard outcomes and service success/failure are functions of
`context` only — never of time, randomness or iteration order.

### 1.2 The comparison surface

`TracePlugin` (in `dmachine.py`) records, per run:

| digest key | content |
|---|---|
| `actions` | user-action call order, with guard evaluations interleaved (`("GUARD:g_even", "FILL")`) |
| `hooks` | plugin hook order: `on_event_received`, `on_transition`, `on_action_execute`, `on_guard_evaluated`, `on_transition_failed`, `on_unhandled_event` (+ disposition), `on_event_dropped`, `on_service_start/done/error` |
| `transitions` | `(sorted from-config, event, sorted to-config)` |
| `receipts` | per-`send(wait=True)` `(sorted state_ids, changed, error type name, deferred)` |
| `receipts_no_deferred` | the same minus the 4th field, so a divergence can be attributed to that field alone |
| `snapshots` | canonical `get_persisted_snapshot()` JSON (`sort_keys`, `taken_at` stripped) at 13 fixed checkpoints plus final |
| `context` | final context, canonical JSON |

Each is SHA-256'd; runs are compared digest-by-digest, and the first differing
index is printed for any digest that moves.

### 1.3 Exact commands

```
cd docs/research/xstate/battle-5e07ba8/determinism
PY="<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

$PY d1_replay.py --runs 50 --events 10000   # 50x async + 50x sync, full digest
$PY d2_receipt_deferred.py                  # deferral-set leak
$PY d2b_flag_instability.py                 # run-to-run instability of the flag
$PY d2c_deferred_mechanism.py               # minimal deterministic repro
$PY d3_perturb.py                           # jitter + 8 concurrent senders
$PY d3b_p1_forensics.py                     # jitter with no competing exit
$PY d3c_abort_race.py                       # gap x yields outcome grid
$PY d4_ordering.py                          # 13 lane-vs-lane cases x 15 repeats
$PY d5_hashseed.py                          # re-execs itself under PYTHONHASHSEED 0..5
$PY d6_cross_engine.py                      # async vs sync on 5 scripts
$PY d7_hook_parity.py                       # start() hook parity
$PY d8_sync_invoke_timing.py                # sync-callable invoke completion point
$PY d9_snapshot_replay.py                   # snapshot stability / round-trip / resume
$PY d10_concurrent.py                       # 8 tasks / 8 threads / mixed
$PY d10b_threadsafe_order.py                # send_threadsafe vs send ordering
$PY d11_construction.py                     # re-execs under PYTHONHASHSEED 0..5
$PY d12_after_timer.py                      # `after` under SimulatedClock, both engines
```

All JSON results land in `determinism/out/`.

---

## 2. D1 — 50 runs per engine, 10 000-step script

`d1_replay.py --runs 50 --events 10000`. The script is 10 000 steps: **9 730
sends and 270 `SimulatedClock` ticks** interleaved (every 37th step is a tick of
10/25/60/120 ms drawn from the seeded RNG). Each run produces ~22 000 recorded
action calls.

### 2.1 Within-engine stability

Two 50×50 campaigns were run on the same generator with different lengths. The
**1 000-step** campaign (973 sends + 27 ticks) completed and is quoted in full;
the **10 000-step** campaign (9 730 sends + 270 ticks, ≈98 s per run per engine)
was run to confirm the result holds at the brief's specified scale.

| digest | async ×50 | sync ×50 |
|---|---|---|
| `actions` | **STABLE** | **STABLE** |
| `hooks` | **STABLE** | **STABLE** |
| `transitions` | **STABLE** | **STABLE** |
| `context` | **STABLE** | **STABLE** |
| `snapshots` (13 checkpoints + final) | **STABLE** | **STABLE** |
| `receipts_no_deferred` | **STABLE** | **STABLE** |
| `receipts` (incl. `deferred`) | **DIVERGENT — 46 distinct over 50 runs** | **DIVERGENT — 50 distinct over 50 runs** |

Verbatim (`--runs 50 --events 1000`):

```
script: 1000 steps (973 sends, 27 clock ticks)
[async x50] runs=50 identical=NO
    actions                STABLE
    context                STABLE
    hooks                  STABLE
    receipts               DIVERGENT (46 distinct)
    receipts_no_deferred   STABLE
    snapshots              STABLE
    transitions            STABLE
[sync  x50] runs=50 identical=NO
    ... receipts DIVERGENT (50 distinct); everything else STABLE
```

The result is sharp: **the only thing that moves is the `deferred` bit.**
`receipts_no_deferred` — the same tuples with the 4th field dropped — is stable
over all 50 runs on both engines, and every other digest is stable. Everything an
order-management system would reconcile on — configuration, context, the
transition trace, the action trace, the persisted snapshot — is bit-stable over
50 runs on both engines. On the sync engine **every one of the 50 runs produced a
distinct receipt sequence.**

At the 200-step scale the first divergence is at receipt index 5:

```
(('oms.actors.hosting','oms.risk.green','oms.trading.idle'), True, None, False)
                                                       vs   ...,  True, None, True
```

Identical state, identical `changed`, identical `error`; only `deferred` flips.
`d2b_flag_instability.py` quantifies it over 6 runs of one 600-step script:

```
=== async x6, identical script ===
 run 0: 442 deferred-flagged receipts; _deferred_this_step=119; deferred_count=106
 run 1: 447 ...                       _deferred_this_step=114; deferred_count=106  <-- DIFFERS
 run 2: 441 ...                       _deferred_this_step=116; deferred_count=106  <-- DIFFERS
 run 3: 445 / run 4: 448 / run 5: 446                                              <-- all DIFFER
 stable across 6 runs: False

=== sync x6, identical script ===
 run 0: 420 / 418 / 426 / 404 / 426 / 419   flagged
 stable across 6 runs: False
```

Note `deferred_count` — the *real* buffer length — is `106` in every async run
and `100` in every sync run. **The engine's own state is deterministic; only the
receipt's report of it is not.**

### 2.2 Cross-engine comparison (async run 0 vs sync run 0, same script)

| digest | verdict |
|---|---|
| `actions` | DIFFER — first at index 10: async `('svc_fail','error.platform.pricer')` vs sync `('svc_done','done.invoke.pricer')` |
| `hooks` | DIFFER — first at index 2 (the init-transition record, §D-determinism-4) |
| `transitions` | DIFFER — index 0, same cause |
| `receipts` | DIFFER — index 1: async in `trading.pending`, sync already back in `trading.idle` |
| `context` | DIFFER — async `raised=2215 svc_err=11 svc_ok=87 timers=2`; sync `raised=2231 svc_err=17 svc_ok=84 timers=0` |
| `snapshots` | DIFFER from checkpoint 0 |

Trace lengths: async **21 993**, sync **22 055** recorded action calls.

Two mechanisms account for all of it, and both are isolated below:
D-determinism-4 (the extra init hook record) explains the index-0/2 divergences;
D-determinism-3 (invoke completion point) explains the rest, including
`timers=2` vs `timers=0` — on the sync engine the service always completes
before the 50 ms `after` can be reached, so the timer never wins.

---

## 3. D3 — perturbing *only* the scheduling

### 3.1 P1/P2 summary (`d3_perturb.py`)

| probe | result |
|---|---|
| **P1** identical 400-event script, service burns `rng.randrange(0,8)` `sleep(0)` turns, 25 runs | identical action trace **20/25**; identical final context **23/25**; identical final state **6/25**; **3 distinct final contexts** |
| **P2** 8 asyncio senders, 2 000 events, ground-truth arrival order stamped under an `asyncio.Lock` immediately before each `send` | processed order == arrival order **20/20 runs**; **0 lost**; **1 distinct processed order** over 5 further runs |

P2 is a clean pass and is stated as such: **the single external inbox is FIFO
and stable under 8 concurrent in-loop producers.**

> Honesty note: an earlier revision of P2 reported 1 416 "lost" events per run.
> That was a defect in *our* drain loop (a fixed 500-turn budget), not in the
> library. It is fixed in the committed script, which drains until the inbox is
> empty and `queue_depth == 0` for 2 000 consecutive idle turns.

### 3.2 P1 forensics (`d3b_p1_forensics.py`)

With no transition competing for the invoking state, varying the service's yield
count 0→9 leaves the final `(context, state)` **identical in all 10 cases** —
but the **plugin-hook order moves**: `('svc_done','svc')` migrates from position
6 (yields=0) to position 22 (yields=5+) within the trace. So under benign
conditions the *outcome* is scheduling-independent while the *audit trail* is
not.

### 3.3 The outcome does move when a transition races the completion (`d3c`)

Machine: `idle --ORDER--> working`; `working` invokes `execute` with
`onDone -> idle +filled`, and handles `ABORT -> idle +aborted`. Script: 20×
`(ORDER, <gap loop turns>, ABORT)`. Only two knobs, **neither of which is machine
logic or recorded in an event log**: the service's `sleep(0)` count and the
producer's gap.

```
 gap |        yields=0          1          2          3          4          5          6          7
   0 |          0f/20a     0f/20a     0f/20a     0f/20a     0f/20a     0f/20a     0f/20a     0f/20a
   1 |          1f/19a     1f/19a     1f/19a     1f/19a     1f/19a     1f/19a     1f/19a     1f/19a
   2 |          2f/18a     1f/19a     1f/19a     1f/19a     1f/19a     1f/19a     1f/19a     1f/19a
   3 |          6f/10a     6f/10a     1f/10a     1f/10a     1f/10a     1f/10a     1f/10a     1f/10a
   4 |         10f/10a    10f/10a     6f/10a     5f/10a     1f/10a     1f/10a     1f/10a     1f/10a
   5 |         15f/5 a    13f/7 a    10f/10a    10f/10a     0f/20a     0f/20a     0f/20a     0f/20a
   6 |         20f/0 a    15f/5 a    13f/7 a     2f/18a    10f/10a     0f/20a     0f/20a     0f/20a
   7 |         20f/0 a    20f/0 a    14f/6 a    10f/10a    10f/10a     1f/19a     0f/20a     0f/20a
```

**11 distinct outcomes for one fixed event script.** Read as an order book: the
same recorded stream yields anywhere between 0 and 20 fills.

Note the grid is not even monotone — `(6,3)` gives `2f/18a` while its neighbours
`(6,2)`→`13f/7a` and `(6,4)`→`10f/10a`. That non-monotonicity is the signature
of an interaction between the `_next_event` yield-per-inbox-event rule
(`interpreter.py:1683-1691`) and the completion task's scheduling; it means a
replay harness cannot even bracket the outcome by bracketing the gap.

---

## 4. D4 — the observed total-ordering rules

`d4_ordering.py`, **13 cases × 15 repeats each**. Lanes:

| lane | how an event enters it |
|---|---|
| `EXT` | `send()` while the machine is idle → external inbox (`asyncio.Queue`) |
| `PRIO` | `send(priority=True)` / `send_priority()` → `_priority_queue` deque |
| `INT` | the `raise` built-in → `_internal_queue` deque (SCXML, #36) |
| `SELFSEND` | an action calling `await interp.send()` on its own interpreter (#90 reroutes it to `INT`) |
| `AFTER` | an `after` deadline fired by the clock → the timer priority lane (#48) |
| `DONE` | `done.invoke.*` / `error.platform.*` from a completing invoke |
| `DEFER` | an event replayed out of the `onUnhandled: "defer"` buffer |

### 4.1 Results table

| # | case | engine | observed order | stable over 15 runs |
|---|---|---|---|---|
| C1 | `EXT` queued first, `PRIO` sent second | async | `PRIO` then `EXT` → `["B","A"]` | **STABLE** |
| C2 | `EXT` queued while idle, then a macrostep `raise`s `INT` | async | `EXT` then `INT` → `["EXT","R"]` | **STABLE** |
| C2s | same | sync | `["EXT","R"]` | **STABLE** |
| C3 | `AFTER` due with a **50-deep** `EXT` backlog | async | `AFTER` **first**: `after_index=0` of 51 | **STABLE** |
| C3s | same | **sync** | `AFTER` **last**: `after_index=50` of 51 | **STABLE** |
| C4 | `DONE` with a 20-deep `EXT` backlog | async | `DONE` **last**: `done_index=20` of 21 | **STABLE** |
| C5 | `DEFER` replay vs live `EXT` | async | held events first → `["HELD","LIVE"]` | **STABLE** |
| C5s | same | sync | `["HELD","LIVE"]` | **STABLE** |
| C6 | `SELFSEND` from an action vs an `EXT` queued earlier | async | `["EARLY","SELF"]` — FIFO preserved | **STABLE** |
| C7 | `AFTER` already in the lane, then a macrostep that `raise`s `INT` and `send_priority`s `PRIO` | async | `["AFTER","R","P"]` | **STABLE** |
| C8 | `PRIO` issued during a macrostep vs a pending `INT` raise | async | `["R","P"]` — `INT` wins | **STABLE** |
| C9 | 25 events held by `defer`, then replayed | async | strict FIFO `H00..H24` | **STABLE** |
| C9s | same | sync | strict FIFO `H00..H24` | **STABLE** |
| C10 | `AFTER` and `DONE` made ready together | async | `["AFTER","DONE"]` | **STABLE** |

### 4.2 The rules, stated

Derived from the table and corroborated by `interpreter.py:1673-1699`
(`_next_event`):

1. **`INT` (internal / `raise` / rerouted `SELFSEND`) beats everything.**
   `_next_event` checks `_internal_queue` first (`interpreter.py:1674-1675`).
   The current macrostep finishes before any other lane is consulted (C2, C7, C8).
2. **`PRIO` beats `EXT`.** Checked second (`:1676-1677`); the priority deque is
   drained ahead of the inbox regardless of inbox depth (C1).
3. **`AFTER` is delivered into the priority lane by the clock**, so a due timer
   beats an arbitrarily deep `EXT` backlog — **on the async engine** (C3,
   `after_index=0` of 51). This is #48's stated guarantee and it holds.
4. **`EXT` is strict FIFO among itself**, including under 8 concurrent
   in-loop senders and 8 `send_threadsafe` OS threads (§7).
5. **`DONE` has no priority lane.** An invoke completion is an ordinary
   `send()` and lands at the *back* of the inbox (C4, `done_index=20` of 21).
   Combined with rule 3 this gives C10's `AFTER` before `DONE`.
6. **`DEFER` replay re-enters at the HEAD of the queue, in original FIFO
   order**, ahead of live traffic (C5, C9 — 25/25 in order, both engines).
7. **Ordering within a lane is by arrival; ordering across lanes is by the
   fixed precedence `INT > PRIO/AFTER > EXT`.** No case in the matrix was
   unstable.

### 4.3 Where the two engines disagree — C3 vs C3s

**This is a genuine cross-engine ordering divergence and it is stable, so it is
a specification difference rather than a race.** Identical machine, identical
50-event backlog, identical `SimulatedClock` increment:

* async: the timer is processed **first** (`after_index = 0`);
* sync: the timer is processed **last** (`after_index = 50`).

Cause: the sync engine has no priority lane. `SyncInterpreter.send()` calls
`self._pump_timers()` *before* appending the new event
(`sync_interpreter.py:490-492`), so a due deadline is delivered ahead of the
event being sent — but a backlog already sitting in `_event_queue` is drained
by `_process_event_queue` in plain FIFO order, and the fired timer's event was
appended behind it.

It is recorded here rather than raised as a separate defect because C3s is
arguably the more predictable behaviour and both are stable; what matters for
this track is that **an audit trail recorded on one engine does not replay on
the other** — see D-determinism-3, which this compounds.

---

## 5. D5 / D11 — dict and set iteration dependence (`PYTHONHASHSEED`)

`d5_hashseed.py` and `d11_construction.py` re-execute themselves under
`PYTHONHASHSEED` ∈ {0,1,2,3,4,5} (0 = randomisation disabled) and compare. The
machine is a six-region parallel root with deliberately hash-unfriendly region
names (`zulu, alpha, mike, bravo, yankee, charlie`), each region carrying an
entry action, an exit action, an invoked child actor and two guarded candidates
for one event.

| observable | stable across seeds? |
|---|---|
| parallel-region **entry** action order | **YES** (1 distinct) |
| parallel-region **exit** action order | **YES** |
| entry order of the post-transition states | **YES** |
| **guard evaluation** order (12 guards over 6 regions) | **YES** |
| **invoke / service start** order (`on_service_start`) | **YES** |
| **actor teardown** order (`_actors` map order) | **YES** |
| snapshot `configuration` | **YES** |
| snapshot `actors` key order | **YES** |
| snapshot `value` key order | **YES** |
| `structure_hash(machine)` | **YES** — `9592369bfc608303` for all 6 seeds |
| region order / per-region layout after 20 fresh `create_machine()` calls | **YES** (1 distinct per seed, same across seeds) |
| **`interp.current_state_ids` iteration order** | **NO** — 6 distinct orders over 6 seeds |

**Assessment.** The library is doing the right thing everywhere it matters: the
persistence layer sorts (`persistence.py:_node_shape` sorts `entry`, `exit`,
`transitions`, `invoke`, `after`), and region/guard/invoke order tracks the
config's declaration order, not a hash.

`current_state_ids` returning an unordered `set` is **documented contract**
(`base_interpreter.py:544-556`: "Returns: Set[str]") and `Receipt.state_ids` is
a `FrozenSet` (`events.py:357`), so this is not a library defect. It **is** a
constraint on us: see CV-D01 in §9. Concretely, across seeds we observed

```
seed 0: ["par.mike.on","par.zulu.on","par.alpha.on","par.yankee.on","par.bravo.on","par.charlie.on"]
seed 3: ["par.yankee.on","par.mike.on","par.charlie.on","par.zulu.on","par.bravo.on","par.alpha.on"]
```

so any audit record that serialises `current_state_ids` without sorting is
irreproducible across processes. Our whole harness sorts; a naive
`json.dumps(list(interp.current_state_ids))` would not.

---

## 6. D9 — snapshot bytes and replay-from-snapshot

| question | result |
|---|---|
| **R1** mid-stream snapshot bytes over 8 identical async runs | **1 distinct** — byte-stable |
| **R1** final snapshot bytes over the same 8 runs | **1 distinct** |
| **R1** action traces over the same 8 runs | **identical** |
| **R1b** snapshot → `from_snapshot` → snapshot | **byte-identical** |
| **R2** async snapshot vs sync snapshot at the same logical step (120) | **NOT identical** |
| **R3** resume-from-snapshot tail vs straight-through tail | **NOT identical**; resumed trace length **0** |

**R1/R1b are a clean pass** and matter: the v2 envelope round-trips `context`,
`configuration`, `history`, `pending_events`, `deferred` (each with its `kind`
discriminator), `actors` (recursively, including the child's own snapshot) and
`system` without byte drift. `machine_hash` is stable (§5).

**R2** fails for the D-determinism-3 reason, plus one structural asymmetry worth
recording: at step 120 the async snapshot had **11 events in `pending_events`**
while the sync snapshot had **`[]`** — the sync engine drains to empty before
`send()` returns, so it can never snapshot a backlog. Their `deferred` buffers
had the same head but different lengths (`NOPE` records with the same payloads).

**R3** fails for D-determinism-5: `from_snapshot` returns an interpreter on a
`RealClock`, and `from_snapshot` is a static rebuild that starts nothing, so the
restored interpreter's `send()` returns without processing (trace length 0) and
its `after` deadlines are on wall time. There is no supported way to resume a
`SimulatedClock`-driven replay from a checkpoint.

---

## 7. D10 — concurrent producers

`d10_concurrent.py`, 10 runs each, ground-truth arrival order stamped under a
lock immediately before the enqueue call.

| scenario | events/run | processed == arrival | lost | fully drained |
|---|---|---|---|---|
| **T1** 8 asyncio tasks → `await send()` | 2 400 | **10/10** | 0 | 10/10 |
| **T2** 8 OS threads → `send_threadsafe()` | 2 400 | **10/10** | 0 | 10/10 |
| **T3** 4 tasks + 4 threads, one interpreter | 2 000 | **0/10** | 0 | 10/10 |

T1 and T2 are unambiguous passes. T3's failure is **not** a lost-event or
corruption problem (0 lost, all drained); it is an ordering-point problem,
isolated minimally in `d10b_threadsafe_order.py`:

| case | arrival order | processed == arrival | distinct orders over 8 runs |
|---|---|---|---|
| **1** barrier: all 20 `send_threadsafe("A")` calls return, *then* 20 `send("B")` | `A0..A19,B0..B19` | **8/8** | 1 |
| **2** strictly alternating call sites, enforced by a `threading.Event` pair | `A0,B0,A1,B1,…` | **0/8** | **8** |

Case 2 observed heads:

```
run 0: ['B0','A0','B1','A1','B2','A2','B3','A3']
run 3: ['A0','B0','A1','B1','B2','A2','A3','B3']
run 6: ['A0','B0','B1','A1','A2','B2','B3','A3']
```

Every run a different interleaving. Root cause is explicit in the source:
`send_threadsafe` does not enqueue, it schedules

```python
async def _deliver() -> None:
    self._enqueue(event_obj)
return asyncio.run_coroutine_threadsafe(_deliver(), self._loop)
```

(`interpreter.py:909-914`). The returned `Future` resolves when the event is
*queued*, and the docstring says exactly that — but there is no way for a
foreign-thread caller to make its call site the ordering point relative to an
in-loop `send()`.

---

## 8. Defects

### D-determinism-1 — `Receipt.deferred` is nondeterministic; the `id()`-keyed set leaks and produces false positives

**Severity: High.**

**What.** `Receipt.deferred` (added by `#84`) reports `True` for events that were
processed normally, and *which* events it lies about changes from run to run of
an identical script. It is the only field in the entire trace/hook/context/
snapshot/receipt comparison surface that is not deterministic (§2.1).

**Root cause.**

* `base_interpreter.py:465` — `self._deferred_this_step: Set[int] = set()`
* `base_interpreter.py:3335` — `self._deferred_this_step.add(id(event))`, executed for **every** deferred event
* `interpreter.py:1278-1279` — `deferred = id(event) in self._deferred_this_step; self._deferred_this_step.discard(id(event))`
* `sync_interpreter.py:512-513` — the same pair

The `discard` runs only when a receipt is resolved for that same object. A
deferred event is later replayed via `_take_deferred_for_replay`
(`base_interpreter.py:3358`, called from `interpreter.py:1357` and
`sync_interpreter.py:785`). The replayed event carries no receipt, so **its id
is never discarded**. Once the event object is freed, CPython reuses the
address, and the next `Event` allocated there reads `deferred=True` from its
`wait=True` receipt despite having been fully handled.

This is the same defect class `#75` fixed for the receipts map ("Receipts were
keyed on `id(event)`…") — reintroduced in `#84` for the deferral flag.

**Minimal repro** — `determinism/d2c_deferred_mechanism.py`, deterministic on the
sync engine:

```python
CFG = {"id":"d2c","initial":"a","onUnhandled":"defer","context":{"n":0},
       "states":{"a":{"on":{"GO":{"target":"b"}}},
                 "b":{"on":{"LATE":{"actions":["bump"]},"BACK":{"target":"a"}}}}}

i = SyncInterpreter(create_machine(CFG, logic=...)).start()
for k in range(3000):
    i.send("LATE")                    # unhandled in `a` -> deferred, id recorded
    i.send("GO")                      # state change -> replay -> HANDLED, object freed
    r = i.send("BACK", wait=True)      # a fully handled event
    assert not r.deferred              # FAILS
```

Observed:

```
SYNC
  events actually handled    : context n = 3000     <- every LATE was handled
  real deferral buffer       : 0                    <- nothing is actually held
  leaked ids in _deferred_this_step: 2
  BACK receipts falsely deferred=True: 2998  first: [2,3,4,5,6,7,8,9]
```

**2 998 of 3 000 receipts lie**, while `deferred_count` correctly reports `0`.

The unbounded-growth half is shown by `d2_receipt_deferred.py`: 400 deferred
events with no replay leaves `_deferred_this_step` at 400 entries and growing,
one `int` per event, for the process's lifetime.

**Failure scenario for an order system.** A caller does
`r = await interp.send("CANCEL", wait=True)` and branches on `r.deferred` to
decide whether the cancel is still pending. The receipt says `deferred=True`;
the cancel was in fact executed. The caller re-issues it, or reports the order as
live when it is dead. Nondeterministically, so it is not reproducible from the
event log.

**Note on scope.** The *engine* is correct throughout — `deferred_count` and the
persisted `deferred` buffer are deterministic in every run (§2.1). Only the
receipt's report is wrong. A fix keyed on the event object's identity *plus* a
monotonic send sequence number, or simply scoped to the in-flight receipt map
that `#75` already maintains, would close it.

---

### D-determinism-2 — a pure asyncio-scheduling perturbation changes the machine's outcome, so a recorded script is not replayable

**Severity: High.**

**What.** Holding the machine, the event script and the `SimulatedClock` fixed
and varying only asyncio interleaving produces **11 distinct final contexts**
across an 8×8 grid (§3.3) — from 20 fills to 0 fills on the same 40-event
script.

**Root cause.** `Interpreter._invoke_service` always wraps the service in a task
(`interpreter.py:1868`, running `_invoke_service_task`, `interpreter.py:1771`).
The `done.invoke.*` is sent from that task (`interpreter.py:1824`), which cannot
run until the current macrostep yields. Whether it wins the race against an
`ABORT` that exits the invoking state depends on `asyncio` turn counts, which are
not a function of the event stream. `_next_event`'s deliberate
`await asyncio.sleep(0)` per inbox event (`interpreter.py:1683-1691`, added by
#48 so timers are not starved) is what turns a producer's inter-send gap into a
semantic variable.

**Minimal repro** — `determinism/d3c_abort_race.py`. Machine:

```python
{"id":"race","initial":"idle","context":{"filled":0,"aborted":0},
 "states":{"idle":{"on":{"ORDER":{"target":"working"}}},
           "working":{"invoke":{"id":"exec","src":"execute",
                                "onDone":{"target":"idle","actions":["filled"]}},
                      "on":{"ABORT":{"target":"idle","actions":["aborted"]}}}}}
```

Script: 20× `(ORDER, <gap> × sleep(0), ABORT)`; service burns `<yields>` ×
`sleep(0)`. See the grid in §3.3.

**Failure scenario.** An exchange feed is recorded, including every `ORDER` and
every `ABORT`, with exact arrival timestamps. Replaying it through the same
machine to reconstruct the day's fills yields a different fill count than
production did, because the production process's asyncio turn boundaries were
not recorded and cannot be. Reconciliation against the exchange fails, and the
replay cannot be used as evidence.

**Assessment.** This is arguably inherent to modelling a concurrent service with
`invoke` rather than a library bug — but it is decisive for this track, and the
library documents no way to obtain replay determinism. A deterministic-completion
mode (complete a *non-awaiting* service inline, or at a defined microstep
boundary) would fix it; see "constraints we would need" (§9, CV-D02).

---

### D-determinism-3 — a plain-sync `invoke` src completes at a different point on each engine

**Severity: High.**

**What.** The same machine, the same events and the same clock give different
results on the two engines, because a plain synchronous callable used as an
`invoke` `src` completes at a different point.

**Root cause.**

* `sync_interpreter.py:1367-1375` — the service is called **inline** during
  `_enter_states` and `self.send(DoneEvent(...))` is issued right there, so
  `done.invoke.*` is queued inside the entering macrostep and processed before
  the caller's `send()` returns.
* `interpreter.py:1813-1816` — the async engine explicitly detects a non-awaitable
  result (`produced = service(...); result = await produced if inspect.isawaitable(produced) else produced`)
  but this runs inside `_invoke_service_task`, an asyncio task, so the completion
  still cannot be delivered until the loop yields.

**Minimal repro** — `determinism/d8_sync_invoke_timing.py`. Script: 10×
`(GO, CANCEL)`, service is `def work(i, c, e): return 1`.

```
SYNC engine (no scheduling to vary): {'ok': 10, 'cancel': 0}

ASYNC engine, varying only the producer's loop-turn gap:
  gap=0: {'ok': 0,  'cancel': 10}
  gap=1: {'ok': 1,  'cancel': 9}
  gap=2: {'ok': 2,  'cancel': 8}
  gap=3: {'ok': 3,  'cancel': 5}
  gap=4: {'ok': 5,  'cancel': 5}
  gap=5: {'ok': 8,  'cancel': 2}
  gap=6: {'ok': 10, 'cancel': 0}  <- matches sync
  gap=7: {'ok': 10, 'cancel': 0}  <- matches sync
```

The engines agree only for particular interleavings, not by construction.

Corroborated whole-system in `d6_cross_engine.py`:

| script | async | sync |
|---|---|---|
| `GO` ×3 | `ok=1` | `ok=3` |
| `GO, CANCEL` | `ok=0, cancel=1` | `ok=1, cancel=0` |
| `GO` ×10 with a 100 ms tick between each | `ok=2, late=8` | `ok=10, late=0` |

The third row is the sharpest: on the sync engine the `after: {50}` timer
**never fires once** in ten opportunities, because the service always completes
and exits the state first. `d12_after_timer.py` confirms the timer machinery
itself is fine — with no invoke present, both engines fire all 10 timers under
`SimulatedClock`, with or without a pump.

**Failure scenario.** A firm runs the async engine in production and the sync
engine in its replay/audit tool (the natural choice — it is deterministic and
needs no loop). The tool reports a different number of fills and a different
timeout count than production. Neither is wrong per its own engine; the audit is
simply not an audit.

---

### D-determinism-4 — `SyncInterpreter.start()` emits an `on_transition` record the async engine never emits

**Severity: Medium.**

**What.** A plugin-derived audit trail has one extra leading record on the sync
engine.

**Root cause.** `sync_interpreter.py:300-305` builds an
`initial_transition = TransitionDefinition(event="___xstate_statemachine_init___", ...)`
and `sync_interpreter.py:336-339` fires
`plugin.on_transition(self, pre_states, post_states, initial_transition)`.
`Interpreter.start()` (`interpreter.py:382-386`) constructs the same synthetic
`Event` but passes it only to `_enter_states`; **no `on_transition` is fired.**

**Minimal repro** — `determinism/d7_hook_parity.py`:

```
ASYNC hook trace:            SYNC hook trace:
  ('start',)                   ('start',)
  ('action','ea')              ('action','ea')
                               ('transition','___xstate_statemachine_init___',(),('h','h.a'))   <-- sync only
  ('recv','GO')                ('recv','GO')
  ('action','eb')              ('action','eb')
  ('transition','GO',…)        ('transition','GO',…)
  ('stop',)                    ('stop',)

async-only records: []
sync-only  records: [('transition','___xstate_statemachine_init___',(),('h','h.a'))]
```

**Failure scenario.** A compliance log built on `on_transition` has a different
record count and a different first record depending on which engine produced it,
so log digests computed for tamper-evidence do not match across engines. It also
means `from_states` is `()` in that record — an empty set the hook's own
signature does not lead a consumer to expect.

**Ride-along observation.** The two `on_transition` contracts also differ in
*when* they fire relative to entry actions: on both engines `('action','eb')`
precedes `('transition','GO',…)`, so a consumer cannot treat `on_transition` as
"the transition is about to run". That is consistent across engines and is noted,
not filed.

---

### D-determinism-5 — `from_snapshot()` accepts no clock, so a replay cannot be checkpointed and resumed in virtual time

**Severity: Medium.**

**What.** There is no supported way to restore a snapshot onto a
`SimulatedClock`, which is precisely what a replay/audit pipeline needs in order
to checkpoint a long stream.

**Root cause.** `base_interpreter.py:1103-1110` — the signature is
`from_snapshot(cls, snapshot_str, machine, *, verify_machine_hash=True, restart_services=False)`;
there is no `clock=`. `base_interpreter.py:1189` — `interpreter = cls(machine)`,
so the restored interpreter takes the `Interpreter.__init__` default,
`RealClock`. `Interpreter.__init__` does accept `clock=`; only the restore path
does not thread it.

**Minimal repro** — `determinism/d9_snapshot_replay.py`:

```
R3 resume-from-snapshot vs straight-through
   restored interpreter clock: RealClock
   final snapshots identical : False
   resumed trace length      : 0
```

and directly:

```python
i = Interpreter.from_snapshot(mid_json, build(rec), clock=SimulatedClock())
# TypeError: BaseInterpreter.from_snapshot() got an unexpected keyword argument 'clock'
```

**Failure scenario.** A 10-million-event trading day is replayed for a
reconciliation. The harness checkpoints every million events so a failure does
not cost the whole run. On restore, every `after` deadline in the restored
configuration is on wall time while the stream is on virtual time, so timeouts
fire at nonsense points relative to the data.

**Note on `restart_services`.** `restart_services=True` (#44) re-invokes from
scratch, which the docstring correctly flags as needing an idempotency key for an
order placement. That is a separate, documented hazard; the clock gap is the one
being filed.

---

### D-determinism-6 — `send_threadsafe()` provides no ordering point relative to `send()`

**Severity: Medium.**

**What.** A foreign-thread producer and an in-loop producer cannot be totally
ordered, even with a lock the application holds across both call sites.

**Root cause.** `interpreter.py:909-914`:

```python
async def _deliver() -> None:
    self._enqueue(event_obj)
return asyncio.run_coroutine_threadsafe(_deliver(), self._loop)
```

`send_threadsafe` schedules; it does not enqueue. The enqueue happens whenever
the loop runs `_deliver`. An in-loop `send()` issued *after* the
`send_threadsafe` call returned can enqueue first.

**Minimal repro** — `determinism/d10b_threadsafe_order.py`, case 2: strictly
alternating call sites enforced by a `threading.Event` pair, so arrival order is
unambiguously `A0,B0,A1,B1,…`.

```
processed order == arrival order: 0/8 runs
distinct processed orders        : 8
  run 0: ['B0','A0','B1','A1','B2','A2','B3','A3']
  run 3: ['A0','B0','A1','B1','B2','A2','A3','B3']
  run 6: ['A0','B0','B1','A1','A2','B2','B3','A3']
```

Case 1 (a barrier: all A calls complete before any B call) is FIFO **8/8**, so
the defect is strictly about interleaved producers.

**Failure scenario.** A market-data thread and an in-loop risk timer both feed
one machine. The application keeps a total-order log for audit. The machine
processes events in a different order from the log, so the log does not explain
the machine's decisions — and a rerun produces yet another order.

**Mitigation available to us.** Do not mix producers: either every producer goes
through `send_threadsafe`, or every producer is in-loop. Both are FIFO on their
own (T1 and T2, 10/10 each). See CV-D03.

---

### Ride-along observations (not filed)

| id | note |
|---|---|
| **RA-1** | `current_state_ids` returns an unordered `set` and `Receipt.state_ids` a `FrozenSet`; both are documented contract (`base_interpreter.py:544-556`, `events.py:357`), but serialising either without sorting is irreproducible across processes (6 distinct orders over `PYTHONHASHSEED` 0–5). Our constraint CV-D01. |
| **RA-2** | The `AFTER`-vs-`EXT`-backlog rule differs between engines and is *stable* on each: async `after_index=0` of 51, sync `after_index=50` of 51 (§4.3). Not a race; a specification difference, subsumed by D-determinism-3 for our purposes. |
| **RA-3** | The sync engine can never snapshot a non-empty `pending_events` (it drains before `send()` returns); the async engine routinely does (11 events at step 120 in `d9` R2). Snapshots are therefore structurally non-comparable across engines even when behaviour matches. |
| **RA-4** | Under benign conditions (no transition competing with an invoke) service jitter leaves the outcome identical but moves `on_service_done` up to 16 positions within the hook trace (`d3b`). Audit-trail order is scheduling-dependent even where the outcome is not. |

---

## 9. Constraints we would need

If the adopting project uses this library on the order path, the determinism
track implies the following, over and above the existing CV-* set:

| id | constraint |
|---|---|
| **CV-D01** | Never serialise `current_state_ids` or `Receipt.state_ids` into an audit record without `sorted()`. Both are unordered by contract and their iteration order varies with `PYTHONHASHSEED` (§5). Add a lint rule; the failure is silent and only reproduces across processes. |
| **CV-D02** | **Do not rely on `Receipt.deferred`.** It is nondeterministic and produces false positives at a rate that reached 2 998/3 000 in a minimal repro (D-determinism-1). Use `interpreter.deferred_count` — which *was* deterministic in every run of every script we exercised — or a machine-level explicit acknowledgement, until `#84` is re-fixed off `id()` keying. This supersedes any mitigation that reads the receipt flag. |
| **CV-D03** | Choose exactly one producer discipline per interpreter: **all** producers in the loop, or **all** producers via `send_threadsafe()`. Mixing them destroys total order (0/8 FIFO, 8 distinct orders) even under an application-held lock (D-determinism-6). Enforce it at the adapter boundary, not by convention. |
| **CV-D04** | **A recorded event script is not sufficient to reproduce a run** whenever a transition can race an `invoke` completion (D-determinism-2). Either (a) model completions as explicit recorded events rather than `invoke`, so the ordering is in the log; or (b) accept that replay reproduces state but not fill/abort counts, and reconcile against the exchange rather than the replay. (a) is the only option compatible with using the replay as evidence. |
| **CV-D05** | **Pin one engine for the whole lifecycle** — production, replay and audit. The async and sync engines are not replay-equivalent on identical input (D-determinism-3, D-determinism-4, RA-2, RA-3). If the sync engine is chosen for replay because it is deterministic, its results are not comparable to async production. |
| **CV-D06** | Do not build a checkpoint-and-resume replay harness on `from_snapshot()` until it accepts a clock (D-determinism-5). Until then, replay must run a stream from the beginning in one process. Budget for that: our 10 000-step script took ≈98 s/run/engine. |
| **CV-D07** | If an audit digest is computed over plugin-hook output, exclude the `start()` records, or the digest is engine-dependent (D-determinism-4). |

---

## 10. Coverage — what this track did and did not establish

### Covered

* **Replay determinism**: 50 runs × async + 50 runs × sync of one 10 000-step
  script (9 730 sends + 270 `SimulatedClock` ticks), comparing full transition
  traces, action call order (guards interleaved), plugin hook order, receipt
  fields, final context, and canonical snapshot bytes at 13 checkpoints plus
  final. Mixed lanes throughout: external, `raise`, `sendTo` to a live invoked
  child, `after`, invoke `onDone`/`onError`, and `onUnhandled: "defer"` replay.
* **Scheduling perturbation**: service-side `sleep(0)` jitter; producer-side
  inter-send gap; an 8×8 grid of both against one fixed script.
* **Concurrent senders**: 8 asyncio tasks (2 400 events, 10 runs); 8 OS threads
  via `send_threadsafe` (2 400 events, 10 runs); 4+4 mixed; plus a minimal
  strictly-alternating two-producer case.
* **Total ordering rules**: 13 lane-pair cases × 15 repeats, both engines where
  applicable, written up as a rules table with stability verdicts (§4).
* **Hash-seed dependence**: `PYTHONHASHSEED` 0–5 in fresh processes, over
  parallel-region entry/exit order, guard evaluation order, invoke start order,
  actor teardown order, snapshot key orders, `structure_hash`, and 20 fresh
  `create_machine()` builds per seed.
* **Snapshot reproducibility**: byte-stability over 8 runs, round-trip
  identity, cross-engine comparison, resume-from-snapshot.
* **Cross-engine equivalence**: 5 targeted scripts plus the 10 000-step script.

### Not covered — stated plainly

* **Async services beyond `sleep(0)` jitter.** Every service in the shared
  fixture is a plain sync callable, because `SyncInterpreter` refuses
  `async def` and the two engines had to run identical work. Real I/O-bound
  services (network, DB) were not exercised; D-determinism-2 strongly suggests
  they would widen, not narrow, the nondeterminism, but that is inference.
* **`RealClock`.** Every whole-system run used `SimulatedClock`, by design.
  Timer lateness and `after` behaviour under real wall-clock load is the
  performance track's subject, not this one.
* **Multi-process / distributed replay.** Single process throughout. Snapshot
  interchange between two *processes* (as opposed to two interpreters in one
  process) was not tested.
* **`OverflowPolicy` / bounded inbox under replay.** All runs used the default
  unbounded queue. Drop/block policies necessarily make order load-dependent;
  we did not measure how.
* **Hypothesis-driven random machine generation.** The machine shape is one
  hand-built fixture plus several minimal ones. A generated-machine campaign
  could find ordering cases the 13 hand-picked pairs miss.
* **`spawn` (as opposed to `invoke`) actor determinism**, and `sendTo` with a
  `delay`. The fixture uses an invoked child and a zero-delay `sendTo`.
* **Whether D-determinism-1's false-positive rate is bounded.** We showed it is
  nondeterministic and can reach 99.9 % in a crafted case; we did not
  characterise it as a function of traffic shape.
* **`PYTHONHASHSEED` beyond 0–5.** Six seeds; the brief specified 1–5 and we
  added 0 (randomisation disabled) as a control.

### Artefact index

| script | covers | output |
|---|---|---|
| `dmachine.py` | shared fixture: machine, logic, `TracePlugin`, script generator, canonical snapshot | — |
| `d1_replay.py` | §2 — 50×50 full-digest replay | `out/d1_replay.json` |
| `d2_receipt_deferred.py` | D-determinism-1 (unbounded growth) | stdout |
| `d2b_flag_instability.py` | D-determinism-1 (run-to-run instability) | stdout |
| `d2c_deferred_mechanism.py` | D-determinism-1 (minimal deterministic repro) | stdout |
| `d3_perturb.py` | §3.1 — jitter + 8 concurrent senders | `out/d3_perturb.json` |
| `d3b_p1_forensics.py` | §3.2 — jitter with no competing exit | `out/d3b_p1.json` |
| `d3c_abort_race.py` | **D-determinism-2** | `out/d3c_race.json` |
| `d4_ordering.py` | §4 — the ordering rules table | `out/d4_ordering.json` |
| `d5_hashseed.py` | §5 — runtime hash-seed dependence | `out/d5_hashseed.json` |
| `d6_cross_engine.py` | §2.2 — cross-engine, 5 scripts | `out/d6_cross_engine.json` |
| `d7_hook_parity.py` | **D-determinism-4** | `out/d7_hook_parity.json` |
| `d8_sync_invoke_timing.py` | **D-determinism-3** | `out/d8_sync_invoke.json` |
| `d9_snapshot_replay.py` | §6, **D-determinism-5** | `out/d9_snapshot.json` |
| `d10_concurrent.py` | §7 — T1/T2/T3 | `out/d10_concurrent.json` |
| `d10b_threadsafe_order.py` | **D-determinism-6** | `out/d10b_threadsafe.json` |
| `d11_construction.py` | §5 — build-time hash-seed dependence | `out/d11_construction.json` |
| `d12_after_timer.py` | §8 (D-determinism-3 control: timers alone are fine) | `out/d12_after_timer.json` |

### Defect summary

| id | severity | one line |
|---|---|---|
| **D-determinism-1** | **High** | `Receipt.deferred` is nondeterministic; `id()`-keyed set leaks and yields false positives (2 998/3 000 in a minimal repro) |
| **D-determinism-2** | **High** | Pure asyncio-scheduling perturbation changes the outcome — 11 distinct final contexts from one fixed script |
| **D-determinism-3** | **High** | A plain-sync `invoke` src completes inline on sync, task-deferred on async; the engines are not replay-equivalent |
| **D-determinism-4** | Medium | `SyncInterpreter.start()` fires an `on_transition` for the init event; `Interpreter.start()` does not |
| **D-determinism-5** | Medium | `from_snapshot()` takes no `clock=`; a restored interpreter is always on `RealClock` |
| **D-determinism-6** | Medium | `send_threadsafe()` schedules rather than enqueues, so it cannot be ordered against `send()` |
