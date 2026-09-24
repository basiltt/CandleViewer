# FUZZ — fuzzing & property-based battle test of `xstate-statemachine` @ `6db65d8`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`6db65d8`** ("Merge pull request #191 from
basiltt/fix/0.8.1-round7"). `CHANGELOG.md` `[Unreleased] — targeting 0.8.1`.
**`__version__` still reports `0.8.0`; this build is identified by commit.**

**Date:** 2026-09-21. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Track:** FUZZ, re-run of `battle-221ce7c/fuzz.md` plus a new attack set aimed
at round 7's fixes (#179–#190, reopened #167/#168/#175). Scripts live under
`docs/research/xstate/battle-6db65d8/fuzz/`. No library source was modified.
No `git` command was run in the adopting project's repository. GitHub was
read-only throughout.

**Standard applied.** This library is being evaluated to run an
order-management system handling real money. Every silent failure,
nondeterminism and ordering ambiguity is treated as a defect and reproduced
before it is counted. **Every service-related check was run with both `def`
and `async def` services** — the lane round 7 was filed for.

---

## 0. Bottom line

**Round 7's headline fix is real and complete: the coroutine lane is now
charged, and both of this track's round-7 Blockers are gone. What round 7 did
not do is make the *shed* and *scheduling* sides of the same accounting
provenance-aware — and there the async engine still loses external events
silently and can starve an external producer indefinitely.**

- **D7-fuzz-1 is FIXED.** `q1_async_invoke_runaway.py` verbatim: the chart that
  ran 46 910 laps with `last_error=None` now trips at **21 laps with
  `RunawayChainError` on both service kinds**. `p3_mechanism.py`: all three
  cycle shapes bounded on all three engine/service combinations. The
  500-config livelock fuzzer settles **500/500 on every cell of the
  {sync, async} × {def, async def} matrix — 0 RUNAWAY, 0 unobservable trips**
  (prior round: 223/500 runaway).

- **D7-fuzz-2 is FIXED as filed, and CHANGED into a much smaller residue.**
  The permanently-dead empty configuration is gone: the same generated chart
  now **heals within 500 ms** and `RunawayChainError` is reported. But
  `await send(EV, wait=True)` still **resolves at an instant when
  `current_state_ids == []`, `last_transition_ok=True`, `last_error=None`** —
  7/15 on a 284-byte shrunk chart, `async def` only. Refiled at reduced
  severity as **D8-fuzz-1 (High)**.

- **D8-fuzz-2 (High) — an external `send(priority=True)` is still SHED by the
  chain budget, and the sender is told it succeeded.** #180 fixed the charge
  side by provenance; the *drop* test in the run loop is still positional, so
  an external event sitting in the priority lane when a self-generated chain
  trips is dropped as `chain_budget`. Measured end-to-end by an action
  watermark: **600 sent, 592 applied, 8 lost, `sender_ok=600`,
  `sender_err=0`** — `plain def` services only.

- **D8-fuzz-3 (High) — an `always`-into-invoke cycle starves external priority
  traffic permanently, with every health signal green.** 500 external
  `send(priority=True)` events, root-level handler so they match in every
  configuration: **1 applied**, 499 still queued, `status="running"`,
  `last_error=None`, no `on_event_dropped` — and **still stuck 10 s after the
  producer stopped**, at 70 % of one core. The sync engine applies 500/500.

- **Everything else round 7 built verifies clean.** The persistence property
  over **300 random machines × both engines × both service kinds** — including
  the initial descent (#182) and invoked children (#183) — is
  **7 752 refusals, 1 068 legal snapshots, ZERO torn**. `_chain_owed` under
  **100 never-completing coroutine services** settles to 0 and `stop()` is
  clean. #185's null/absent-hash rule holds on every versioned payload. #190's
  wildcard/strict matrix is exact on both engines. The 5-way receipt matrix
  discriminates all five cases **identically on both engines** for the first
  time. All four engine-completion **forgery** vectors are charged and trip.
  Determinism is total, including a **PYTHONHASHSEED sweep**.

- **The pattern.** Round 7 correctly redefined chain accounting as
  *provenance, not timing* — and applied that definition at the charge site
  only. The two new Highs are both places where the old *timing* rule
  survives: the shed test and the lane-scheduling order.

---

## 1. Method

### 1.1 What was re-run, and the reductions made

Hard bounds: ≤ 120 s per script, ≤ 20 min total. **Reductions, stated:**

| Script | Prior run | This run | Reduction | Justification |
|---|---|---|---|---|
| `repros.py`, `m9_send_hang_min.py`, `n1_repro.py`, `n2_restore_untyped.py`, `n8_strict_targets_root.py` | full | **full** | none | Cheap prior-defect oracles; verbatim. |
| `q1`, `q14`, `p1`, `p3` | full | **full** | none | The two round-7 Blocker repros and their mechanism probes. |
| `f2_events.py` | 800 | **800** | none | Same budget, comparable rate. |
| `f3_snapshot.py` | 1 200 | **1 200** | none | Same budget. **NO DEFECTS**, third round running. |
| `q2`–`q11` | full | **full** | none | Re-run as written; `q10`/`q11` re-pointed at **this** run's own `f2` capture via the new `r0_extract_b2.py` (they had been hard-wired to `221ce7c`'s). |
| `q5_livelock_fuzz.py` | 500 | **superseded by `r11`** | — | `q5` only ever ran (sync, `def`) and (async, `async def`); `r11` runs all four cells. `q5` was also run as-is: 500/500 settled both engines. |
| `q9_soak.py 8` (plain-`def` services) | 8 min | **superseded by `r15`** | — | The brief asks for an **async**-service soak with an external priority producer; `q9`'s pool deliberately excluded `async def` shapes because they were D7-fuzz-1. |
| `r15_soak.py` | — | **5 min, not 12** | **reduced** | Wall-clock budget. Stated in §5; the 30 s smoke run and the 5 min run agree on every criterion, and the RSS question is answered by the chaos-ON/OFF split rather than by duration. |
| `f1_machine_config.py` | not re-run | **not re-run** | dropped again | Same justification as last round: `r11` is the sharper instrument for the same non-termination property. Noted in §6. |
| new `r0`–`r20` | — | as briefed | — | Persistence property, snapshot-contract fuzz, concurrency, livelock matrix, determinism + hash-seed sweep, 5-way semantics, forgery, observability, soak. |

### 1.2 Harness faults found and corrected before any defect was counted

Four, all in our own code:

1. **`q10`/`q11` could not run** — they read `out/q10_cfg.json`, an artefact of
   the *previous* round that this run does not regenerate. Written
   `r0_extract_b2.py` to pull the B2 repros out of **this** run's
   `out/f2_events.json`. The §2 verdicts are post-fix.
