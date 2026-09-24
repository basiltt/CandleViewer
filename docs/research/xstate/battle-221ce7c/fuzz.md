# FUZZ — fuzzing & property-based battle test of `xstate-statemachine` @ `221ce7c`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`221ce7c`** ("Merge pull request #178 from
basiltt/fix/157-loop-side-raise-observable"). `CHANGELOG.md`
`[Unreleased] — targeting 0.8.1`. **`__version__` still reports `0.8.0`; this
build is identified by commit.**

**Date:** 2026-09-20. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Track:** FUZZ, re-run of `battle-cec108b/fuzz.md` plus a new attack set aimed
at round 6's fixes (#166–#175, #157, #122-as-designed) and the hot-path perf
PRs #165/#176. Scripts live under `docs/research/xstate/battle-221ce7c/fuzz/`.
No library source was modified. No `git` command was run in the adopting
project's repository. GitHub was read-only throughout.

**Standard applied.** This library is being evaluated to run an
order-management system handling real money. Every silent failure,
nondeterminism and ordering ambiguity is treated as a defect and reproduced
before it is counted.

---

## 0. Bottom line

**Round 6 fixed the Blocker this track filed — for `plain def` services only.
The identical chart with an `async def` service is completely unbounded, and
that gap also produces a permanently empty configuration that no caller can
detect.**

- **D6-fuzz-1 is FIXED as filed.** The 8-line `m9_send_hang_min.py` repro now
  resolves in 0.00–0.20 s on every ablation, **0 hangs** where the prior round
  had 6/6. The macrostep settle budget is genuinely per-instance.

- **D7-fuzz-1 (Blocker) — the chain budget is never charged when the invoked
  service is an `async def`.** Same chart, same `maxIterations`, one-word
  change: `def svc` trips `RunawayChainError` at lap 22; `async def svc` runs
  **46 910 laps in 5 s at 98 % of one core with `last_error=None` and
  `last_transition_ok=True`** — for ever. `SyncInterpreter` trips at 22.
  `maxIterations` ∈ {None, 10, 20, 1000} makes no difference. The livelock
  fuzzer hits this on **223 of 500** generated configs while the sync engine
  settles **500/500**. Root cause is one line: `interpreter.py:2288`
  (`_deliver_priority`) charges the budget only `if self._processing`, and an
  `async def` service resolves on its own task *after* the entering macrostep
  has ended, so every lap arrives "free".

- **D7-fuzz-2 (Blocker) — `await send(EV, wait=True)` resolves with the
  configuration EMPTY, reporting success.** Shrunk automatically to a 12-line
  chart: `current_state_ids == []`, `last_transition_ok=True`,
  `last_error=None`, `status="running"`, and it **never heals**. 10/10 with an
  `async def` service, 0/10 with a `plain def` one — the same root cause. The
  machine is silently dead on the happy path; the only honest surface is
  `get_persisted_snapshot()`, which correctly refuses with
  `SnapshotMidStepError`.

- **D6-fuzz-2 is DOWNGRADED to an observation.** #171's fix works where it
  matters: the state after `start(); send("GO")` is now identical on both
  engines, **0/20 outcome divergence** (was 10/10). What still differs is the
  transient `current_state_ids` read *at* `start()`'s return (20/20) — a view,
  not an outcome.

- **Every other round-6 fix verified clean.** #169's entry/exit-window refusal
  holds over a **300-machine property run: 2 478 refusals, 300 legal
  snapshots, ZERO torn** — across `on_transition`, mid-action-list, and guard
  hooks on nested and parallel charts. #170's 4-way matrix discriminates
  exactly as documented (`CRASH`→`denied=False, error=ValueError`;
  `DENY`→`denied=True`; unhandled→`denied=False, error=None`). #172's in-flight
  counter balances at **0 after 800 threadsafe sends across 8 threads**.
  #157 fires `on_event_dropped(queue_full)` **1 278 times for 1 278 refused
  futures — exactly once each**. #173's `service_pool_size=1` carries 50
  services and survives `stop()` mid-service. #166's chain bound is **not**
  reset by 16 concurrent external senders (51 laps quiet, 51 laps under 29 389
  external events). Determinism is perfect and **cross-engine lap-parity holds**
  (both trip at 15 laps; hook matrix 1:1 on both engines). The #165/#176
  sentinel is **not** shared across machines — no aliasing.

- **The residue is one line, one engine, two Blockers.** Both defects below are
  the same missing accounting hop, and both are invisible to a `plain def`
  test suite — which is exactly what the round-6 regression tests use.

---

## 1. Method

### 1.1 What was re-run, and the reductions made

Hard bounds: ≤ 120 s per script, ≤ 20 min total. **Reductions, stated:**

