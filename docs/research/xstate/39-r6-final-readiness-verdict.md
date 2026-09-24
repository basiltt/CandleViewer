# 39 — Round-6 FINAL readiness verdict: `xstate-statemachine` main @ `cec108b` (unreleased 0.8.1)

Date: 2026-09-20. Question asked by the owner: *"Verify all reported issues are genuinely closed; is the library completely ready, fully battle-tested, and are we good to proceed?"*

**Identify this build by commit, never by version string.** `__version__` still reports `0.8.0` on `cec108b` (merge of PR #164, `fix/0.8.1-round5`) while `CHANGELOG.md` targets 0.8.1. Every pin, gate baseline and CI assertion keys on the commit.

Method: 26 issue verifications (round-5 fixes #142–#162 plus the five narrow reopens #118/#122/#125/#133/#134), full regression sweep (238 standalone scripts + the 89-check gate), library suite + coverage, benchmarks, diff review `3ed3099..cec108b`, all 8 battle tracks re-run with new attacks, all 20 contract machines driven end-to-end, then triage → dedupe → **independent adversarial refutation of every Blocker and High**. Register of record: `38-r6-findings-register.md`; refutations: `39-r6-01-refutation.md`, `39-r6-05-refutation.md`, `battle-cec108b/semantics/R6-06-refutation.md`, `battle-cec108b/contracts/R6-02-refutation.md`, `battle-cec108b/contracts/r6-09-refutation.md`, `battle-cec108b/refutation/`.

---

## 0. The answer

**Are the 26 reported issues genuinely closed? — Yes, 24 of 26.** One is **PARTIAL** (#122 — `tick()`'s contract is now documented and zero-delay chains and `SimulatedClock` ladders drain correctly, but the original `RealClock` real-delay-ladder repro still exits 1; the literal repro-passes criterion is unmet) and one is **NOT-FIXED** (#157 — `send_threadsafe`'s `qsize()` pre-check is still TOCTOU-racy; see the refutation caveat in §5, which *narrows* rather than clears it). Two closures carry a documented scope caveat: **#144** is fixed and pinned on the **sync engine only** (the same nested-invoke cycle is unbounded on async — that is R6-01/R6-02), and **#161** validates dict-event *key shape* only, by design. Fix quality across six rounds remains high; the failure mode of this round is **scope**, not correctness.

**Is the library fully battle-tested and ready? — Not for the order path.** After independent refutation the round leaves **2 Blocker · 2 High · 7 Medium · 9 Low** live library defects. Both Blockers are the same shape and both are **async-engine-only**, with the sync engine demonstrably correct:

- **R6-01** — `await send(..., wait=True)` never resolves and the loop burns a core when an event re-enters a compound whose `always` descends into a child with a completed `invoke`. 23 064 `_process_event` calls in 3 s, `qsize` pinned at 1, `status` still `"running"`. #144's "a chain ends only when nothing self-generated remains" rule shipped in `sync_interpreter.py` only.
- **R6-03** — `actionErrorPolicy: "rollback"` + `invoke.onDone` re-arms the invoke for ever: **2 859 service invocations in 2.0 s** for one user-visible event, `status="running"`, `.error is None`, `last_transition_ok=True`, and **no budget is charged** even at an explicit `maxIterations=5`. `rollback` is CandleViewer's mandatory policy (CV-C31) and `invoke.onDone` → entry-actions is a shape four of five machines in one catalogue group carry.

Neither is wrappable: a wrapper cannot observe a livelock that reports `running` / `error=None` / `last_transition_ok=True`, and for R6-03 the re-invoked service is a *side-effecting* one (order placement, payment capture) called ~1 400×/s.

**Are we good to proceed?**

- **Non-order paths (B10–B17, B19, B20 — recording, replay, connection, ingestion supervision, paper matching, auth, live-enablement, reconciliation, risk lockout): YES, proceed now**, under the constraints recomputed in §7. Every Blocker is on a shape those machines do not use (no `always`-into-invoked-child, no `rollback`+`invoke.onDone` entry-action raise), and both Highs are mechanically mitigated (CV-C23 quiescence-only snapshots covers R6-06; CV-C35 caps `always` fan-in for R6-02). B16–B20 drove **0 new library defects** this round.
- **Order path (B1–B9, B18): NO — DEFER.** Two independent Blockers, each sufficient on its own.

**What blocks, and whose it is.** The block is **UPSTREAM** and is now a single, precisely stated defect class: **the async engine does not share the sync engine's chain/macrostep termination accounting.** Concretely — (a) `interpreter.py:1427` exempts *all* system events from the chain budget (`not is_system_event(event)`), where `sync_interpreter.py:770-828` spares a completion only at the moment of the trip; and (b) the async macrostep-termination condition in `_run_event_loop` never concludes a self-generated `always` chain once its invoke has completed. Deleting the exemption and porting #144's termination rule to `interpreter.py` closes R6-01, R6-02 and R6-03 together. **That is one change, not three patches.** Nothing on our side blocks; our remaining work (catalogue defects C-04/C-07b/C-06/C-07, wrapper obligations W-01…W-04) is ticketed and does not gate the non-order GO.

---

## 1. The 26 issues

| Result | Issues |
|---|---|
| **FIXED — confirm closed (22)** | #118 #125 #133 #134 #142 #143 #145 #146 #147 #148 #149 #150 #151 #152 #153 #154 #155 #156 #158 #159 #160 #162 |
| **FIXED with a documented scope caveat (2)** | **#144** — fixed and pinned on `SyncInterpreter` (`tests/test_round5_findings.py:331`); the identical nested-invoke `onDone` cycle is **unbounded on the async engine** (34 k invocations / 2 s). Not a false positive in the existing pin — a gap beside it, filed as R6-01/R6-02. · **#161** — dict-event *key-shape* validation (non-`str` key/type, empty type, missing type) all raise `InvalidEventError`; value-level validation is intentionally out of scope per the documented fix. |
| **PARTIAL — reopen narrowly (1)** | **#122** — `tick()`'s one-deadline-per-call contract is documented and zero-delay chains plus `SimulatedClock` ladders drain correctly, but the original `RealClock` real-delay-ladder repro still exits 1. The change is a doc fix, not a drain-loop fix. |
| **NOT-FIXED — reopen (1)** | **#157** — `send_threadsafe`'s `qsize()` pre-check is a TOCTOU race. Refutation narrows the *claim*: nothing is accepted-then-lost (the authoritative check is `_enqueue()` on the loop, max observed depth 0 against a bound of 3, 497/500 refused correctly). The surviving defect is that the loop-side `RAISE` refusal lands on a future fire-and-forget producers never read, with **no log and no `on_event_dropped`** — correct load shedding with a hidden shed rate. Reopen at Medium on that narrower ground (R6-05). |

Three prior-round "FAIL" signals were re-classified as **stale harness artefacts, not regressions**: #134's original repro (stale-detection), #159's repro (substring-match heuristic), and `LC-01` (asserts the pre-#145 `status == "error"`; the code is right and the `plugins.py` docstring is the stale artefact — R6-20).

---

## 2. Regressions

**Three confirmed, all Medium, all deterministic (5/5), none Blocker-class.** The gate flagged four PASS→FAIL deltas vs the last full baseline `5e07ba8`; triage removed one.

| # | Item | Verdict |
|---|---|---|
| 1 | **LC-01** — `actionErrorPolicy:"fail"` ends `status="stopped"`, not `"error"` | **NOT a regression (H-1).** #145 deliberately changed this and the CHANGELOG says so; the script copies the stale `plugins.py:201-202` docstring. Kept as **R6-20** (Low, doc defect) and a harness refresh. |
| 2 | **LC-26 → R6-14** (Medium) | **TRUE REGRESSION.** `AfterEvent` timestamp *fields* are fixed (#118), but under a 100-iteration busy loop lateness is **88–92 ms against a 50 ms budget**. The per-macrostep settle budget does not bound *lateness* under load. Pre-existing constraint BENCH-6 already covers this for us. |
| 3 | **N-1 case D → R6-15** (Medium) | **TRUE REGRESSION.** Cases A/B/C of the duplicate-`Event`-instance collision bug are genuinely fixed; `stop()` no longer resolves *every* outstanding duplicate-instance receipt with `InterpreterStoppedError` — some racing events settle as ordinary `Receipt(changed=True, …)`. |
| 4 | repro/LC-26 | Secondary copy of #2, folded in; not counted separately. |

Everything else FAIL at `cec108b` (LC-12, LC-48, LC-57, PROBE-01/03, `149/150/157/probe_144`, the R4-*/R5-* post-* repros, `c14`, `f_loader_dup`, `86_87`, `fv1_blockers_highs`, `r4merge/m5`) was already FAIL at the immediately preceding baseline `3ed3099` or is a previously-confirmed register finding — superseded behaviour, not new. `f_loader_dup` and `fv1_blockers_highs` are **expected FAILs**: round-5 fix-confirmation scripts whose "the defect reproduces" assertion now fails *because* the new `InvalidConfigError` / `RootTargetError` guards fire (H-4).

**Suite / coverage:** `3399 passed, 13 skipped, 0 failed` in 9 m 02 s (**+77 vs `3ed3099`**); coverage **92.77 %** against PR #163's new 90 % floor — passes with +2.77 pts headroom. `tests/test_round5_findings.py` carries **52** test functions, matching the CHANGELOG exactly. `PYTHONHASHSEED` 1 vs 2: 98/98 identical, no order sensitivity.

---

## 3. Battle-test scorecard (`cec108b`, post-refutation)

| Track | Round-5 defects | Now | New defects (final severity) | Coverage this round | Verdict |
|---|---|---|---|---|---|
| **Persistence** | 1 B (R5-01), 1 H, 2 M | **all FIXED at the root** — `_configuration_is_legal` is exactly-one-leaf-per-region on both sides; `n3_parallel_tear 300`: **0/179 torn** (was 49/179 = 27.4 %) | R6-06 (**High**), R6-16 (L) | 2 000 events × snapshot+restore at every quiescent point = **2000/2000 OK**; `m1` 1 217 snapshots over 350 random parallel machines, 0 raises | **PASS with one caveat** (entry-action window) |
| **Concurrency** | 1 B, 2 H, 1 M | **all FIXED** — 300-case Hypothesis property, 879 quiescent snapshots, 0 failures; 5 000 mutations → 0 raw builtins; `_die` idempotent | R6-11 (M), R6-12 (M), R6-13 (M) | Hypothesis 300 cases + 16-thread RAISE contention | **PASS** |
| **Fuzz** | 3 (1 B, 2 H) | **all FIXED** — sync livelock gone, restore paths typed (5000→typed 5000/untyped 0), `RootTargetError` 8/8 | **R6-01 (Blocker)**, R6-02 (High) | 8-line minimal repro + 4 necessity ablations | **FAIL** — async run loop |
| **Determinism** | 3 | **all FIXED** | none (one false alarm — `taken_at` is a wall clock, an intentional non-invariant) | seeded property fuzzer + `internal=True` forgery | **PASS** |
| **Semantics** | 2 H, 1 M | 3 of 4 FIXED; 1 STILL-PRESENT | R6-06 (High, carried), R6-10 (M) | prior 32/34 + new 32/33 across 6 groups | **PARTIAL** |
| **Observability** | 1 H, 3 M | **all FIXED**; `on_event_dropped` at `stop()` now fires 5/5 | R6-08 (L), R6-20 (L) | reduced (no Hypothesis/soak this pass — stated, not silent) | **PASS with a reduced-coverage note** |
| **Security** | 2 M | redaction **FIXED both halves** (17/17 keys, DEBUG log redacted); dict-event boundary **resolved by design** (#161) | R6-07 (L), R6-04 (L) | fuzz reduced 5 000 → 300 (time-bound); D-security-2/3/4 carried forward, **not re-verified** | **PASS** |
| **Soak (1.5 min / 30 machines, reduced)** | 1 M | **FIXED** — 6/6 hostile fields typed | none | heavily reduced from 25 min/200 machines — **stated gap** | **PASS at reduced scale** |

**Diff review `3ed3099..cec108b` (`37-r6-diff-review.md`)** contributed R6-02 (the `interpreter.py:1427` exemption read directly out of the diff), R6-12 and R6-17, and confirmed PR #141's hot-path work is behaviour-neutral and PR #163's coverage gate is real.

**Benchmarks.** `bench_a` raw `send()` **238 004 ev/s** (4.20 µs), pure API 37 479 ev/s, lockstep-5000 p95 **45.9 µs**. `bench_h`: 500 open orders fill-latency **p95 0.057 ms** vs a 0.10 ms budget (**PASS**), 3.096 KB/open-order, no leak. `bench_j` policy ratios (rollback 0.736×, defer 1.131×) sit inside the documented noisy band — **no regression**. **BENCH-2 still missed**: rule fan-out 410/s async, 342/s sync against a 2 000 ev/s target — a known scaling limit, unchanged, nothing in #142–#162 touched it. **`bench_c_timers` (loaded drift) did not complete inside the wall-clock budget and was killed — a gap in this report, not a finding**; R6-14 is the independent lateness evidence.

---

## 4. Contract machines (B1–B20) on the library

**All 20 machines build from the corrected catalogue JSON with zero `InvalidConfigError` and zero `ImplementationMissingError`, and drive their invariants end-to-end.**

| Group | Build | Invariant checks | `SnapshotMidStepError` at quiescence | New **library** defects | Verdict |
|---|---|---|---|---|---|
| B1–B5 (order core) | 5/5 clean | B1 **23/23**, B2 14/14, B3 14/14, B5 16/16, **B4 9/11** | **0** across every macrostep of all five | 1 (CV-CEC-01 → merged into R6-09) | **PASS** — B4's 2 failures are **ours** |
| B6–B10 | 5/5 clean | **53/55**; round-5 analogues **7/7**; cross-machine reconnect **4/4**, byte-identical to the `3ed3099` baseline | 0 | 0 | **PASS** — of the 2 failures, one is a stale harness assertion (H-3), one is ours (CD-03) |
| B11–B15 | 5/5 clean, JSON byte-identical to the baseline | all stated invariants pass; **32/32** snapshot/restore cycles clean; 5/5 engine parity | **0** | 3 (LIB-R6-01/02/03 → R6-03, R6-05, R6-16) | **PASS functionally**, exposed to R6-03 |
| B16–B20 (control) | 5/5 clean from the **re-extracted** catalogue (round-5 CV-C31/C34 corrections; the `battle-3ed3099` copies are stale and were not used) | 46 scenarios; 9 snapshot-every-macrostep runs, traces **9/9** equal to the uninterrupted run | **0** | **0 new** | **PASS** |

So: **B10–B17, B19, B20 PASS on the library. B1–B9 and B18 pass functionally but are exposed to R6-03** (`rollback` + `invoke.onDone`, which our mandatory config requires) **and R6-01**.

### Our-contract and wrapper items (library is correct in every row)

| ID | Sev | Machine | Issue |
|---|---|---|---|
| **C-04** | **Blocker (ours)** | B16 | Elevation survives `LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE` and can be acquired after `REVOKE` — the `elevation` region declares only `REVOKE`. Correct SCXML parallel semantics; our JSON is wrong. |
| **C-07b** | **Blocker (ours)** | B18 | `onUnhandled:"error"` makes a guard-denied `RELEASE` terminal — the kill switch is bricked by a wrong button press. |
| CV-B4-01 | High | B4 | `LEG_B_FILL` declared only on `racing`; `completing`/`completed` don't declare it, so it re-defers for ever and `filled_b=0` in a terminal OCO. Patch confirmed. Identical at `3ed3099` — not a regression. |
| CD-03 | High | B8 | `naked ⇄ verifying` unbounded invoke livelock (523 laps/s). Our shape — but **R6-02 is why it is silent on async**. |
| C-06 | High | B19 | `stale_lockout` declares only `RECONNECTED`; `OPERATOR_RESOLVED` defers for ever; `page_owner` re-pages on every retry of a flapping link. |
| C-07 | High | B16–B20 | CV-C31 withdrew `fail` for `rollback` + explicit `halted` states; **the `halted` states were never added**, so a failed `locked` entry rolls B20 back to `clear` (tag `trading_allowed`) with no record. |
| OUR-B11-01 | High | B11 | `degraded` declares no `STREAM_UNHEALTHY`; one-line JSON fix. |
| OUR-B14-01 | High | B14 | INV-B14-d's "bounded" pending-delta buffer is prose-only: 1000 deltas → 1000 buffered, 1:1. |
| W-01 / C-01 | High | all | `create_machine` is not a conformance gate — all machines build with a bare `MachineLogic()`. Wrapper must validate the logic table against the JSON at construction. |
| W-03 | High | B17 | A deferred `ENABLE_REQUESTED` auto-fires the moment evidence lands, reaching `enabled` unattended. |
| W-04 | High | all | Wrapper must read `(denied, error is None)` — not `denied` alone (R6-10) — and keep guard-denied events out of the defer buffer. |
| CV-B8-01 · CV-B3-01 · W-02 | Medium | B1/B8, B3, B16 | No `stateIn` guard enforcing native-SL-before-position; `place_tp_ladder_once` re-fires on restore; unbounded defer buffer in a terminal region. |
| C-05 | Low | B16 | `STEP_UP_OK` while already elevated writes no audit record (INV-B16-c). |

**Retracted this round:** the prior "B13 `strict` false negative" was a harness defect, not a library or contract defect.

---

## 5. Surviving library defects, by final severity

Refutation moved **six** of the ten Blocker/High candidates. Every move is recorded with its reason; nothing was downgraded for convenience.

### Blocker (2) — both async-only, both the same root class

| ID | Refutation | Why it stands |
|---|---|---|
| **R6-01** — `await send(wait=True)` never resolves; loop burns a core when an event re-enters a compound whose `always` descends into a child with a completed `invoke` | **CONFIRMED** | Reproduced unmodified at both `maxIterations=1` and `=1000`, internal and external; sync returns in 0.04 s with `RunawayChainError`. Instrumented as a true livelock (23 064 `_process_event` calls in 3 s, `qsize` pinned at 1, `_raise_depth` 0). Root cause is the #120 system-event exemption at `interpreter.py:1427` — **every second lap is an engine completion, so the chain budget is never charged, not merely exceeded.** The `always` is not load-bearing: the literal #144 config hangs on async while sync trips, making this **#144 reopened on the async engine**. All refutation axes failed — docs (`json-config.md:110`, `troubleshooting.md:49`) promise an observable trip and "never raised"; no config bounds it, so not API misuse; sync is the control, not the required engine; XState v5 bounds microstep loops (cited by the library itself at `interpreter.py:1678`) with **no completion exemption**. |
| **R6-03** — `actionErrorPolicy:"rollback"` + `invoke.onDone` = unbounded hot re-invocation | **CONFIRMED** | 2 859 service invocations in 2.0 s for one user-visible event; `state=['spin.starting']`, `status='running'`, unbounded. `reliability.md` defines rollback as configuration+context restored with no warning of re-invocation, and the library's own CHANGELOG #94 claims "a rollback→re-arm→done cycle remains bounded" — **false on async**. Explicit `maxIterations=5` still yields 7 321 invocations/s: each lap is a separate macrostep driven by a genuine `done.invoke.s`, so no budget is charged. Sync is correct (2 invocations, quiescent) — also an engine-parity break. Mitigations weighed and rejected as insufficient: the loop is not starved (heartbeat gaps ≤0.7 ms, `send("ABORT")` accepted at 0.000 s) and the failure is observable via `on_transition_failed`/`last_error` — but **there is no bound and no terminal state**, so a side-effecting service is re-invoked ~1 400×/s indefinitely while the machine reports `running`. |

### High (2)

| ID | Refutation | Note |
|---|---|---|
| **R6-02** — the async chain budget exempts system events (`interpreter.py:1427`), so a two-state invoke cycle is unbounded and silent | **DOWNGRADE Blocker→High** | Repro verbatim: 3 983 laps in 8.06 s (494/s), 3 983 spurious critical alerts, `status=running`, `error=None`, `last_transition_ok=True`, `on_event_dropped=[]`; sync trips at 500 laps with `Receipt.error=RunawayChainError`. #120's premise ("an engine completion cannot self-feed"; "the sync engine spares these by construction") is **false** — `sync_interpreter.py:770-828` (#94) spares a completion only at the moment of the trip. Downgraded because **the machine is not bricked**: after the cycle the escape hatch still works (`POSITION_FLAT` → `changed=True`, watchdog region moves to `idle`), the loop is not starved, the configuration stays legal, nothing is corrupted or lost. Impact is unbounded CPU, unbounded invocations, unbounded silent side effects — **externally recoverable**. One partial mitigation exists: `getting-started.md:462` says "engine completions are never cut by it" — but that sentence is falsified by the sync engine and contradicted by `core-concepts.md:639` ("identical semantics on both engines … the same code path") and `api/index.md:1786`, which names this exact shape as a `RunawayChainError` cause. |
| **R6-06** — a snapshot taken inside an **entry action** is accepted and persists a torn state | **CONFIRMED High** | Both engines: persists `configuration=['oms','oms.filled']` with `context={'filled_qty':0}`, restores to `oms.filled` with `filled_qty=0`, `last_transition_ok=True`, `last_error=None`. Cause at `base_interpreter.py:1306` — the guard is the **conjunction** `_step_in_flight() and not _configuration_is_legal()`; #142's per-region rewrite correctly closed the parallel tear, but in the entry window the configuration is perfectly legal while context is half-applied, so the conjunction is false. **Published-contract violation**: `api/index.md:713` and `:1787`, `snapshots.md:134`, `troubleshooting.md:56` all state `SnapshotMidStepError` is raised when called "from inside an action". XState v5 publishes the new snapshot only at macrostep completion, so the state is unreachable there. **Two extensions found:** the **exit**-action window is also accepted, so the guard is inert for *every* action window in a non-parallel machine; and the obvious fix (`_step_in_flight()` alone) collides with a documented remedy — `on_transition` is documented as a safe snapshot site but `_step_in_flight()` is True inside it, so the hook must move outside the window or be exempted. |

### Medium (7)

| ID | Final | Note |
|---|---|---|
| **R6-05** — `send_threadsafe` RAISE refusals are silent | **DOWNGRADE High→Medium** | Headline claim **refuted**: the inbox bound is *not* bypassed. Corrected repro (reads the returned future, samples `qsize`) shows max depth **0** against a bound of 3, 497/500 refused with `QueueOverflowError` on the loop inside `_enqueue()`. The call-site check is an optimistic pre-check; `_enqueue()` is authoritative. Nothing accepted-then-lost, no leak. The documented contract says so explicitly, and the repro discards the future. **Surviving narrower defect:** #157's premise inverts under load — while the loop is busy (the only time backpressure matters) the refusal lands on exactly the future fire-and-forget producers never read, and the RAISE branch emits **no warning and no hook** (verified at `logging.DEBUG`, no asyncio unretrieved-exception traceback). Correct load shedding with a **hidden shed rate**. Fix: log / fire `on_event_dropped` for loop-side RAISE refusals. |
| **R6-10** — `Receipt.denied=True` for a *crashed* guard under `guardErrorPolicy:"raise"` | **DOWNGRADE High→Medium** | Reproduced on both engines after correcting two harness errors. But #153's actual contract (declared-but-refused vs undeclared) is intact — undeclared still gives `denied=False`. **No information is lost**: `Receipt.error` is a first-class field and `(denied, error is None)` totally discriminates all three cases in one read. The plugin channel is clean — a crashed guard under `raise` fires no `on_unhandled_event` at all. Reduces to a wording deviation (`api/index.md:1222`, `interpreters.md:510` say "returned False"). The defer half is weaker: under `onUnhandled:"defer"` the receipt reports `denied=True` **and** `deferred=True` together. Residual: make `denied` False when the guard raised, and warn that denied events enter the defer buffer. |
| R6-11 | Medium (stands) | `await Interpreter.start()` returns before the initial entry set's `invoke` children are registered (~13 ms) and before a plain-`def` initial service completes; `SyncInterpreter.start()` does both. `interpreter.py:487,496` never calls `_await_inline_services()`. Mitigating: the sendTo loss is **not silent** — `on_event_dropped(reason='unresolved_target')` fires, the #133 contract working. |
| R6-12 | Medium (stands) | `_threadsafe_self_sends_in_flight` incremented on the calling thread (`:1132`), decremented inside `_deliver` (`:1136`), no compensating path. It gates the `_raise_depth` reset at `:1513`. Leak is deterministic; the consequence (chain budget never resets) is **latent, not demonstrated**. |
| R6-13 | Medium (stands) | `max_workers=4` hard-coded at `interpreter.py:2360` and absent from the public surface; 9 × 0.2 s services take **5.01 s** against an ideal 0.2 s and a serialised 1.8 s — worse than serial, because R6-09 compounds pool saturation. Workaround (`service_executor=`) exists. |
| R6-14 | Medium — **regression** | `after` lateness 88–92 ms against a 50 ms budget under load, 5/5. |
| R6-15 | Medium — **regression** | `stop()` does not resolve every outstanding duplicate-`Event`-instance receipt with `InterpreterStoppedError`. |

### Low (9)

| ID | Final | Note |
|---|---|---|
| **R6-04** — `send_threadsafe(internal=…)` trust boundary | **DOWNGRADE Blocker→Low** | Both directions reproduced, neither is a security or correctness failure. `internal=True` **grants nothing extra**: an action copying its contextvars into a worker thread — the documented route — gets 500/500 accepted with **no flag** under `max_queue_size=2` + RAISE. The inbox bypass is a property of self-sends (the SCXML internal lane, unbounded by design), not of the caller flag. It is **not silent**: 5 000 forged `internal=True` sends raise `_raise_depth` to 5 000 and trip the chain budget with an ERROR log plus `on_event_dropped(reason="chain_budget")`. `internal=False` is documented ("False forces external accounting") and harm-free: 400 self-retriggers at `max_iterations=20` while a 10 ms heartbeat still fires 62× in 1 s — external accounting yields between events, so the starvation `maxIterations` guards is absent. Residual is a **doc gap only**. |
| **R6-07** — dropped `machine_hash` silently disables drift verification | **DOWNGRADE High→Low** | Mechanism reproduces (`check_identity` keys on field presence, `check_shape` never requires the key). But `machine_hash` is an **unkeyed structural fingerprint, not a MAC**, documented purely as drift detection. Against an attacker the proposed fix is worthless: dropping the hash *and* setting `version:0` is still accepted (`check_version` reads the same attacker-controlled blob), and leaving the hash correct while rewriting `state_ids`/`configuration`/`context` restores a fully forged interpreter — an attacker never needs to touch the field. The 196/300 fuzz figure counts mutations against a control that was never load-bearing. The accidental-corruption case mostly fails loudly anyway (a real state rename with the hash dropped raises `StateNotFoundError`). Genuine residual: `base_interpreter.py:1327` writes `machine_hash` unconditionally, so a `version>=1` payload lacking it is by construction not one this library wrote — add it to `check_shape`'s required keys plus a doc note that snapshots must come from a trusted store. |
| **R6-08** — an `onUnhandled:"error"` kill is invisible to the sender | **DOWNGRADE High→Low** | Receipt is `error=None/changed=False/denied=False` because `_handle_unhandled_event`'s `"error"` branch calls `_fail(err)` without populating the caller's pending receipt. But "invisible" is **false**: the instant the receipt resolves, with no sleep, `status='error'`, `.error` is the `UnhandledEventError`, `is_running=False`, and `on_error` + `on_unhandled_event(…,'errored')` have fired — precisely the documented observation channel (`core-concepts.md` L134-136). `last_error=None` is its **contract**, not a hole (`api/index.md` L738 defines it as the exception behind the most recent `last_transition_ok=False`, and no transition was attempted). The compounding claim is refuted by measurement: every later send returns `error=InterpreterStoppedError`, not "only a WARNING log". Residual: `Receipt.error` unpopulated for exactly one event (the ergonomics class #153 fixed with `denied`), plus a doc error at `interpreters.md` L996. |
| **R6-09** — plain-`def` service blocks its own macrostep | **DOWNGRADE High→Low** | Reproduced, but fails on **cause** and on **usage**. Cause refuted by measurement: a background ticker keeps firing every ~55 ms through a 0.5 s plain service; `await send("PING")` *without* `wait=True` returns in 0.000 s (the repro's 0.35 s is it awaiting its own receipt); a nested child actor on a 100 ms `after` ladder alternates seven times during the parent's 0.6 s service. So the CHANGELOG's "the loop keeps turning" is true — what is deferred is only the **invoking machine's own dispatch**, and that is documented verbatim at `api/index.md`'s `service_executor` row as the deliberate #116 parity contract. **API misuse**: `services.md` lists `async def` as the async engine's service type. Corrected to the documented shape (`async def s(...): return await asyncio.to_thread(blocking)`, identical blocking body) → latency 0.001 s, PING handled in `working`. **The defect does not survive correct usage.** Residual is documentation: `services.md`'s #116 note never warns that events declared on the invoking state are evaluated post-completion, and the invoking machine's own `after` timers fire late by the service duration (`after.100` at 0.528 s, ~428 ms lateness) undocumented. |
| R6-16 | Low | `configuration` emptied alone with `state_ids` intact → **ACCEPTED**, restores live. The read-side check never cross-validates `set(state_ids) ⊆ set(configuration)`. |
| R6-17 | Low | `_configuration_is_legal()` calls a root with zero child states legal; the surviving `_active_leaf_present()` answers `False`. **Two disagreeing definitions of one invariant in one file — the shape that reopened #142.** |
| R6-18 | Low | Owned-pool `shutdown(wait=False)` lets a service thread outlive the machine and commit its side effects after `stop()` returned. Probably right, **undocumented**: for an order-placement service, "`stop()` returned" must not be read as "nothing further will happen". |
| R6-19 | Low | `spawnBlockingTimeout` is accepted by `create_machine` but sets no attribute on `MachineNode`, so a conformance lint cannot assert it post-build. |
| R6-20 | Low | `plugins.py:201-202` says `"fail"` → `status == "error"`; runtime and CHANGELOG say `"stopped"`. **Resolves regression LC-01**: the code is correct, the docstring is the stale artefact. |

**Final counts: 2 Blocker · 2 High · 7 Medium · 9 Low = 20 canonical library defects.** Triage of the inbound set: 20 LIBRARY-DEFECT · 13 DUPLICATE · 5 HARNESS-ERROR · 5 DESIGN-CONSTRAINT · 15 OUR-CONTRACT/NEEDS-WRAPPER · 9 CONFIRMED-FIXED/INFO.

---

## 6. Gate decision (per `20-adoption-gate.md` §7)

Applied in order, first match wins, with honest counts:

| Row | Condition | Our count | Matches? |
|---|---|---|---|
| 1 | Any `ERROR` row in the gate output | none — 33 FAIL / 56 PASS, all FAILs triaged to known findings or expected-FAIL harness scripts | no |
| 2 | Suite fails, or coverage < 86 % | 3399 passed / 0 failed; **92.77 %** | no |
| 3 | Snapshot format changed while LC-21 open | LC-21 closed; format versioned and unchanged this round | no |
| 4 | **Any filed Blocker repro still exits 1** | **R6-01 and R6-03 both reproduce unmodified** | **YES — row 4 wins** |

```
Gate run 2026-09-20 — xstate-statemachine main @ cec108b (unreleased 0.8.1)
DECISION: DEFER (order path)  ·  GO for non-order paths under constraints
          — decision-table row 1 of the readiness ladder: Blocker row non-empty

  26 issues      : 24 closed (2 with a documented scope caveat), 1 partial (#122),
                   1 not-fixed (#157, reopened narrowly as R6-05 Medium)
  regressions    : 3 confirmed (R6-14 after-lateness, R6-15 stop() receipts,
                   + LC-26 secondary folded in); LC-01 reclassified as harness (H-1)
  new defects    : 2 Blocker · 2 High · 7 Medium · 9 Low  (post-refutation)
                   pre-refutation was 4 Blocker · 6 High · 5 Medium · 5 Low;
                   refutation moved 6 of 10 Blocker/High down, 0 up
  gate script    : verify 29/34 · verifyM 10/15 · verifyM2 3/3 · repro 13/34 · probe 1/3
  suite/coverage : 3399 passed / 13 skipped / 0 failed (9m02s) · 92.77% (floor 90%)
  benchmarks     : order-path fill p95 0.057 ms vs 0.10 ms budget PASS;
                   raw send 238k ev/s; policy ratios inside the noise band;
                   BENCH-2 rule fan-out 410/s vs 2000/s FAIL (unchanged class);
                   BENCH-6 loaded-drift bench NOT RUN (time budget) — gap, not a finding
  contracts      : 20/20 build clean; B10-B17/B19/B20 PASS; B1-B9/B18 pass
                   functionally but exposed to R6-03 on the mandatory rollback policy
  blockers open  : R6-01, R6-03      high open: R6-02, R6-06
  operative block: UPSTREAM — async chain/macrostep termination accounting does not
                   match the sync engine (interpreter.py:1427 exemption + the #144
                   termination rule never ported to interpreter.py)
  decided by     : adoption audit, round 6
```

**Note on what row 6 *would* have given.** Had the two Blockers been absent, the open-High count is **2** (R6-02, R6-06) — inside the ≤5 bar — and both have mechanically enforced mitigations available (CV-C35 `always` fan-in lint; CV-C23 quiescence-only snapshots via the factory wrapper, already ticketed as E50-T10). That is row 6, **ADOPT WITH CONSTRAINTS**. So the entire distance between today's DEFER and adoption is **one upstream change**: give the async engine the sync engine's termination accounting.

**Why not "ADOPT with wrappers" anyway.** R6-06 is wrappable (snapshot only at quiescence) and R6-02 is lintable. R6-01 and R6-03 are not: a wrapper cannot see a livelock that reports `running` / `error=None` / `last_transition_ok=True`, and an external watchdog that kills a machine mid-flight is not a mitigation for an order path — it is a second failure mode. Money does not go through an unbounded silent loop.

---

## 7. Constraints

### Retired (7)

| Constraint | Why it retires |
|---|---|
| **CV-C30** (no parallel regions in order-path machines) | **RETIRES.** #142/#143 landed one legality predicate — exactly-one-leaf-per-region — on **both** the write and the read side, and #143 provably reuses the identical write-side function, so no drift is possible. Evidence: `n3_parallel_tear 300` **0/179 torn** (was 27.4 %); Hypothesis 300-case property over random parallel machines, 879 quiescent snapshots, 0 failures; `m1` 1 217 snapshots over 350 generated parallel machines, 0 illegal configurations. Parallel regions are safe again. |
| **CV-C27** (our own legality check on every `from_snapshot()`) | **RETIRES as a general obligation, survives as a one-line residual** — see CV-C27′ below. The read side now enforces legality (5 000 mutations → 0 raw builtins, 0 restored `running`-with-no-leaf). The only hole left is R6-16 (`configuration` emptied alone with `state_ids` intact). |
| **CV-C31** (`actionErrorPolicy:"fail"` forbidden) | **RETIRES as written.** #145 is confirmed symmetric on both engines: `"fail"` → `status="stopped"` + configuration cleared, `TransitionFailedError` retained, round-trips through snapshot, and `from_snapshot` refuses the halted blob with `InvalidConfigError`. R5-12 (reverts to source, brickable, snapshottable) is dead. **But it is replaced, not deleted** — see CV-C31′: R6-03 makes `"rollback"` *itself* the dangerous policy on the order path, which is the exact inversion of the round-5 position. |
| CV-C24, CV-C25 (runtime half), CV-C26, CV-C29 | Already retired in round 5; confirmed still retired at `cec108b` (#147 `RootTargetError` is now non-downgradable under both `strict_targets` settings, 8/8, so CV-C29's belt-and-braces lint is genuinely redundant). |
| **CV-C34** (remove `"*": defer` scaffolding) | **RETIRES — done.** Applied throughout `28-statechart-catalogue.md`; B16–B20 were re-extracted from the corrected catalogue this round and `onUnhandled:"defer"` now correctly holds and replays `UNKNOWN_ORDER` mid-sweep on B19. |

**CV-C32 does *not* retire.** R6-09's refutation downgraded the *defect* to Low precisely *because* the correct usage is `async def` — the constraint is what makes the downgrade valid, so removing it would re-open the finding. It is **restated per-engine**: async engine → every service is `async def` (wrap blocking work in `asyncio.to_thread`); sync engine → every service is plain `def` (`SyncInterpreter` raises `NotSupportedError` on `async def`, confirmed three ways). Consequence to record: **sync parity is unavailable, not merely untested, for any machine with services.**

### Standing (unchanged)

**CV-C01…CV-C22** as amended · **CV-C23** (quiescence-only snapshots via the factory wrapper) — **promoted to the primary defence against R6-06**, and now also the reason the entry/exit-action window never bites us · **CV-C28** (no `LoggingInspector` in production) — the R5-19 DEBUG bypass is fixed (#160, 17/17 keys), but the constraint is cheap and the production-logging argument is independent · **CV-C33** (`send_threadsafe` only via our gateway) — now also the enforcement point for R6-05's hidden shed rate.

### New (5)

| ID | Rule | Enforced by | Covers |
|---|---|---|---|
| **CV-C27′** | Our restore wrapper asserts `set(state_ids) ⊆ set(configuration)` before `start()`. One assertion, not the full legality check. | E50-T12, narrowed | R6-16 |
| **CV-C31′** | **Order-path machines must not combine `actionErrorPolicy:"rollback"` with an entry action that can raise on a state carrying an `invoke`.** Where a machine needs both, use `"fail"` + an explicit `halted` state (now safe per #145). | Linter rule over the catalogue JSON: flag any state with `invoke` whose entry actions are not declared `noraise`. | **R6-03 (Blocker)** |
| **CV-C35** | **No `always` transition may descend into a child state carrying an `invoke`**, and no `always` may target an ancestor of its own source. | Same linter pass, build-time | **R6-01 (Blocker)**, R6-02 |
| **CV-C36** | Every `send_threadsafe` future returned by the gateway is **read**; a refusal increments a shed counter and pages at a threshold. Fire-and-forget cross-thread sends are forbidden. | Gateway API shape (returns nothing that can be ignored) + a contract test | R6-05 |
| **CV-C37** | `await start()` is not "the machine is up". The factory awaits an explicit `children_ready()` barrier (poll `interpreter.actors` for the declared invoke ids) before returning the handle. | Factory wrapper + contract test | R6-11 |

**Wrapper obligation W-04 becomes a constraint clause under CV-C06:** read `(denied, error is None)` — never `denied` alone — and keep guard-denied events out of the defer buffer (R6-10, C-2).

### Recomputed mandatory configuration block

```jsonc
{
  // --- error handling -------------------------------------------------
  "actionErrorPolicy": "rollback",   // default, ALL non-order machines.
                                     // CV-C31′ (2026-09-20): on the ORDER path,
                                     // forbidden on any state that carries an
                                     // `invoke` and has a raisable entry action —
                                     // R6-03 re-arms the invoke for ever (~1400/s,
                                     // status="running", error=None). Use "fail" there.
  "actionErrorPolicy": "fail",       // ORDER-PATH machines with invoke+entry actions:
                                     // RE-PERMITTED (CV-C31 retired). #145 verified:
                                     // status="stopped", configuration cleared,
                                     // TransitionFailedError retained, and the halted
                                     // blob is refused by from_snapshot with
                                     // InvalidConfigError. Pair with an explicit
                                     // `halted` state entered from on_transition_failed
                                     // (C-07: these states are still MISSING — E50-T16).

  "guardErrorPolicy": "raise",       // #152 verified: cancels only the FAILING candidate,
                                     // the unguarded fallback is still taken, both engines.
                                     // CV-C06/W-04: read (denied, error is None) — a crashed
                                     // guard also sets denied=True (R6-10).

  "onUnhandled": "defer",            // order path. CV-C34 retired: NO "*" scaffolding.
                                     // Authorisation/risk events must be non-deferrable
                                     // (W-03, C-2) — B17/B18/B19 opt out per-event.
  "onUnhandled": "error",            // control machines ONLY, and NOT on B18:
                                     // C-07b — a guard-denied RELEASE is terminal,
                                     // i.e. the kill switch is bricked by a wrong press.

  "strictTargets": true,             // #147: RootTargetError at build time, non-downgradable
                                     // under BOTH strict_targets settings (8/8). CV-C29 retired.
  "maxIterations": 500,              // NOTE: inert against R6-01/R6-02/R6-03 on the async
                                     // engine — system events are exempt at
                                     // interpreter.py:1427 and each rollback lap is its own
                                     // macrostep. Keep it; do not rely on it.
  "spawnBlockingTimeout": 5000       // R6-19: parsed but sets no MachineNode attribute,
                                     // so a conformance lint cannot assert it post-build.
}
```

```python
# Runtime construction — mandatory
MachineLogic(strict=True)                     # W-01: create_machine is NOT a conformance
                                              # gate; the wrapper must cross-validate the
                                              # logic table against the JSON at construction.
Interpreter(..., max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
                                              # CV-C36: every send_threadsafe future is read.
# Services: async def ONLY on the async engine (CV-C32, restated). Blocking work goes
# through `await asyncio.to_thread(...)`. service_executor= is set explicitly because
# max_workers=4 is hard-coded otherwise (R6-13).
# Snapshots: ONLY via the factory snapshot() wrapper at quiescence (CV-C23) — the
# library's in-flight guard is inert inside entry AND exit actions (R6-06).
# start(): await children_ready() before handing out the handle (CV-C37).
```

---

## 8. Release-readiness note for the team (before tagging 0.8.1)

Round 5's fix quality was high and this round confirms it at the root, not by symptom. Two things stand between `cec108b` and a tag we would pin.

1. **`__version__` is still `0.8.0`.** Six rounds, six reports that have had to say "key on the commit". Bump it.
2. **Port the sync engine's termination accounting to the async engine — one change, three findings.**
   - Delete the blanket exemption at `interpreter.py:1427` (`if self._raise_depth > limit and not is_system_event(event)`). Its stated premise — *"the sync engine spares these by construction; mirror that here"* — is false on this very commit: `sync_interpreter.py:770-828` spares a completion only **at the moment of the trip** (`spare = is_completion and not tripped`) and drops it thereafter. Mirror *that*.
   - Port #144's rule ("a chain ends only when nothing self-generated remains queued") from `sync_interpreter.py` into `interpreter.py::_run_event_loop`, and add the `always`-into-completed-`invoke` shape as a pinned async test. The existing pin at `tests/test_round5_findings.py:331` is sync-only.
   - Charge each `rollback` → re-arm → `done.invoke` lap to the chain budget so R6-03 terminates. If the design view is that it should not, then **fire `on_event_dropped` and set `RunawayChainError` on the exempted path** so the livelock is at least observable — silent is the unacceptable part.
   - **Add an engine-parity test class**: for a handful of pathological configs, assert `Interpreter` and `SyncInterpreter` reach the same terminal disposition. Three of this round's four candidate Blockers would have been caught by it at authoring time. This is the single highest-value test the project can add.
3. **Fix the snapshot in-flight guard's predicate** (R6-06). `base_interpreter.py:1306` uses `_step_in_flight() and not _configuration_is_legal()`; the right predicate for the root call is `_step_in_flight()` alone. Note the collision: `on_transition` is documented as a safe snapshot site but runs inside the in-flight window, so the hook must move outside it or be explicitly exempted. Pin **entry**, **exit** and `on_transition` windows separately — the current pin covers only the parallel case.
4. **Unify the two legality predicates** (R6-17). `_configuration_is_legal()` and `_active_leaf_present()` disagree about a root with zero child states. Two definitions of one invariant in one file is the exact shape that reopened #142; delete one.
5. **Cross-validate `configuration` against `state_ids` on restore** (R6-16) and require `machine_hash` in `check_shape` when `version >= 1` (R6-07) — the latter as *corruption detection*, with a doc note that snapshots must come from a trusted store. It is not, and cannot be, tamper resistance.
6. **Make loop-side `OverflowPolicy.RAISE` refusals observable** (R6-05): log at WARNING and fire `on_event_dropped`. Current behaviour is correct load shedding with a hidden shed rate, which is the worst of both.
7. **Decrement `_threadsafe_self_sends_in_flight` in a done-callback** on the returned future (R6-12) — it gates the `_raise_depth` reset.
8. **Expose `service_pool_size=`** and document the limit (R6-13); document that `stop()` does not interrupt an in-flight service thread (R6-18); set the `spawnBlockingTimeout` attribute on `MachineNode` (R6-19).
9. **Doc fixes.** `plugins.py:201-202` (`"fail"` → `"stopped"`, not `"error"` — R6-20); `interpreters.md` L996's claim that `onUnhandled="error"` raises at the call site (it does not, on either engine); `getting-started.md:462`'s "engine completions are never cut by it", which contradicts both `core-concepts.md:639` and the sync engine; and `services.md`'s #116 note, which never warns that events declared on the invoking state are evaluated post-completion.
10. **Populate `Receipt.error` for the `onUnhandled:"error"` kill** (R6-08) — one line, same ergonomics class #153 fixed with `denied`; and set `denied=False` when the guard raised (R6-10).
11. **Bound `after` lateness under load** (R6-14) and resolve every outstanding receipt at `stop()` (R6-15) — the two genuine regressions.
12. Coverage floor is now 90 and passes at 92.77 %. `interpreter.py` at 89 % is the module carrying both Blockers, and the missed branches are exactly the rare error paths. Worth a targeted push before the tag.

---

## 9. What would change the verdict

**Close R6-01 and R6-03 with pinned async tests → the Blocker row clears.** Open-High is then **2** (R6-02, R6-06), inside the ≤5 bar, each with a mechanically enforced mitigation and a contract test in `tests/xstate_contract/` (CV-C35 lint for R6-02; the CV-C23 factory wrapper for R6-06). That is decision-table **row 6 — ADOPT WITH CONSTRAINTS on the order path**. If R6-02 closes as part of the same change — which it will, since it is the same line — the count is 1 High and the margin is comfortable.

Nothing else needs to move. The Medium and Low rows are wrappable, ticketed, or documentation.

**Re-verification recipe (~45 minutes):**

```
gate/run_gate.py                                        # incl. the new verify-main-cec108b set
battle-cec108b/fuzz/m9_send_hang_min.py                 # R6-01 + its 4 ablations — must exit 0
battle-cec108b/contracts/repro/<R6-03 rollback spin>    # must terminate, bounded
battle-cec108b/contracts/repro/f9_sync_budget_signal.py # R6-02: async must now match sync
battle-cec108b/semantics/repro/d6s1_entry_window_torn_snapshot.py  # R6-06, entry AND exit
battle-cec108b/persistence: n2 (2000 quiescent points) + m1 (350 parallel machines)
contracts: B1, B8, B18 end-to-end
```

**What would make the verdict *worse*:** a 0.8.1 tag cut at `cec108b` as-is. We would then be pinning a *released* version carrying two silent unbounded-CPU Blockers, and the "key on the commit, not the version" escape hatch disappears.

---

## 10. Next steps for CandleViewer

1. **Post round 6 upstream.** Drafts staged in `issues/post-cec108b/` (not posted): 24 confirm-closed comments, 1 narrow reopen (#122), 1 reopen-on-narrower-grounds (#157), new-issue files for every CONFIRMED Medium-and-above library defect (R6-01, R6-02, R6-03, R6-05, R6-06, R6-10, R6-11, R6-12, R6-13, R6-14, R6-15), a ride-along comment on #144 recording the async gap beside its sync fix, and a refreshed `meta-26.md` carrying this scorecard and the release note. Manifest: `issues/post-cec108b/manifest.json`. **Lead with the engine-parity test class** — it is worth more to the project than any individual fix.
2. **Start the non-order machines on the library now** (E50 enablement): B10–B17, B19, B20 under CV-C01…CV-C37 as recomputed in §7. A real GO, not a hedge — those machines drove **0 new library defects** across 46 control scenarios and 9 snapshot-every-macrostep runs.
3. **Order path stays on the in-house shim.** `E50-X01` re-runs when the team pushes the `interpreter.py` termination change.
4. **Fix our own catalogue first — two of our defects are Blockers and they are ours on any runtime.** C-04 (B16 elevation survives `LOGOUT`/`REVOKE`) and C-07b (B18 kill switch bricked by a guard-denied `RELEASE`). Then C-07 (the `halted` states CV-C31 promised and nobody added), CV-B4-01, C-06, OUR-B11-01, OUR-B14-01.
5. **E50 ticket movement:** retire `E50-T13`'s root-target rule and CV-C30's parallel-region ban; **narrow** `E50-T12` to the single `state_ids ⊆ configuration` assertion; **re-scope** `E50-T16` to write the missing `halted` states and re-permit `"fail"` on the order path; **new** tickets for the CV-C31′/CV-C35 linter pass, the CV-C36 gateway future-reading rule, and the CV-C37 `children_ready()` barrier.
6. **Shim retirement plan (conditional on GO).** Not a switch, a ladder: (a) non-order machines move now, the shim keeps only the order path; (b) when R6-01/R6-03 close, run the dual-runtime conformance harness (`E50-T03`) over B1–B9/B18 on both runtimes for one full sprint with the library in **shadow mode** — same events, compared dispositions, zero divergences required; (c) cut over one machine at a time, starting with B9 `rule_instance` (no money on it) and ending with B1 `order`; (d) the shim is deleted only after B1 has run 30 days in production with no divergence. Budget the ladder at two sprints *after* the upstream fix lands, not before.

---

## Evidence index

`38-r6-findings-register.md` (register of record) · `35-r6-regression.md` · `36-r6-suite-bench.md` · `37-r6-diff-review.md` · `39-r6-01-refutation.md` · `39-r6-05-refutation.md` · `battle-cec108b/*.md` (8 tracks) · `battle-cec108b/contracts/*.md` (4 groups + 2 refutations) · `battle-cec108b/semantics/R6-06-refutation.md` · `issues/verify-main-cec108b/*` · `gate/result-main-cec108b.json` · `gate/tmp_regrun/results.json` (238 scripts) · suite/coverage/bench runs recorded in §2/§3/§6 (2026-09-20, Python 3.13.7, Windows 11).