2. **`r4` used `it.add_plugin(P())`** — no such method; the first run reported
   `refused=0 produced=0` and an `AttributeError`, i.e. it measured nothing.
   The API is `it.use(...)`. The 300-machine result in §3 is post-fix.
3. **`r13`'s sync arm used `it.send(ev)`** — `SyncInterpreter` returns a
   `Receipt` only with `wait=True`, so every sync field read `'?'` and looked
   like a cross-engine divergence. It is not one; see §3, S1.
4. **`r11`/`r20` sampled the async lap count at a fixed 0.6 s.** A merely slow
   chart was then scored with a truncated count and compared against the sync
   engine's complete one. Replaced with polling to quiescence. This removed
   roughly a sixth of the apparent parity mismatches — the rest are real and
   assessed in §3.7.

`common.py`'s `ALLOWED_*` tuples were not changed — `6db65d8` adds no new
exception class at these boundaries.

### 1.3 Exact commands

```bash
cd docs/research/xstate/battle-6db65d8/fuzz
PY="_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

# prior-defect oracles
$PY -u repros.py ; $PY -u m9_send_hang_min.py ; $PY -u n1_repro.py
$PY -u n2_restore_untyped.py ; $PY -u n8_strict_targets_root.py
$PY -u q1_async_invoke_runaway.py      # D7-fuzz-1 oracle
$PY -u q14_torn_repro.py               # D7-fuzz-2 oracle
$PY -u p1_nested_invoke_spin.py ; $PY -u p3_mechanism.py
$PY -u f2_events.py   --cases 800
$PY -u f3_snapshot.py --cases 1200
$PY -u q2_snapshot_hooks.py 300 ; $PY -u q3_concurrency.py ; $PY -u q4_c1_chain.py
$PY -u q5_livelock_fuzz.py 500 ; $PY -u q6_determinism_semantics.py
$PY -u q7_start_parity.py ; $PY -u q8_observability.py
$PY -u r0_extract_b2.py                # re-point q10/q11 at THIS run's capture
$PY -u q10_b2_replay.py ; $PY -u q11_receipt_torn.py

# new work
$PY -u r1_torn_characterise.py 0       # does the torn config heal now?
$PY -u r2_torn_shrink.py 0             # shrinker -> 284 bytes
$PY -u r3_empty_repro.py               # D8-fuzz-1 MINIMAL repro
$PY -u r4_persist_property.py 300      # #182/#183/#187 property, both engines+kinds
$PY -u r5_concurrency.py               # _chain_owed / #180 / children_timeout
$PY -u r6_ext_priority_charged.py 3    # D8-fuzz-2 isolation
$PY -u r7_ext_shed_mechanism.py        # D8-fuzz-2 mechanism
$PY -u r8_ext_shed_loss.py             # D8-fuzz-2 SILENT LOSS, end to end
$PY -u r9_snapshot_contract.py         # #185 / #186 / #190 matrices
$PY -u r10_186_asymmetry.py            # the #186 one-sidedness
$PY -u r11_livelock_matrix.py 500      # 500 x {def,async def} x both engines
$PY -u r12_determinism.py              # 50x traces + PYTHONHASHSEED sweep
$PY -u r13_semantics_security.py       # 5-way receipts + 4 forgery vectors
$PY -u r14_observability.py            # hook matrix, exactly-once
$PY -u r16_ext_loss_diagnose.py        # is soak EXT loss real?
$PY -u r17_ext_starvation.py           # instrument it
$PY -u r18_ext_starvation_repro.py     # D8-fuzz-3 repro + ablations
$PY -u r19_starvation_drain.py         # transient or permanent?
$PY -u r20_lap_parity.py               # is the parity gap real?
$PY -u r15_soak.py 5                   # 5-min ASYNC soak + priority producer
```

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

`repros.py` verbatim: **0 of 6 runnable repros reproduce** (three more cannot
set up because the config is rejected at build — itself the fix).

| ID | Prior severity | Verdict | Evidence |
|---|---|---|---|
| **D7-fuzz-1** completions from an `async def` service are never charged to the chain budget; every self-generated invoke cycle is unbounded on `Interpreter`, `maxIterations` inert, `last_error=None` | Blocker | **FIXED** | `q1_async_invoke_runaway.py` verbatim: `sync=22 laps/RunawayChainError`, `async engine + plain def = 21 laps/RunawayChainError`, **`async engine + async def = 21 laps/RunawayChainError`** (prior round: 46 910 laps, `last_error=None`). `p1_nested_invoke_spin.py`: async `mi=None` now **1 001 events at 0.27 s CPU per 5 s** with `RunawayChainError` (prior: 73 030 events at 4.86 s CPU, no error); `mi=10` bounds it to 11 events. `p3_mechanism.py`: all three cycle shapes bounded on all three engine/service combinations. Prevalence: `r11_livelock_matrix.py 500` — **0 RUNAWAY in all four cells** (prior: 223/500). |
| **D7-fuzz-2** `await send(EV, wait=True)` resolves with the configuration EMPTY reporting success, and never heals | Blocker | **FIXED as filed; CHANGED into a smaller residue → D8-fuzz-1** | `q14_torn_repro.py` verbatim: **0/10 with `async def`** (prior: 10/10) — the chart now reports `RunawayChainError` and stays in `['m.a.a.a']`. The *permanence* is gone. `r1_torn_characterise.py` on this run's own `f2` capture: the empty window still occurs 19/25, but **healed_in_500ms=19/19** and `last_error` becomes `RunawayChainError`. The surviving fact — a **resolved receipt at an instant when `current_state_ids == []` and every health field is green** — is refiled as **D8-fuzz-1 (High)**, §3.1. |
| **D6-fuzz-1** `send(wait=True)` never resolves; async loop burns a core | Blocker | **still FIXED** | `m9_send_hang_min.py` verbatim: **`HANGS: 0`**, every ablation resolves (0.00–1.08 s). |
| **D6-fuzz-2** #149/#116 start-parity | High (downgraded last round) | **unchanged observation** | `q7_start_parity.py`: **OUTCOME divergence 0/20 — PASS**; the transient `current_state_ids` read *at* `start()`'s return still differs 20/20. A view, not an outcome. Not refiled. §3.8. |
| **D5-fuzz-1** nested invokes whose `onDone` targets their ancestor livelock | Blocker | **FIXED on both engines** | `n1_repro.py`: sync `start_alive=False` at every `maxIterations`; async started and settled. The async half — which was D7-fuzz-1 — is gone (row 1). |
| **D5-fuzz-2** `from_snapshot()` untyped/silent paths | High | **still FIXED** | `n2_restore_untyped.py`: 6 of 7 mutations `SnapshotCorruptError`. `f3_snapshot.py --cases 1200`: **NO DEFECTS**, `C3.roundtrip_ok=199`. |
| **D5-fuzz-3** `strict_targets=False` reopens the #108 root-target hole | High | **still FIXED** | `n8_strict_targets_root.py` still cannot set up: `RootTargetError` from `validation.py:291`. |
| D-fuzz-3/4/5/6/8 (round-3 residue) | — | **still FIXED** | `repros.py` 0/6. |
| **F2 `B2-illegal-configuration`** | (D7-fuzz-2 last round) | **STILL-PRESENT, reduced** | `f2_events.py --cases 800` reproduces **2 hits** (prior: 6). Both shrink to the same transient-empty-configuration property; see D8-fuzz-1. |
| **`n2`'s `configuration=None` → LOADED SILENTLY** | never filed | **STILL-PRESENT, and now contradicts #186** | Previously assessed as documented redundancy. #186 now *claims* the two fields must agree, so this is no longer a redundancy — it is an exception to a stated rule. Filed as **D8-fuzz-4 (Medium)**, §3.4. |
| **`f3`'s `C1.tamper_hash.accepted`** | never filed | **STILL-PRESENT (5 hits)** | `machine_hash` tampering tolerated when structural fields agree. `r9`.A2 pins the exact rule: this is the **v0 bypass**, and on v0 it is intended. Not refiled; see §3.4 for the part of it that *is* a defect. |