| Script | Prior run | This run | Reduction | Justification |
|---|---|---|---|---|
| `repros.py` | full | **full** | none | Cheap; verbatim, 0/6. |
| `f2_events.py` | 800 | **800** | none | Same budget; found the same B2 class (6 hits) — which this round shrank to D7-fuzz-2. |
| `f3_snapshot.py` | 1 200 | **1 200** | none | **NO DEFECTS**, same as prior round. |
| `f1_machine_config.py` | 1 500 | **not re-run** | dropped | Its A1/A3 classes were established as *generator* staleness last round; the livelock budget was spent on `q5` instead, which is the sharper instrument for the same property. Noted in §6. |
| `n5_soak.py` (sync) | 5 min | **superseded** | — | Replaced by `q9_soak.py`, an **async** 8-min soak — §6.1 of the prior report named this the highest-value missing run. |
| new `q1`–`q14` | — | as briefed | — | 300-machine snapshot property, 500-config livelock fuzz, 50× determinism, 4-way semantics matrix, hook matrix, security probes. |

### 1.2 Oracle updates and harness bugs corrected before filing

Two harness faults were found and fixed *before* any defect was counted:

1. **`get_persisted_snapshot()` returns a `dict`, not a JSON string** (while
   `from_snapshot()` takes a string). `q2`'s first run reported an untyped
   `TypeError` from its own `json.loads`. The library was right. Corrected;
   the 300-machine result in §3 is post-fix.
2. **`q3.C1`'s "chain" was not a chain.** Its entry action self-sent on a state
   the machine never re-entered, so `n=1` and the "FAIL" was the harness
   measuring nothing. Rewritten as `q4_c1_chain.py` with a genuine
   action-re-sends-its-own-trigger loop; #166 then **passes**.

`common.py`'s `ALLOWED_*` tuples were not changed — `221ce7c` adds no new
exception class at these boundaries.

### 1.3 Adapting scripts that assumed superseded behaviour

| Prior script | What happens now | Adaptation |
|---|---|---|
| `m9_send_hang_min.py` | no longer hangs (the fix) | **Left unmodified.** Its `HANGS: 0` line is the evidence for D6-fuzz-1 = FIXED. |
| `n8_strict_targets_root.py` | still cannot set up (`RootTargetError` at line 13) | Left unmodified; the traceback is the evidence. |
| `m3_b2_replay.py`, `m4_b2_flaky.py` | depend on `out/b2_repro.json`, not regenerated by this run's `f2` | Superseded by `q10_b2_replay.py`, which extracts the repro from this run's own `out/f2_events.json`. |
| `n10_async_spin.py` | still burns a core | **Left unmodified** — it is now the oracle for D7-fuzz-1, not for D6-fuzz-1. See §3.1. |

### 1.4 Exact commands

```bash
cd docs/research/xstate/battle-221ce7c/fuzz
PY="_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

# prior-defect oracles
$PY -u repros.py                     # 0/6
$PY -u m9_send_hang_min.py           # D6-fuzz-1 -> HANGS: 0  (FIXED)
$PY -u m11_116_parity.py             # D6-fuzz-2
$PY -u n1_repro.py ; $PY -u n2_restore_untyped.py ; $PY -u n8_strict_targets_root.py
$PY -u n10_async_spin.py             # now the D7-fuzz-1 oracle
$PY -u f2_events.py   --cases 800
$PY -u f3_snapshot.py --cases 1200

# new work
$PY -u p1_nested_invoke_spin.py      # is the invoke cycle bounded on async?
$PY -u p2_depth_trace.py             # _raise_depth per lap -> always 0
$PY -u p3_mechanism.py               # blast radius: async def vs plain def
$PY -u q1_async_invoke_runaway.py    # D7-fuzz-1 MINIMAL repro
$PY -u q2_snapshot_hooks.py 300      # #169 property, 300 machines
$PY -u q3_concurrency.py             # #172 / #173 / #157
$PY -u q4_c1_chain.py                # #166 under 16 external senders
$PY -u q5_livelock_fuzz.py 500       # livelock fuzzer, both engines, 30s watchdog
$PY -u q6_determinism_semantics.py   # determinism, 4-way matrix, sentinel, security
$PY -u q7_start_parity.py            # D6-fuzz-2 outcome vs view
$PY -u q8_observability.py           # hook matrix, both engines
$PY -u q10_b2_replay.py              # replay this run's f2 B2 hit
$PY -u q13_torn_shrink.py            # automatic shrinker
$PY -u q14_torn_repro.py             # D7-fuzz-2 MINIMAL repro
$PY -u q9_soak.py 8                  # 8-min ASYNC soak, 200 machines
```

---
## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

`repros.py` verbatim: **0 of 6 runnable repros reproduce** (three more cannot
set up because the config is rejected at build — itself the fix).

| ID | Prior severity | Verdict | Evidence |
|---|---|---|---|
| **D6-fuzz-1** `await send(EV, wait=True)` never resolves and the async loop burns a core when an event re-enters a compound whose `always` descends into a child with a completed `invoke` | Blocker | **FIXED** | `m9_send_hang_min.py` verbatim: **`HANGS: 0`** (prior round: 6/6 hang). `maxIterations=1` resolves in 0.00 s, `=1000` in 0.20 s, external `GO` in 0.16 s, "no settle" in 0.17 s — every ablation that hung now returns, all landing in `['m.a.a']`. The sync baseline is unchanged (0.04 s, `RunawayChainError`). #166's per-macrostep instance budget works. |
| **D6-fuzz-2** #149's `service_executor` breaks #116 parity: a plain-`def` `invoke` in the initial entry set is complete when `start()` returns on sync, still pending on async | High | **CHANGED — downgraded to an observation** | `q7_start_parity.py`: the **outcome** now matches. `sync=(after_start=['m.b'], after_GO=['m.c'])`; async `after_GO=['m.c']` too — **0/20 outcome divergence** (prior round: 10/10 landed in `m.b`). #171's "completion awaited before the first inbox event is read" holds. What remains is the **transient view**: `current_state_ids` read *at* `start()`'s return is `['m.a']` on async vs `['m.b']` on sync, 20/20. `m11_116_parity.py` reports this as "divergent 10/10" but its own sample line now reads `(['m.a'], ['m.c'])` — the second element, the one that matters, agrees. **Not refiled.** See §3.4. |
| **D5-fuzz-1** nested `invoke`s whose `onDone` targets their common ancestor livelock the engine | Blocker | **FIXED on sync / STILL-PRESENT on async, refiled as D7-fuzz-1** | `n1_repro.py`: sync `start_alive=False` at `maxIterations` ∈ {None, 10, 1000}, settling in `m.a.a`. `n10_async_spin.py` is **unchanged from the prior round**: 160 378 events at t=12 s, **2.86–2.91 s CPU per 3 s wall**, RSS flat at 43 MB, `status=running`. `p1_nested_invoke_spin.py` adds the decisive datum the prior rounds lacked: `last_error=None` at every `maxIterations`. Root-caused in §3.1. |
| **D5-fuzz-2** `from_snapshot()` has untyped and silent paths | High | **still FIXED** | `n2_restore_untyped.py`: all 6 field mutations `SnapshotCorruptError`. `f3_snapshot.py --cases 1200`: **NO DEFECTS**, `C3.roundtrip_ok=199`. |
| **D5-fuzz-3** `strict_targets=False` reopens the #108 root-target hole | High | **still FIXED** | `n8_strict_targets_root.py` still cannot set up: `RootTargetError` from `validation.py:287`. |
| D-fuzz-3/4/5/6/8 (round-3 residue) | — | **still FIXED** | `repros.py` 0/6. |
| **F2 `B2-illegal-configuration`** (prior round: 6 hits, assessed as "a transient sample of the D6-fuzz-1 livelock") | (not filed) | **STILL-PRESENT and now filable** | `f2_events.py --cases 800` reproduces **6 hits** again. Last round the livelock made it unshrinkable; with the livelock fixed it shrinks cleanly to a 12-line chart and is a defect in its own right — **D7-fuzz-2**. §3.2. |

**Score: D6-fuzz-1 FIXED; D6-fuzz-2 downgraded; D5-fuzz-1's async half still
open and root-caused; the previously-unexplained B2 class promoted to a
Blocker.**

### 2.1 The two `n2` / `f3` residues, again not filed

`n2`'s `configuration=None -> LOADED SILENTLY` is the documented redundancy
with `state_ids` (assessed in rounds 5 and 6). `f3`'s
`C1.tamper_hash.accepted=6` is `machine_hash` tampering being tolerated when
the structural fields still agree — unchanged behaviour, previously assessed.
Neither is new; neither is refiled.

---
## 3. New attacks

`q2`–`q14`. Summary matrix; the two Blockers follow.