**Score: both round-7 Blockers FIXED; D7-fuzz-2's residue refiled at High;
three new defects, none a Blocker.**

---

## 3. New attacks

`r1`–`r20`. Summary matrix; the three new defects follow.

| # | Attack | Targets | Result | Observation |
|---|---|---|---|---|
| R4 | **300 random machines × BOTH engines × BOTH service kinds**, `get_persisted_snapshot()` from `on_transition`, mid-action-list, guard hooks — charts include **parallel**, **invoked child machines** (#183) and entry actions **in the initial descent** (#182) | **#182 #183 #187** | **PASS** | `refused=7752 produced=1068 **TORN=0** untyped={}` (the one untyped entry is `NotSupportedError: service is async` on the sync engine — the library correctly refusing a coroutine service, not a defect). Per site: `action` 5 544 refused / **0 produced**, `guard` 396 refused / 0 produced, `on_transition` 1 812 refused / 1 068 produced. Per kind: `plain def` 4 404/600, `async def` 3 348/468. Every mid-action snapshot is refused on **both** engines — the asymmetry #182 was filed for is gone. |
| R5.C1 | **100 concurrent never-completing coroutine services**, then independent traffic, then `stop()` | **#179 `_chain_owed`** | **PASS** | `owed after start=100`, unchanged by 20 independent sends (so an outstanding long service does **not** keep a foreign chain open), `last_error=None` (no false trip), `stop()` **clean in 0.36 s**, **`owed_after_stop=0`**. The cancellation callback settles every debt; no leak, no hang. |
| R5.C3 | `start(children_timeout=0.5)`, **50 children** whose entry action sleeps 0.35 s | **#181** | **PASS** | `start()` returned in **0.37 s**, `status=running`, all 50 registered. `r14`.D pushes past the bound (entry 0.6 s, timeout 0.2 s): returns in **0.20 s** and logs the WARNING verbatim — `⏳ Interpreter 'p': 50 invoked child actor(s) still starting after 0.200s; start() returns with them in progress (#181).` |
| R9.A2 | **#185 matrix**: `version` ∈ {absent(v0), 0, 1, 2} × `machine_hash` ∈ {absent, null, wrong, correct} × `verify_machine_hash` ∈ {True, False} — 32 cells | **#185** | **PASS** | Every **versioned** payload (`version` 1 or 2) with an absent, null or wrong hash is refused `SnapshotDriftError`. `version: 0` with absent/null hash loads — that is the **declared v0 bypass**, exactly as #185 specifies ("the bypass is keyed on the declared version"). `verify_machine_hash=False` is the opt-out on every cell. 0 untyped. |
| R9.A3 | **#190 wildcard/strict matrix**, both engines: declared-only / wildcard-beside-declared / **wildcard-only** / wildcard-in-another-state × {declared event, undeclared event} | **#190** | **PASS** | 8 cells, **sync and async identical in all 8**. `UNDECLARED` raises `UnknownEventError` even when a `"*"` handler exists in the same state or elsewhere in the chart. Wildcard-only charts declare *nothing*, so even `GO` is refused — the declaration question, answered correctly. |
| R11 | **Livelock fuzzer, 500 configs × {plain def, async def} × {sync, async}, 30 s watchdog**, quiescence-polled — nested invoke cycles, `always` cycles, rollback+`onDone`, `sendTo` self-loops, **priority self-sends**, `maxIterations` ∈ {None,1,5,20,1000} | #179 #166 #151 | **PASS on termination & observability** | `async/asyncdef:settled **500**`, `async/plaindef:settled **500**`, `sync/plaindef:settled **500**`, `sync/asyncdef` 310 settled + 190 `NotSupportedError` (correct rejection). **`RUNAWAY = 0`** in every cell (prior round: 223). **P2 unobservable trips (>2 000 laps with no `last_error` and no drop hook) = 0.** P3 lap parity: 129/500 mismatches — assessed in §3.7 as a **Low observation**, not a defect. |
| R12.D1 | **50× identical traces per cell**, both engines × both service kinds, including trip lap counts | determinism | **PASS** | All four cells `distinct=1`, every one `(('t.a',), 6, 'RunawayChainError')`. `cross_engine_equal=True`; the trip lap count is **6 across the entire matrix**. |
| R12.D2 | **`PYTHONHASHSEED` sweep** (re-exec, seeds 0/1/12345) — skipped last round | determinism | **PASS** | `distinct results = 1`; identical sync and async tuples at every seed. |
| R13.S1 | **5-way receipt matrix**, both engines, both service kinds, `guardErrorPolicy=raise` × `onUnhandled` ∈ {ignore, defer, error} — guard-crash / denied / deferred / unhandled / error-kill | **#170 #153 #189** | **PASS** | 12 rows, **sync and async byte-identical on every one**. `CRASH → denied=False, error=ValueError`; `DENY → denied=True, error=None`; unhandled `NOPE → denied=False, error=None`; `onUnhandled="defer"` → `deferred=True` for both `DENY` and `NOPE`; **`onUnhandled="error"` → `error=UnhandledEventError` on the SENDER's receipt** — #189 holds, and it is the first round where this matrix is identical across engines. |
| R13.X1 | **Forge the engine-completion marker**, 4 vectors × both service kinds: an `Event` subclass typed `done.invoke.<id>`, `dataclasses.replace` on a captured `DoneEvent`, a plain `Event` with the completion type, and a replay of the captured `DoneEvent` — each driving a self-feeding chain | security | **PASS 8/8** | Every vector trips `RunawayChainError` with `chain_budget` drops. `DoneEvent` is **not a dataclass** and carries **no privileged non-payload field** — the "engine completion" mark is a keyword argument on an internal call path (`_deliver_priority(..., engine_completion=True)`), not data on the event, so there is nothing to forge. A user-issued event typed `done.invoke.x` is charged as a self-raise and bounded. |
| R14.A | `chain_budget` hook on the **async lane**, both engines, both service kinds | #77 #179 | **PASS** | `sync=1 / async=1` in both cells, `RunawayChainError` on all four. **Exactly-once and cross-engine parity, including the coroutine lane** — the cell that did not exist last round. |
| R14.B | **loop-side `RAISE` refusals** (#157): `max_queue_size=2`, `OverflowPolicy.RAISE`, 8 threads × 80 | **#157** | **PASS** | `futures=640 future_errors=638 hook queue_full=638` in both service-kind cells — **exactly one hook per refused future**, 0 call-site raises. |
| R14.C | **child mid-step snapshot refusal** (#183) | #183 | **PASS with a caveat** | The snapshot is refused `SnapshotMidStepError` from inside an invoked child's entry action on both service kinds — the tear is prevented. But the exception reports **`child=False`**, while #183 specifies `SnapshotMidStepError(child=True)` for a child caught mid-step. Filed as **D8-fuzz-5 (Low)**, §3.5. |
| R3/R1/R2 | Shrink and characterise the residual empty-configuration window | #179 | **D8-fuzz-1** | §3.1. |
| R6/R7/R8 | External `send(priority=True)` vs the chain budget's **shed** side | **#180** | **D8-fuzz-2** | §3.2. |
| R16–R19 | External priority traffic under an `always`-into-invoke cycle | **#180 #179** | **D8-fuzz-3** | §3.3. |
| R10 | **#186** `configuration` vs `state_ids` — one-sidedness | **#186** | **D8-fuzz-4** | §3.4. |

### 3.1 D8-fuzz-1 — `await send(EV, wait=True)` resolves at an instant when the configuration is EMPTY and every health field is green — **High**

**Lineage.** This is D7-fuzz-2's residue. The Blocker part is fixed: the
configuration is no longer *permanently* dead. What survives is the receipt.

**Found by:** `f2_events.py --cases 800` (`B2-illegal-configuration`, 2 hits),
extracted by `r0_extract_b2.py`, characterised by `r1_torn_characterise.py`,
shrunk 1 230 -> **284 bytes** by `r2_torn_shrink.py`. **Repro:
`r3_empty_repro.py`.**

```python
CFG = {"id": "m", "initial": "a", "maxIterations": 38,
       "after": {"17": {"target": "#m.a.c"}},
       "states": {"a": {"initial": "a", "always": {"target": "#m.a.a.a"},
           "states": {"a": {"initial": "a",
                            "invoke": {"id": "inv", "src": "svc"},
                            "states": {"a": {"type": "final"}}},
                      "c": {}}}}}
```

```
== sync engine, plain def svc ==
   [['m.a.a.a'], ['m.a.a.a'], ['m.a.a.a'], ['m.a.a.a'], ['m.a.a.a']]
== async engine, async def svc: EMPTY config 7/15 ==
     EMPTY  ok=True  err=None  status=running
     snapshot=REFUSED:SnapshotMidStepError
     +500ms ids=['m.a.c']
== async engine, plain def  svc: EMPTY config 0/15 ==
```

`await send(..., wait=True)` — the caller's "this step is complete" signal —
resolves at an instant when `current_state_ids == []`,
`last_transition_ok=True`, `last_error=None`, `status="running"`. On the
generated chart (`r1_torn_characterise.py`) it is 19/25 with the same
signature, and **19/19 of those heal within 500 ms**, at which point
`last_error` becomes `RunawayChainError`. `plain def` never reproduces it, on
either script.

**The persistence layer remains the only honest surface** — #169/#182's guard
refuses the snapshot with `SnapshotMidStepError` at that exact instant, 19/19.
The interpreter knows it is mid-step while the receipt tells the caller the
step finished successfully.

**Severity: High, reduced from Blocker.** An OMS that reads
`current_state_ids` (or routes on it) immediately after its own `await send`
sees "no state at all" behind a success-shaped receipt. It is no longer
permanent, no longer silently drops every later event, and the machine
recovers by itself — which is why it is not a Blocker. It is still a
success-shaped receipt over a torn read, on a chart `create_machine()` accepts
without a warning, with `async def` services, the style the docs recommend.

**file:line.** The receipt resolves before the `always` chain that is
re-populating the configuration has settled. The step's chain-end test is
`interpreter.py:1725`–`1735` (`_raise_depth` / `_chain_owed` / queue
emptiness); it does not include "the configuration has at least one leaf", and
the completion published by `_publish_completion` (`interpreter.py:2683`)
arrives between the exit set and the entry set of the `always` chain.

### 3.2 D8-fuzz-2 — an external `send(priority=True)` is SHED by the chain budget and the sender is told it succeeded — **High**

**#180 is only half-applied.** `_deliver_priority` (`interpreter.py:2342`)
decides *charging* by provenance, correctly:

```python
if engine_completion:          # interpreter.py:2375
    if self._chain_owed: self._chain_owed -= 1
    self._raise_depth += 1
self._priority_queue.append(event)
```

An external `send(priority=True)` is never charged — verified. But the
**drop** test in the run loop is still positional:

```python
over = self._raise_depth > limit      # interpreter.py:1598
...
elif over:                            # interpreter.py:1608
    self._chain_tripped = True
    for plugin in self._plugins:
        plugin.on_event_dropped(self, event, "chain_budget")   # :1623
    self._fail_receipt(event, "dropped: ... chain budget ...")
```

`event` here is **whatever `_next_event()` dequeued**, and `_next_event()`
drains the priority lane first. Once a self-generated chain has pushed
`_raise_depth` over the limit, an external priority send sitting in that lane
is dropped as `chain_budget` — the exact failure #105 fixed on the inbox lane
and #180 was filed to keep off this one.

**Isolation** (`r6_ext_priority_charged.py`, 12 000 external sends per cell;
`EXT` is an internal self-transition so it always matches):

```
  self-chain + plain def svc: sent=12000  EXTERNAL shed as chain_budget=55 (0.46%)  => FAIL
  self-chain + async def svc: sent=12000  EXTERNAL shed as chain_budget= 0 (0.00%)  => PASS
  NO chain   + plain def svc: sent=12000  EXTERNAL shed as chain_budget= 0 (0.00%)  => PASS
  NO chain   + async def svc: sent=12000  EXTERNAL shed as chain_budget= 0 (0.00%)  => PASS
```

Both ablations are necessary: a self-generated chain **and** a `plain def`
service. (The `async def` cell is spared here only because its chain trips at a
different instant — on the same lane it fails far worse; see §3.3.)

**The loss is real and silent.** `r8_ext_shed_loss.py` puts an action
watermark on the `EXT` handler, so "applied" is measured in the machine's own
context rather than inferred from a hook:

```
  plain def wait=True : sent=600 sender_ok=600 sender_err=0 APPLIED=599 LOST=1 => SILENT LOSS
  plain def fire&forget: sent=600 sender_ok=600 sender_err=0 APPLIED=592 LOST=8 => SILENT LOSS
  async def wait=True : sent=600 sender_ok=600 sender_err=0 APPLIED=600 LOST=0 => PASS
  async def fire&forget: sent=600 sender_ok=600 sender_err=0 APPLIED=600 LOST=0 => PASS
```

**600 sent, 592 applied, 8 lost, `sender_err=0`.** The `on_event_dropped` hook
does fire (8 times), so an application that installs a plugin *and* inspects
the dropped event's type can see the shed rate — but the sender's own
`await send(..., wait=True)` returns a success-shaped receipt for an event
that was never applied. `r7_ext_shed_mechanism.py` reproduces the same with
`maxIterations=3`: 300 receipts `ok`, one `EXT` shed.

**Severity: High.** On an OMS this is a `CANCEL` the caller was told landed. It
is rate-dependent (0.46 % at ~10 k/s), so it will not appear in a low-rate
test and will appear in production. The fix mirrors #180's: the drop test must
ask the same provenance question the charge site now asks — never shed an
event the machine did not generate.

**file:line.** `interpreter.py:1598` (`over = self._raise_depth > limit`) and
the shed block at `interpreter.py:1608`–`1651`, neither of which consults the
event's provenance; the correct counterpart is `interpreter.py:2375`.

### 3.3 D8-fuzz-3 — an `always`-into-invoke cycle starves external priority traffic permanently, with every health signal green — **High**

**Found by** the `r15` soak, which reported `EXT_LOST=11026` with
`ext_drop_hook=0`. `r16_ext_loss_diagnose.py` first ruled out the obvious
harness explanation by moving the `EXT` handler to the **root**, so it matches
in *every* configuration:

```
  plain              svc=plaindef: sent=4000 applied=4000 LOST=0     => PASS
  plain              svc=asyncdef: sent=4000 applied=4000 LOST=0     => PASS
  rollback_ondone    svc=asyncdef: sent=4000 applied=4000 LOST=0     => PASS
  always_into_invoke svc=plaindef: sent=4000 applied= 862 LOST=3138  => LOSS
  always_into_invoke svc=asyncdef: sent=4000 applied=   1 LOST=3999  => LOSS (99.97%)
```

`r17_ext_starvation.py` instruments it. The events are neither dropped nor
unmatched — **they are never dequeued**:

```
== svc=asyncdef, 500 GO + 500 EXT(priority) ==
   status=running  ids=['m.b.b2']  last_error=None
   ext applied (context) = 1
   EXT received=60   transitions=0   action_runs=1
   queue depths at end: inbox=499  priority=440  internal=0
   always-transition fires = 3042
== svc=plaindef, same chart ==
   EXT received=500  action_runs=486   queues: inbox=488 priority=1
```

**Minimal repro: `r18_ext_starvation_repro.py`**, 14 lines of config, with both
necessity ablations:

```python
CFG = {"id": "m", "initial": "a", "maxIterations": 50, "context": {"ext": 0},
       "on": {"EXT": {"actions": ["extbump"]}},        # root handler
       "states": {"a": {"on": {"GO": "b"}},
                  "b": {"always": {"target": "b2"}, "initial": "b2",
                        "states": {"b2": {"invoke": {"id": "s", "src": "svc",
                                    "onDone": {"target": "#m.a"}}}}}}}
```

```
  SYNC engine, plain def:  EXT sent=500 APPLIED=500 (100.0%)  status=running err=None drops={}
  async, plain def:        EXT sent=500 received=500 APPLIED=499 (99.8%)
  async, async def:        EXT sent=500 received= 73 APPLIED=  1 ( 0.2%)
                           status=running  last_error=None  drops={}
                           queues at end: inbox=499  priority=427

ablation A: drop the `always`  -> both kinds 500/500 applied, queues empty
ablation B: drop the `invoke`  -> both kinds trip RunawayChainError (bounded, observable)
```

Both elements are necessary, and neither alone is a defect: the `always` alone
trips the budget correctly; the invoke cycle alone drains correctly. Together,
the machine consumes its own transient chain in preference to 427 queued
**external** priority events.

**It is permanent, not a backlog.** `r19_starvation_drain.py` stops the
producer and watches for 10 s:

```
== async def: producer STOPPED after 500 GO + 500 EXT; watching drain ==
   t= 0.5s applied=1  inbox=499  priority=487  status=running err=None
   t= 5.0s applied=1  inbox=499  priority=416  status=running err=None
   t=10.1s applied=1  inbox=499  priority=372  status=running err=None
   after 10.0s idle: applied=1/500 inbox=499 priority=372 cpu=7.0s (70% of one core)
   => STUCK (permanent starvation)
```

Ten seconds of exclusive CPU after the producer stopped moved the priority
backlog from 487 to 372 and applied **zero** further external events. The
`plain def` cell is also stuck (`applied=482/500`, inbox 330, 79 % of a core),
so this is not purely a coroutine-lane defect — it is merely far worse there.

**Every health signal is green throughout:** `status="running"`,
`last_error=None`, `last_transition_ok` untouched, **no `on_event_dropped` of
any reason**, and the chain budget never trips, because each `always` re-entry
is a fresh macrostep that "raised nothing, armed nothing, owes nothing" by the
time the chain-end test runs. The only visible symptom is a pegged core.

**Severity: High.** A live-lock that swallows an order-management system's
external command stream while reporting perfect health is the failure mode
this evaluation exists to find. It is not a Blocker only because it requires a
specific chart shape (an `always` descending into an invoking child whose
`onDone` re-enters the ancestor) rather than affecting all charts — but `r16`
reached it from a *randomly generated soak pool*, so it is not exotic.

**file:line.** `interpreter.py:1573`–`1583` — `_next_event()` drains the
priority lane and the transient/`always` chain ahead of the inbox with no
fairness bound — combined with the chain-end reset at
`interpreter.py:1725`–`1735`, which clears `_raise_depth` on every lap.

### 3.4 D8-fuzz-4 — #186's "configuration and state_ids must agree" is one-sided: an emptied or removed `configuration` still loads — **Medium**

#186's stated rule: "`configuration or state_ids` let an emptied or rewritten
`configuration` silently win or silently lose; the two must agree or the blob
is refused with `SnapshotCorruptError`."

`r9_snapshot_contract.py`.A1 over 12 mutations, and `r10_186_asymmetry.py`
with a behaviour probe (restore, then send `NEXT` and see which leaf acted):

```
clean@c  configuration=['m','m.b','m.b.c']  state_ids=['m.b.c']

  baseline @c (untouched)                  -> loaded:['m.b.c'] then NEXT->['m.b.d']
  state_ids=[]  (config says m.b.c)        -> loaded:['m.b.c'] then NEXT->['m.b.d']  <== ACCEPTED
  configuration=None (state_ids m.b.c)     -> loaded:['m.b.c'] then NEXT->['m.b.d']  <== ACCEPTED
  configuration missing (state_ids m.b.c)  -> loaded:['m.b.c'] then NEXT->['m.b.d']  <== ACCEPTED
  state_ids missing (config says m.b.c)    -> refused:SnapshotCorruptError
  CROSS: config@d + state_ids@c            -> refused:SnapshotCorruptError
  CROSS: config@c + state_ids@d            -> refused:SnapshotCorruptError
  BOTH emptied                             -> refused:SnapshotCorruptError
  state_ids=[] AND configuration=None      -> refused:SnapshotCorruptError
```

The **cross** cases — the ones that matter most, where both fields are present
and name different leaves — are refused correctly, and that is #186's core
claim holding. But three disagreements load silently:

* `state_ids: []` beside a populated `configuration` — the literal "emptied
  ... silently lose" case #186 names;
* `configuration: null` and `configuration` absent — `state_ids` wins.

`state_ids` is the human-readable field and the one a hand-edit or a
serialisation round-trip through a system that drops empty lists is most
likely to clear. In every accepted case the restored machine then behaves
according to the surviving field, so the restore is not *corrupt* — it is
simply not the refusal #186 promises.

**Severity: Medium.** No torn state results; the machine restores to a
well-defined, consistent leaf. What is wrong is the contract: a blob whose two
configuration fields disagree is documented as refused and is not. An
integrity check that a tamperer or a lossy pipeline can bypass by *clearing* a
field rather than rewriting it is weaker than its documentation says. (This is
also the `n2_restore_untyped.py` residue — `configuration=None -> LOADED
SILENTLY` — which prior rounds correctly declined to file as a *redundancy*.
#186 converted it from a redundancy into an exception to a stated rule, which
is why it is filed now.)

**file:line.** `base_interpreter.py`'s snapshot-restore validation: the
agreement test is reached only when both fields are present and non-empty; an
empty or absent `configuration`/`state_ids` short-circuits to the other field.

### 3.5 D8-fuzz-5 — `SnapshotMidStepError` from an invoked child's entry action reports `child=False` — **Low**

#183 specifies: "a child on the caller's own thread is refused instantly with
`SnapshotMidStepError(child=True)`." `r14_observability.py`.C takes the
snapshot from inside an invoked child machine's entry action, both service
kinds:

```
C child=True snapshot refusal (#183)
   svc=plaindef: {'child': 'REFUSED child=False'}
   svc=asyncdef: {'child': 'REFUSED child=False'}
```

The refusal itself is correct and is the property that matters — no torn blob
is produced, and `r4`'s 300-machine property confirms this over 5 544
mid-action refusals including invoked children. Only the **discriminator** is
wrong: a caller cannot distinguish "my own machine is mid-step, retry in a
moment" from "a child actor is mid-step", which is the distinction the
`child=` flag exists to carry.

**Severity: Low.** Diagnostic fidelity, not correctness. Possibly our probe
reaches the root refusal path before the child path; I could not construct a
case in which `child=True` is observed, so it is filed at Low rather than
assessed as a harness artefact.

**file:line.** `base_interpreter.py:1423` — `exc = SnapshotMidStepError(self.id, child=True)` is
the site that *does* set the flag; the path our probe takes refuses earlier,
at the root in-flight check added by #182/#187.

### 3.6 Lap-parity across engines is close but not equal — **Low observation, not filed**

#179 claims "Both service kinds now trip at the same lap count as the sync
engine." `r11_livelock_matrix.py 500` found 129/500 configs where the totals
differ (`nested_invoke` 93, `rollback_ondone` 36), all with `plain def`
services. `r20_lap_parity.py` re-measures one config at a time with a fresh
counter, polled to quiescence, and prints the per-event histogram:

```
  nested_invoke   mi=20   sync laps=23   async laps=20   DIFFER
      sync  err=RunawayChainError ids=['m0.a.a'] hist={'done.invoke.i1': 12, 'done.invoke.i2': 11}
      async err=RunawayChainError ids=['m0.a.a'] hist={'done.invoke.i1': 10, 'done.invoke.i2': 10}
  nested_invoke   mi=1000 sync laps=1003 async laps=1000 DIFFER
  rollback_ondone mi=20   sync laps=21   async laps=21   SAME
  rollback_ondone mi=1000 sync laps=1001 async laps=1001 SAME
  configs=10 lap-parity mismatches=7
```

In **every** mismatch the two engines agree on the **outcome** (same final
configuration, same `RunawayChainError`); they differ by 2–3 laps in how many
completions land before the cut, and `rollback_ondone` converges exactly at
larger budgets. This is a constant-offset difference in when the trip is
detected, not a semantic divergence, and the financial-OMS property that
matters — bounded, observable, same end state — holds in all 500 configs.
**Not filed**, but it means #179's parity claim should be stated as "the same
bound and the same outcome", not "the same lap count".

### 3.7 What did *not* turn out to be a defect

- **`r5`.C2's first reading** showed external `EXT` events shed on the
  `async def` lane too. Keying the drop hook on `(reason, event type)` showed
  those were `done.invoke.i1` completions — correctly shed. The fixed probe is
  `r6`/`r7`/`r8`; only the `plain def` cell is a real defect (§3.2).
- **`r15`'s `EXT_LOST=224590`** is *not* 224 590 dropped events. `r16` showed
  the soak's charts do not handle `EXT` in every nested leaf, so most of that
  figure is correct non-matching. The part that is real is §3.3, reproduced
  separately with a root-level handler.
- **`q3`.C1 / `q4` "FAIL"** lines: `last_error` is overwritten by the
  succeeding external events, so `trip=None` under load. The lap count is the
  oracle and it is **51 quiet vs 51 under 30 598 external events** — #166
  holds. Previously assessed; the scripts' verdict strings are stale, not the
  behaviour.
- **`f3`'s `C1.tamper_hash.accepted=5`**: `r9`.A2 resolves this — it is the
  **v0 bypass**, keyed on the declared version exactly as #185 specifies.
- **`__slots__` still leaves a `__dict__`** (`q6`.X2): a hot-path layout
  change, never an encapsulation claim. Not a defect.
- **`sync/asyncdef: NotSupportedError` ×190** in `r11`: `SyncInterpreter`
  correctly refusing a coroutine service at build. Counted as a correct
  rejection, not a failure.
- **D6-fuzz-2's transient view divergence** (`q7`: 20/20 on
  `current_state_ids` at `start()`'s return, 0/20 on the outcome): unchanged
  from last round, still a view rather than a semantic difference.

---

## 4. Defects filed this round

| ID | Severity | Title | Engine / service kind | Repro | Reproduced |
|---|---|---|---|---|---|
| **D8-fuzz-1** | **High** | `await send(EV, wait=True)` resolves at an instant when `current_state_ids == []`, `last_transition_ok=True`, `last_error=None`, `status="running"`; heals within ~500 ms | async engine, `async def` only | `r3_empty_repro.py` (284-byte config, shrunk by `r2_torn_shrink.py`); found by `f2_events.py --cases 800` + `r0_extract_b2.py`; characterised by `r1_torn_characterise.py` | **yes — 7/15** minimal, **19/25** generated; 0/15 with `plain def`; 0/5 on sync |
| **D8-fuzz-2** | **High** | An external `send(priority=True)` is shed as `chain_budget` when a self-generated chain trips; the event is never applied and the sender's receipt is success-shaped | async engine, `plain def` only | `r8_ext_shed_loss.py` (watermarked, end-to-end); isolation `r6_ext_priority_charged.py`; mechanism `r7_ext_shed_mechanism.py` | **yes — 600 sent / 592 applied / 8 lost / `sender_err=0`**; 55/12 000 (0.46 %) at ~10 k/s; 0 in all three control cells |
| **D8-fuzz-3** | **High** | An `always` descending into an invoking child whose `onDone` re-enters the ancestor starves external priority traffic permanently; `status="running"`, `last_error=None`, no drop hook, 70 % of a core | async engine; both kinds, catastrophic on `async def` | `r18_ext_starvation_repro.py` (14-line config + both necessity ablations); permanence `r19_starvation_drain.py`; instrumented `r17_ext_starvation.py`; found by `r15_soak.py` / `r16_ext_loss_diagnose.py` | **yes — 1/500 applied** (`async def`), 482/500 and still stuck (`plain def`), **500/500 on sync**; still stuck 10 s after the producer stopped |
| **D8-fuzz-4** | **Medium** | #186's configuration/`state_ids` agreement rule is one-sided: `state_ids: []`, `configuration: null` and an absent `configuration` all load silently | both engines | `r10_186_asymmetry.py`; matrix `r9_snapshot_contract.py` A1 | **yes — 3 of 12** mutations accepted; cross-disagreements correctly refused |
| **D8-fuzz-5** | **Low** | `SnapshotMidStepError` raised from an invoked child's entry action reports `child=False`, so a caller cannot tell a child mid-step from its own | both service kinds | `r14_observability.py` C | **yes — 2/2**; the refusal itself is correct |

**file:line summary.**
D8-fuzz-1 — `interpreter.py:1725`–`1735` (chain-end test omits "configuration
non-empty"), with `interpreter.py:2683` (`_publish_completion`).
D8-fuzz-2 — `interpreter.py:1598` + the shed block `interpreter.py:1608`–`1651`
(positional, not provenance-based), vs the correct charge site
`interpreter.py:2375`.
D8-fuzz-3 — `interpreter.py:1573`–`1583` (`_next_event()` priority/transient
drain without a fairness bound) + `interpreter.py:1725`–`1735`.
D8-fuzz-4 — snapshot-restore validation in `base_interpreter.py`: the
agreement test is short-circuited when either field is empty or absent.
D8-fuzz-5 — `base_interpreter.py:1423`.

**D8-fuzz-2 and D8-fuzz-3 are the same architectural gap** as the one round 7
fixed, in the two places round 7 did not reach: #180 redefined chain
accounting as *provenance, not timing*, and applied that definition at the
charge site. The shed test (D8-fuzz-2) and the lane-scheduling order
(D8-fuzz-3) still run on the old *timing* rule.

**Postable-text check.** No repro, config, log line or identifier quoted in
this report names the adopting project.

---

## 5. Soak

`r15_soak.py 5` — an **async-service** soak with an **external priority
producer**, the configuration the prior round's soak deliberately excluded
(its pool had no `async def` shapes because those were D7-fuzz-1). 200
machines (rollback+`onDone`, `always`-into-invoke, parallel two-region,
plain), `async def` services, `service_pool_size=4`, chaos snapshots on 20
random machines per cycle at quiescence, and one external
`send("EXT", priority=True)` per machine per cycle.

**Reduction, stated: 5 minutes, not the briefed 12.** Wall-clock budget. A
30 s smoke run and this 5 min run agree on every pass criterion, and the RSS
question is answered by the chaos-ON/OFF split rather than by duration.

```
soak 5.0 min, ASYNC services, external priority producer:
  events=1239200 ext_sent=1239200 EXT_APPLIED=1014610 EXT_LOST=224590 ext_drop_hook=0
  snapshots=79035 restores=79035 chaos_refused=17845
  wall=300.0s cpu=293.7s (98% of one core) rss 33->108MB max=108MB
  RSS at chaos-OFF (t-60s) = 91MB -> end 108MB
  drops={}
  violations=0 []
```

**1.24 M events and 79 035 snapshot round trips in 5 minutes with zero
invariant violations, zero machines left non-`running`, and zero untyped
snapshot errors.** The 17 845 `chaos_refused` are #169/#182's mid-step guard
firing correctly on a live async engine. CPU is bounded at 98 % of **one**
core — no livelock at the pool level. This is a materially stronger soak than
the prior round's, because the services are now coroutines: the shape that
pegged a core with 0/5 trips last round is now the *normal* case and it stays
bounded.

**`EXT_LOST=224590` is not 224 590 dropped events** — `r16` established that
the soak's charts do not declare `EXT` in every nested leaf, so most of that
figure is correct non-matching. The residue that *is* real is D8-fuzz-3, which
this soak is what found; it is reproduced separately in §3.3 with a root-level
handler that matches in every configuration.

**RSS: the prior round's open question is now characterised.** Last round
reported an unexplained 32 → 186 MB climb over 8 minutes and could not
attribute it. This run splits the window: with chaos snapshots **ON** for the
first 4 minutes RSS reached 91 MB; with them **OFF** for the last minute it
went 91 → 108 MB. So the snapshot churn is *not* the driver — the slope
continues without it. 33 → 108 MB over 5 minutes at ~4 100 events/s, no
plateau observed. It remains **an observation, not a filed defect**: I did not
isolate it to interpreter retention versus allocator behaviour, and the
financial-OMS standard of this report forbids counting an unattributed
measurement. The 6 196-sample track is saved at `fuzz/out/r15_rss.json` for
whoever picks it up. It is §6's top gap for the second round running.

---

## 6. Not covered

Stated so the verdict is not read as stronger than the evidence:

1. **The soak's RSS growth is still uncharacterised to a cause** (§5), though
   it is now narrowed: it is *not* the chaos-snapshot churn. A run with
   `tracemalloc` or `objgraph` over a fixed machine pool, long enough to see a
   plateau, remains the highest-value missing probe.
2. **The soak ran 5 minutes, not 12.** Stated in §5 and §1.1.
3. **`f1_machine_config.py` was not re-run**, second round running. `r11` is
   the sharper instrument for the same non-termination property, but `f1`'s
   *structural* generator covers config shapes `r11`'s five templates do not.
4. **`r11`'s async scoring polls to quiescence within a 30 s watchdog**, which
   is a genuine improvement on `q5`'s fixed 0.6 s sample, but a chart that
   livelocks only after 30 s would still be scored `settled`. The `RUNAWAY=0`
   figure is therefore an upper bound on health, not a proof.
5. **`f2`/`f3` are at 800/1 200 cases**, as the last two rounds; rates are not
   comparable to the 4 000/5 000-case rounds.
6. **Deferred-replay and `after`-timer-callback snapshot sites were not
   reached.** `r4` covers `on_transition`, mid-action-list (including the
   initial descent and invoked children) and guard hooks — 7 752 refusals.
   The two remaining briefed sites were cut for wall clock.
7. **Restore-and-resume *trace* parity was not run.** `r4` verifies produced
   snapshots are legal and round-trip; it does not drive a restored machine
   through the same event sequence as a live one and diff the traces.
8. **D8-fuzz-5 may be a probe artefact.** I could not construct a case in
   which `SnapshotMidStepError.child` is `True`, so I cannot distinguish "the
   flag is never set" from "my probe always hits the root path first". Filed
   at Low with that stated.
9. **`10k/s` external sends were approximated** at ~7 400–9 900/s actual in
   `r5`.C2 (the loop cannot be driven faster from the same thread without
   starving it). `r6` uses a fixed 12 000-send count per cell instead, which
   is the figure quoted in §3.2.
10. **Hypothesis is installed but unused**; `r2`, `r4` and `r11` use seeded
    `random.Random` (seeds 90210, 31337, 777) and a hand-written greedy
    shrinker. Cases are reproducible but not Hypothesis-shrunk.
11. **`_chain_owed` was probed with 100 concurrent never-completing services,
    not under concurrent `stop()` racing with completions.** The debt settles
    and `stop()` is clean (§3, R5.C1), but a completion landing *during*
    `stop()` was not specifically targeted.

---

## 7. Verdict

**Round 7's central fix is genuine, and it is the largest single improvement
this track has measured. The async engine is no longer NO-GO for
non-termination — but it is not yet GO, because two of its accounting
promises are only half-implemented, and both fail in the silent direction.**

The positive result is substantial and should be stated first. The Blocker
that dominated the last report — an `async def` service's completions never
charged, `maxIterations` inert, 46 910 laps with `last_error=None`, **223 of
500** generated charts unbounded — is **gone**. The same chart now trips at 21
laps on both service kinds. The 500-config fuzzer settles **500/500 in every
cell of the {sync, async} × {`def`, `async def`} matrix**, with **zero
unobservable trips**. The second Blocker — a permanently empty configuration
behind a successful receipt — is fixed as filed; what remains heals in 500 ms.
The persistence property holds over **7 752 refusals and 1 068 legal snapshots
with zero torn**, now including the initial descent and invoked children, on
both engines and both service kinds. `_chain_owed` carries 100 never-
completing coroutine services and settles to exactly 0. Every one of the four
engine-completion forgery vectors is charged and trips — the "engine
completion" mark is a call-path keyword, not forgeable data. The 5-way receipt
matrix is **identical on both engines for the first time**. Determinism is
total across 50× runs, both engines, both service kinds, and a hash-seed
sweep. And a 1.24 M-event async soak with coroutine services ran with zero
invariant violations on one bounded core.

Against that, three Highs, and a pattern worth naming. #180 got the important
idea right: **chain accounting is provenance, not timing.** That idea was
applied at the charge site and nowhere else. The *shed* test still asks a
positional question, so an external `send(priority=True)` that happens to be
at the head of the priority lane when a chain trips is dropped as
`chain_budget` — 8 lost out of 600, with `sender_ok=600` and `sender_err=0`.
The *scheduling* order still has no fairness bound, so an `always` descending
into an invoking child consumes its own transient chain ahead of 427 queued
external priority events, indefinitely, at 70 % of a core, with
`status="running"`, `last_error=None` and no drop hook of any kind. Both are
silent losses of *external* traffic — the class of failure an order-management
system can least tolerate and least easily detect. And D8-fuzz-3 was reached
from a randomly generated soak pool, not constructed.

The encouraging difference from last round is that the regression suite can
now see this class of defect at all: `tests/test_round7_findings.py`
parametrises over `def`/`async def` and runs both engines, which is precisely
why D7-fuzz-1 and D7-fuzz-2 are actually fixed rather than pinned by blind
tests. What those 37 tests do not yet assert is the *external* side of the
accounting — that an event the machine did not generate is never shed, and
that queued external traffic always makes progress. Those two assertions are
what D8-fuzz-2 and D8-fuzz-3 would have caught.

**Adoption recommendation for this track: the sync engine remains in good
shape on every contract tested, across three rounds. The async engine is
CONDITIONAL — no longer NO-GO, not yet GO.** The condition is D8-fuzz-2 and
D8-fuzz-3: complete #180's provenance rule on the shed path, and put a
fairness bound between the transient/priority drain and the inbox. D8-fuzz-1
should be fixed in the same pass, since it is the same chain-end test. Until
then, an adopter on the async engine must avoid the `always`-into-invoke shape
entirely and must not trust a `send(..., wait=True)` receipt as proof that an
external command was applied.