| # | Attack | Targets | Result | Observation |
|---|---|---|---|---|
| Q2 | **300 random machines** (40 % parallel, rest nested), `get_persisted_snapshot()` from `on_transition`, mid-action-list (context half-applied), and guard hooks | **#169** | **PASS** | `refused=2478 produced=300 **TORN=0** untyped={}`. Per site: `action` 1 689 refused / 0 produced, `guard` 189 refused / 0 produced, `on_transition` 600 refused / 300 produced. Every mid-action snapshot — the exact window #169 was filed for — is refused; every produced blob JSON-round-trips with a committed context. Refusal is *targeted*, not blanket. |
| Q3.C2 | `service_pool_size=1`, 50 plain services; then `stop()` mid-service | **#173** | **PASS** | 50 services carried, `status=running`, `threads=2`; `stop()` mid-service clean. The constructor kwarg exists and is honoured. |
| Q3.C3 | `send_threadsafe(internal=True)` × 800 across 8 threads | **#172** | **PASS** | `futures=800 unresolved=0 **in_flight=0**`. The done-callback balances on every terminal outcome; no leaked count. |
| Q3.C4 | `OverflowPolicy.RAISE`, `max_queue_size=2`, 16 threads × 80 against a 50 ms action | **#157** | **PASS** | `sends=1280 future_errors=1278 **hook queue_full=1278**`. Exactly one `on_event_dropped(queue_full)` per refused future — the shed rate is now visible to a fire-and-forget caller. |
| Q4 | Genuine self-generated RAISE chain (`limit=50`) under **16 concurrent external senders** | **#166 / #151** | **PASS** | quiet: 51 laps, `RunawayChainError`, `chain_budget` hook ×1. Under load: **51 laps** while 29 389 external events were applied. External traffic does **not** hand the chain a fresh budget. (`last_error` is later overwritten by the succeeding external events — correct, and why the lap count is the oracle.) |
| Q5 | **Livelock fuzzer, 500 configs × both engines, 30 s watchdog** — nested invoke cycles, `always` cycles, rollback+`onDone`, `sendTo` self-loops, `maxIterations` ∈ {None,1,5,20,1000} | #144/#151/#166 | **FAIL** | `sync:settled **500/500**`; `async:settled 277`, **`async:RUNAWAY 223`** (117 nested-invoke, 106 rollback+onDone). See §3.1. |
| Q6.D1 | 50× traces per engine on a tripping `always` cycle | determinism | **PASS** | `sync distinct=1 laps={15}` / `async distinct=1 laps={15}`, `cross_equal=True`, **`lap_parity=True`**. The trip point is identical on both engines — the parity #166 promised. |
| Q6.D2 | #165/#176 shared init/exit **sentinel aliasing**: two machines, compare `id()` of entry/exit lists and mutate one | #165, #176 | **PASS** | `shared=False`, four distinct ids. The perf PRs' sentinels are not aliased across machines; no cross-talk is possible. |
| Q6.S1 | **4-way matrix**: guard-crash vs denied vs deferred vs unhandled, `guardErrorPolicy=raise`, `onUnhandled=defer` | **#170** | **PASS** | `CRASH → denied=False, error=ValueError`; `DENY → denied=True, error=None`; `NOPE → denied=False, error=None`. `(denied, error is None)` discriminates all three exactly as the CHANGELOG documents. |
| Q6.S3 | Entry-window snapshot refusal at **child vs root** | **#169** | **PASS** | both `root_entry` and `child_entry` → `REFUSED:SnapshotMidStepError`. The "in flight alone refuses at the root" rule is in force at both depths. |
| Q6.X1 | `internal=True` **forgery** from a foreign thread (200 sends) | security | **PASS** | `in_flight=0`, `last_error=RunawayChainError`, `status=running`. A foreign thread claiming `internal=True` is charged to the chain budget and trips it — it cannot use the flag to buy unbounded self-generated work. |
| Q6.X2 | `__slots__` attribute surface | #165 | **observation** | the interpreter still has a `__dict__` and accepts arbitrary attributes. `__slots__` was applied for hot-path layout, not encapsulation; no security claim is broken. Not a defect. |
| Q8 | **Hook matrix both engines**: `chain_budget`, `unhandled`, exactly-once, ordering | #77, #153, #159 | **PASS** | sync `{chain_budget:1, unhandled:ignored:1}` laps=11; async **identical**: `{chain_budget:1, unhandled:ignored:1}` laps=11. `PARITY … SAME`. Exactly one `chain_budget` per trip on each engine. |
| Q10 | Replay this run's `f2` B2 hit, both engines, settle ∈ {0, 0.05, 0.3} | — | **FAIL** | `sync LEGAL/LEGAL/LEGAL` + `RunawayChainError`; `async settle=0` → **`TORN m.a.a:0`**; with a settle delay it is legal. Led to Q11–Q14. |
| Q11 | Is the torn configuration visible **after `send(wait=True)` has resolved**? | #102, #39 | **FAIL** | **40/40**. `ids=[]`, and `get_persisted_snapshot()` at that instant refuses (`SnapshotMidStepError` 40/40) — the persistence layer knows, the caller-facing API does not. |
| Q13/Q14 | Automatic shrinker → minimal repro | — | **D7-fuzz-2** | 12-line chart, 10/10. §3.2. |
| Q9 | **8-min async soak**, 200 machines (rollback+onDone, always-into-invoke, parallel, plain) + executor services + chaos snapshots | all | see §5 | |

---
### 3.1 D7-fuzz-1 — an `async def` service's completions are never charged to the chain budget; the async loop is unbounded — **Blocker**

**Found by:** `p1_nested_invoke_spin.py`, which asked the question the prior
two rounds never asked of `n10_async_spin.py` — not "does it spin?" but
**"does it ever trip?"**

```
sync  mi= None: start() 0.03s events=1003 last_error=RunawayChainError states=['m.a.a']
sync  mi=   10: start() 0.00s events=  13 last_error=RunawayChainError states=['m.a.a']
sync  mi= 1000: start() 0.03s events=1003 last_error=RunawayChainError states=['m.a.a']
async mi= None: events= 73030 cpu=4.86s/5s status=running last_error=None states=['m.a.a']
async mi=   10: events= 69988 cpu=4.78s/5s status=running last_error=None states=['m.a.a']
async mi= 1000: events= 67216 cpu=4.91s/5s status=running last_error=None states=['m.a.a']
```

`maxIterations=10` bounds the sync engine to 13 events and does not bound the
async engine at all.

**The discriminating variable is the service's `def` keyword.**
`p3_mechanism.py` runs three cycle shapes x three engine/service kinds:

| Shape | sync (plain) | async engine, **`plain def`** svc | async engine, **`async def`** svc |
|---|---|---|---|
| nested invoke `onDone`->ancestor | 23 laps, `RunawayChainError` | 22 laps, `RunawayChainError` | **41 558 laps in 6 s, trip=None** |
| invoke ping-pong `a`<->`b` | 22 laps, `RunawayChainError` | 22 laps, `RunawayChainError` | **43 591 laps in 6 s, trip=None** |
| single self-`onDone` (control) | 1 lap | 1 lap | 1 lap — bounded |

**Repro:** `q1_async_invoke_runaway.py`, five lines of config, one-word ablation.

```python
CFG = {"id": "m", "initial": "a", "maxIterations": 20, "states": {
    "a": {"invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m.b"}}},
    "b": {"invoke": {"id": "i2", "src": "svc", "onDone": {"target": "#m.a"}}}}}
async def async_svc(i, c, e): return {"ok": 1}   # RUNAWAY
def       plain_svc(i, c, e): return {"ok": 1}   # trips at 22
```

```
sync  engine, plain      svc: laps=     22         last_error=RunawayChainError
async engine, plain def  svc: laps=     22 in 5s   last_error=RunawayChainError ok=False  => bounded
async engine, async def  svc: laps=  46910 in 5s   last_error=None              ok=True   => RUNAWAY
```

**Root cause — one line.** `interpreter.py:2288`, in `_deliver_priority`:

```python
if self._processing:
    self._raise_depth += 1
self._priority_queue.append(event)
```

The docstring states the intent exactly: "Only a delivery from OUTSIDE a step
(a due timer firing on an idle loop, a task finishing later) is free — that is
external time, not the machine feeding itself." A **plain-`def`** service runs
on the executor and is joined by `_await_inline_services()` *inside* the
entering macrostep, so `self._processing` is `True` and the completion is
charged — the round-6 fix works. An **`async def`** service is a task on the
same loop; it resolves *after* the macrostep that entered the invoking state
has ended, so `self._processing` is `False` and the completion is "free". The
cycle is machine-self-generated work permanently classified as external time.

`p2_depth_trace.py` shows the consequence directly — 9 254 laps in one second,
`_raise_depth` **0 on every single one**, all three "is anything pending"
guards empty, so the `_raise_depth = 0` reset at `interpreter.py:1670` is
redundant and the `over = self._raise_depth > limit` test at
`interpreter.py:1547` is never true:

```
lap  event                depth  iq  pq  tsif
     done.invoke.i1           0   0   0    0
     done.invoke.i2           0   0   0    0
     ... (x9254, identical)
total laps in 1s: 9254      last_error: None
```

**Prevalence.** `q5_livelock_fuzz.py 500` — 500 generated configs, both
engines, 30 s watchdog:

```
sync:settled     500
async:settled    277
async:RUNAWAY    223      (nested_invoke 117, rollback_ondone 106)
```

**44.6 % of generated cycle-shaped charts are unbounded on the async engine
and 0 % are on the sync engine.** `always`-cycle and `sendTo`-self-loop shapes
are bounded on both — consistent with the root cause, since neither routes
through `_deliver_priority` from a detached task.

**Severity: Blocker.** A pegged core and an unbounded event loop, on charts
`create_machine()` accepts without a warning, with `last_error=None` and
`last_transition_ok=True` throughout — there is **no signal any caller can
poll**. It is invisible to a `plain def` test suite, which is what
`tests/test_round6_findings.py` uses, and invisible to the sync engine.

### 3.2 D7-fuzz-2 — `await send(EV, wait=True)` resolves with the configuration EMPTY and reports success — **Blocker**

**Found by:** `f2_events.py --cases 800`, the `B2-illegal-configuration` class
(6 hits) — the same class the prior round saw and could not shrink because the
livelock masked it. `q10_b2_replay.py` replays this run's own capture:

```
sync            ['LEGAL', 'LEGAL', 'LEGAL']           last_error=RunawayChainError
async settle=0     ['LEGAL', 'LEGAL', 'TORN m.a.a:0']    last_error=None
async settle=0.05  ['LEGAL', 'LEGAL', 'LEGAL']           last_error=RunawayChainError
async settle=0.3   ['LEGAL', 'LEGAL', 'LEGAL']           last_error=RunawayChainError
```

**The torn state survives the receipt.** `q11_receipt_torn.py` re-reads the
configuration *after* `await send(ev, wait=True)` has resolved — the caller's
"this step is complete" signal:

```
torn configuration visible after send(wait=True) resolved: 40/40
sample={'torn_after_receipt': ['m.a.a'], 'snapshot': 'REFUSED:SnapshotMidStepError', 'ids': []}
snapshot outcomes at the torn instant: {'REFUSED:SnapshotMidStepError': 40}
```

**Shrunk automatically.** `q13_torn_shrink.py` greedily deletes keys while the
property "a resolved `send` leaves `current_state_ids == []`" holds, reaching a
fixpoint at 215 bytes. **Repro: `q14_torn_repro.py`.**

```python
CFG = {"id": "m", "initial": "a", "states": {"a": {
    "initial": "a",
    "always": {"target": "#m.a.a.a"},
    "states": {"a": {
        "initial": "a",
        "invoke": {"id": "inv", "src": "svc"},
        "states": {"a": {"type": "final"}}}}}}}
```

No `on` handler, no guard, no `maxIterations`, no timer — an **unhandled**
event is enough.

```
sync (plain svc): [['m.a.a.a'], ['m.a.a.a'], ['m.a.a.a']]

== async engine, `plain def` service: EMPTY config 0/10 ==
    ('start', ['m.a.a.a'])
    ('GO', ['m.a.a.a'], 'ok=False', 'err=RunawayChainError', 'status=running')
    ('GO', ['m.a.a.a'], 'ok=False', 'err=RunawayChainError', 'status=running')

== async engine, `async def` service: EMPTY config 10/10 ==
    ('start', ['m.a.a.a'])
    ('GO', ['m.a.a.a'], 'ok=False', 'err=RunawayChainError', 'status=running')
    ('GO', [],          'ok=True',  'err=None',              'status=running')
    ('  snapshot-at-torn', 'REFUSED:SnapshotMidStepError')
    ('  +500ms heal?', [], 'status=running')
```

Read the third line carefully. The configuration is **empty**,
`last_transition_ok` is **`True`**, `last_error` is **`None`**, `status` is
**`"running"`** — and 500 ms later it is **still empty**. The machine is
permanently dead and every caller-facing signal reports health. Every
subsequent event is silently discarded.

**Same root cause, same one-word ablation:** 10/10 with `async def`, 0/10 with
`plain def`, which instead trips `RunawayChainError` correctly. The uncharged
completion arrives between the exit set and the entry set of the `always`
chain, and the loop treats the resulting no-leaf configuration as settled.

**The persistence layer is the only honest surface.** #169's mid-step guard
correctly refuses the snapshot 40/40 — the interpreter *knows* it is mid-step
while `send(wait=True)` is telling the caller the step finished successfully.
Those two facts cannot both be right.

**Severity: Blocker.** On an OMS: `await send("FILL", wait=True)` returns
successfully, the order machine is in no state at all, `last_error` is `None`,
and every later event vanishes. Silent, permanent, 100 % reproducible.

### 3.3 Why both defects are one fix

`_deliver_priority` must charge `_raise_depth` for a completion the machine
produced, regardless of whether the entering macrostep is still on the stack.
The distinction the code needs is not `self._processing` but "did this actor's
own invoke produce this event?". With that hop, D7-fuzz-1's cycles trip at
`maxIterations` exactly as the `plain def` ones do, and D7-fuzz-2's chain is
cut before it can strand the configuration — which is precisely what the
`plain def` column of every table above demonstrates.

### 3.4 What did *not* turn out to be a defect

- **D6-fuzz-2's residue** (§2): `start()`'s transient `current_state_ids` still
  differs across engines (20/20), but the **outcome** is identical (0/20).
  A view, not a semantic divergence. Worth a documentation sentence.
- **`__slots__` does not remove `__dict__`** (Q6.X2). A performance change, not
  an encapsulation claim.
- **`last_error` overwritten by later external events** (Q4). Correct: it is
  "the last transition's error", not a sticky fault register. The lap count is
  the right oracle for the chain bound.
- **`f3`'s `C1.tamper_hash.accepted=6`** and **`n2`'s `configuration=None`**:
  previously-assessed residues, unchanged (§2.1).

---
## 4. Defects filed this round

| ID | Severity | Title | Engine | Repro | Reproduced |
|---|---|---|---|---|---|
| **D7-fuzz-1** | **Blocker** | Completions from an `async def` service are never charged to the chain budget, so every self-generated invoke cycle is unbounded on `Interpreter`; `maxIterations` has no effect and `last_error` stays `None` | async only, `async def` services only | `q1_async_invoke_runaway.py` (5-line config, one-word ablation); mechanism `p2_depth_trace.py`, `p3_mechanism.py`; prevalence `q5_livelock_fuzz.py 500`; original oracle `n10_async_spin.py`, `p1_nested_invoke_spin.py` | **yes — 100 %**; `maxIterations` ∈ {None, 10, 20, 1000}; **223/500** generated configs |
| **D7-fuzz-2** | **Blocker** | `await send(EV, wait=True)` resolves with `current_state_ids == []`, `last_transition_ok=True`, `last_error=None`, `status="running"`; the machine never heals and silently drops every later event | async only, `async def` services only | `q14_torn_repro.py` (12-line config, shrunk by `q13_torn_shrink.py`); found by `f2_events.py --cases 800`; `q10_b2_replay.py`, `q11_receipt_torn.py` | **yes — 10/10** minimal, **40/40** on the generated case; 0/10 with a `plain def` service |

**file:line for both.** `interpreter.py:2288` — the `if self._processing:`
guard in `_deliver_priority` (defined at `interpreter.py:2277`). Supporting
sites that are correct but unreachable as a result: the budget test
`interpreter.py:1547` (`over = self._raise_depth > limit`), the trip handler
`interpreter.py:1569`–`1578`, and the chain-end reset `interpreter.py:1665`–
`1671`. The `plain def` path that works correctly is
`_await_inline_services()`, called from the run loop at `interpreter.py:1526`
and from `start()` at `interpreter.py:1811`.

Both defects are **one fix**: charge a completion produced by this actor's own
invoke regardless of whether the entering macrostep is still on the stack
(§3.3).

**Postable-text check.** Neither repro, nor any config, log line or identifier
quoted in this report, names the adopting project.

---

## 5. Soak

`q9_soak.py 8` — an **async** soak, the run §6.1 of the prior report named as
the highest-value missing coverage. 200 machines (rollback+`onDone`,
always-into-invoke, parallel two-region, plain), plain-`def` (executor)
services at `service_pool_size=4`, chaos snapshots on 20 random machines per
cycle at quiescence.

```
soak 8.0 min: events=4868400 snapshots=397134 restores=397134 chaos_refused=89706
  wall=480.0s cpu=452.3s (94% of one core) rss 32->186MB max=186MB
  violations=0 []
  CONTROL 5x async-def invoke cycle: cpu=4.9s/5.0s (97% of one core) trips=0/5
```

**4.87 M events, 397 134 snapshot round trips, zero invariant violations, no
machine left `running` and no livelock** across 8 minutes on the async engine.
The 89 706 `chaos_refused` are #169's mid-step guard firing correctly.

The **control group** is the point of the run. Five machines on the
D7-fuzz-1 shape consume **97 % of a core between them with 0/5 trips**, while
200 machines doing real work with plain services consume 94 % of a core and
stay bounded. The defect is not a soak-visible degradation; it is a cliff that
depends on one keyword.

**One observation, not filed: RSS grew 32 MB -> 186 MB over 8 minutes**
(monotonic, no plateau observed within the window). I did not isolate whether
this is the 397 134 snapshot dicts the harness creates and drops, interpreter
retention, or allocator behaviour, and the prior round's 5-minute **sync**
soak was flat at 1 MB of movement — so this is a genuine difference worth a
dedicated probe, but it is **not reproduced to a cause** and the financial-OMS
standard of this report forbids counting it. Listed in §6 as the top gap.

---

## 6. Not covered

Stated so the verdict is not read as stronger than the evidence:

1. **The soak's RSS growth is uncharacterised** (§5). An async memory probe
   with the snapshot chaos disabled, run long enough to see a plateau or a
   slope, is the single highest-value missing run for the next round.
2. **`f1_machine_config.py` was not re-run.** Its budget went to
   `q5_livelock_fuzz.py`, which tests the same non-termination property far
   more directly (and found 223 failures where `f1` historically found ~1 per
   233 cases). But `f1`'s *structural* generator covers config shapes `q5`'s
   four templates do not.
3. **`q5`'s async scoring is a 0.6 s sample, not a 30 s watchdog per case.**
   The watchdog bounds `start()`; the RUNAWAY verdict is ">5 000 events in
   0.6 s with no trip". That is decisive for the cases it flags, but a chart
   that livelocks only after several seconds would be scored `settled`. The
   223 figure is therefore a **lower bound**.
4. **`f2`/`f3` are at 800/1 200 cases**, as last round; rates are not
   comparable to the 4 000/5 000-case rounds.
5. **Deferred-replay and after-timer-callback snapshot sites were not
   reached.** `q2` covers `on_transition`, mid-action-list (entry/exit of
   nested and parallel) and guard hooks — 2 478 refusals. The two remaining
   briefed sites (inside deferred replay, inside an `after` callback) were cut
   for wall clock. #169's rule is uniform enough that I expect them to hold,
   but that is an expectation, not a result.
6. **Restore+resume *trace* parity was not run.** `q2` verifies that produced
   snapshots are legal and round-trip; it does not drive a restored machine
   through the same event sequence as a live one and diff the traces.
7. **`done-callback double-fire` was tested only via the balance invariant**
   (`in_flight == 0` after 800 sends, `q3.C3`). I did not instrument the
   callback to count invocations per future, so a double-fire that happens to
   balance would not have been caught.
8. **`PYTHONHASHSEED` sweep was not re-run.** Last round's result (`distinct=1`
   across seeds 0/1/12345) stands unchallenged; `q6.D1`'s 50x in-process runs
   are internally deterministic on both engines with full lap parity.
9. **Redaction of `get_snapshot`'s DEBUG log was not probed.** The security
   track covers it; `q6.X1`/`X2` covered forgery and the attribute surface
   only.
10. **Hypothesis is installed but unused**; `q2`, `q5` and `q13` use seeded
    `random.Random` generators and a hand-written greedy shrinker. Cases are
    reproducible (seeds 90210, 31337, 777) but not Hypothesis-shrunk.

---

## 7. Verdict

**Round 6's fixes are real, well-targeted and verify clean — and the async
engine is still NO-GO, for a narrower and sharper reason than last round.**

The positive result deserves to be stated first, because it is large. The
Blocker this track filed against `cec108b` is **genuinely fixed**: the 8-line
repro that hung 6/6 now returns in every ablation. #169's snapshot window holds
over **2 478 refusals and 300 legal snapshots with zero torn** across 300
random nested and parallel machines. #172 balances its counter at exactly zero
under 800 threadsafe sends. #157 fires its hook **1 278 times for 1 278
refusals — exactly once each**. #170's discriminator works on all three cases.
#166's bound survives 29 389 concurrent external events without being reset.
Determinism is total and, for the first time, the **trip point is identical on
both engines** — 15 laps and 15 laps, hook matrices 1:1. The perf PRs'
sentinels are not aliased. D6-fuzz-2 has been fixed where it counts. And an
8-minute async soak moved 4.87 M events through 200 machines with **zero
invariant violations**.

Against that: **the chain budget the whole round was built around is never
charged when the invoked service is an `async def`.** One keyword. The same
chart trips at lap 22 with `def` and runs 46 910 laps in five seconds with
`async def`, reporting `last_error=None` and `last_transition_ok=True` the
entire time. It affects **223 of 500** generated cycle-shaped charts. And the
same missing hop strands the configuration **empty and permanently dead behind
a successful `await send(..., wait=True)`** — the failure mode an
order-management system can least afford, because there is nothing to poll: no
exception, no error field, no status change, no hook.

The uncomfortable part is *why* this survived a round dedicated to exactly this
mechanism. #166/#167/#168 were each reproduced, fixed and pinned in
`tests/test_round6_findings.py` — with **plain-`def`** services. Every table in
§3 has a `plain def` column that passes. The regression suite cannot see this
class of defect, and neither can the sync engine, which is correct on all 500
fuzzer configs.

**Adoption recommendation for this track: NO-GO for the async engine; the sync
engine remains in good shape on every contract this track tests.** D7-fuzz-1
and D7-fuzz-2 are one fix at `interpreter.py:2288`. The regression suite needs
an `async def` variant of every round-6 cycle test before the next verdict —
otherwise the fix will be pinned by tests that would have passed without it.
