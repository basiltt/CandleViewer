# 44 — Round-7 FINAL readiness verdict: `xstate-statemachine` main @ `221ce7c` (unreleased 0.8.1)

Date: 2026-09-20. Question asked by the owner: *"Verify all reported issues are genuinely closed; is the library completely ready, fully battle-tested, and are we good to proceed?"*

**Identify this build by commit, never by version string.** `__version__` still reports `0.8.0` on `221ce7c` (merge of PR #178 on top of #177 and the hot-path PRs #165/#176) while `CHANGELOG.md [Unreleased]` targets 0.8.1. Every pin, gate baseline and CI assertion keys on the commit.

Method: 12 issue verifications (round-6 fixes #166–#175 + #157 + #122-as-designed), full regression sweep (gate + every standalone verify/repro/probe script), library suite + coverage, benchmarks, diff review `cec108b..221ce7c`, all 8 battle tracks re-run with new attacks, all 20 contract machines driven end-to-end, then triage → dedupe → **independent adversarial refutation of every Blocker and High**. Register of record: `43-r7-findings-register.md` (refutation verdicts applied below); refutations: `44-r7-01-refutation.md`, `44-r7-07-refutation.md`, `adversarial/r7-04/README.md`, `issues/post-cec108b/new/r7-02-refutation.md`.

---

## 0. The answer

**Are the 12 reported issues genuinely closed? — 7 of 12 outright, 2 partially, 2 documentation-only, 1 not at all.** **FIXED and verified:** #157, #166, #169, #170, #171, #172, #173. **PARTIAL:** #167 and #168 — the invoke-cycle/rollback-cycle bound landed on the **plain-`def`** service path only; the identical chart with an `async def` service is still completely unbounded (14k–70k laps, no trip, `last_error=None`). **DOCUMENTED-ONLY (no code changed):** #122 (`tick()`'s real-clock-ladder contract is now stated verbatim; correct as designed) and #174 (blocking-timer behaviour documented; busy-loop `after` lateness and the after-100-behind-500ms-service class both still reproduce unchanged). **NOT-FIXED:** #175 — `stop()` still never resolves duplicate-`Event`-instance receipts with `InterpreterStoppedError` (160/160 receipts over 20 trials resolved as ordinary success), and the shipped round-6 regression test pins only a weaker `ok == applied` invariant that passes even while Case D is broken.

**Is the library fully battle-tested and ready? — No, not for the order path.** After independent refutation the round leaves **2 Blocker · 4 High · 6 Medium · 8 Low** live library defects. Refutation moved **three** of the eight Blocker/High candidates *down* (R7-03 Blocker→High, R7-06 High→Medium, R7-04 High→REFUTED with a Low documented residual) and **none** up. The two surviving Blockers are both on the async engine, both silent (`status == "running"`, `last_error is None`), and both sit in code this round added:

- **R7-01 (Blocker)** — an `async def` invoked service publishes its completion on the **public inbox lane** (`interpreter.py:2414`, child-actor `onDone` at `:2882`) instead of the charged priority lane (`_finish_plain_service` → `_deliver_priority`, `:2690`, charging at `:2287-2288`). Lane probe: plain `{priority:23, inbox:0}` + `RunawayChainError` vs async `{priority:0, inbox:27409}` + `last_error=None`. Arriving `from_inbox` it *also* satisfies the disjunct at `:1647` and resets `_settle_iterations`/`_settle_tripped` every lap, so the per-macrostep settle budget cannot trip either. 67 351 laps in 5 s, `ok=True`. One variant (`q14`) settles into an **empty configuration 10/10** with `ok=True`, `err=None`, `status="running"`, unhealed at +500 ms — while the library's own `get_persisted_snapshot()` refuses that same instant as `SnapshotMidStepError`. The rollback ablation is the same defect (23 service calls bounded vs 2 780 unbounded).
- **R7-02 (Blocker)** — external `send(priority=True)` is charged to the chain budget. Burst producer: `sent=3000 processed=1162 dropped=1838 reasons={'chain_budget'}`; a non-burst probe (one external send per 0.1 ms) still loses 30 %. Control run with the identical load minus `priority=True`: `processed=3000, dropped=0`. The run loop's own architecture note (`interpreter.py:1510-1516`) explicitly promises external traffic of any volume is never throttled. The drop path resets `_raise_depth`/`_chain_tripped` (`:1596-1599`), so `last_error` reads `None` and the loss is visible only through the opt-in `on_event_dropped` hook.

Neither is wrappable. R7-01 has **no configuration that mitigates it** (DC-4): the only mitigation is plain-`def` services, which #174 documents as blocking the machine's own `after` timers — and B19's `backing_off` retry ladder depends on `after` firing during a service. CV-C32 (async-only services, which keeps the round-6 downgrade of R6-09 valid) is precisely what puts every contract machine on the *unprotected* lane.

**Are we good to proceed?**

- **Non-order paths (B10–B17, B19, B20 — recording, replay, connection, ingestion supervision, paper matching, auth, live-enablement, reconciliation, risk lockout): YES, proceed now**, under the constraints recomputed in §7 — unchanged from round 6 in substance, plus the five new mechanical rules CV-C38…CV-C42. Those machines build clean, pass every catalogue invariant, snapshot/restore at every macrostep with trace equality, and drove **zero new library Blockers** this round. The order-path-only exposure is R7-01 (invoke cycles under `async def`) and R7-02 (the priority lane), and the non-order machines either do not carry the shape or are protected by CV-C35/CV-C38.
- **Order path (B1–B9, B18): NO — DEFER.** Two independent Blockers, each sufficient alone, each a silent-loss class with money on it.

**What blocks, and whose it is.** The block is **UPSTREAM**, and it is now two lines of provenance accounting in `interpreter.py`, not a design problem:

1. **R7-01 — publish coroutine-service and child-actor completions on the same charged lane the plain-`def` path uses** (route `:2414` / `:2882` through `_deliver_priority` rather than `await self.send`), and stop treating an engine completion that arrives `from_inbox` as an external event at `:1647`.
2. **R7-02 — make the chain-budget charge in `_deliver_priority` (`:2287-2288`) depend on *provenance*, not on the `_processing` flag** — an explicit internal flag, or gate on `_issued_from_own_action()` the way every other enqueue path already does (`:826`, `:854`, `:1206`).

These are opposite halves of the same mistake: **WHO issued the event has been replaced by WHEN it arrived.** Self-generated work escapes the budget on one path while external work is charged on another.

**Nothing on our side blocks the non-order GO.** Our remaining work — catalogue defects C-04 and C-07b (both Blockers *on any runtime*, ours), C-06, C-07, CD-03, CV-B4-01, OUR-B11-01, OUR-B14-01/02, OUR-B15-01, and wrapper obligations W-01…W-05 — is ticketed under `E50-T14`/`E50-T16` and gates only the machines it names.

**One more thing the owner should hear plainly.** The round-6 fixes were real and they verified on our own contract machines — *with `def` services*. All three pinned regression tests (`tests/test_round6_findings.py:124/184/486`) declare `def svc`, so the library's suite is structurally blind to the lane its own documentation tells users to prefer. **One extra parametrisation over service kind would have caught every one of the six findings folded into R7-01.** That is the single highest-value change upstream can make this round, worth more than any individual fix.

---
## 1. The 12 issues

| Result | Issues |
|---|---|
| **FIXED — confirm closed (7)** | **#157** (loop-side RAISE refusal: 5/5 forced races surfaced `QueueOverflowError` on the future + `on_event_dropped('queue_full')` + a WARNING log; `refused=199, hook_fires=199` under load, exactly once per refusal) · **#166** (`always`+completed-`invoke`: sync trips `RunawayChainError`, async `await send(wait=True)` resolves in ~0.2 s with the same error — no livelock; the R6-01 repro exits 0) · **#169** (root `get_persisted_snapshot()` refuses unconditionally while a step is in flight, both engines; post-settle snapshot shows `filled_qty=100`, not the torn `0`) · **#170** (`denied`/`error` now discriminate guard-false / guard-crash / guard-true injectively on both engines) · **#171** (`await start()` awaits actor bring-ups, an invoked `MachineNode` child is in `_actors` the instant `start()` returns, immediate `sendTo` no longer drops — and #149 is preserved: `start()` does not block on a plain service's result) · **#172** (done-callback balances the threadsafe in-flight counter on every terminal outcome — delivered/refused/cancelled/loop-stopped; `inflight_counter_after=0`) · **#173** (public `service_pool_size=` feeds `ThreadPoolExecutor(max_workers=…)`, default unchanged at 4, `pool_size=8` is 7.8× `pool_size=1`, `0` raises `ValueError`) |
| **PARTIAL — reopen narrowly (2)** | **#167** — plain-`def` invoked service is bounded (chain-budget trip, ~1 000 calls, `status="running"`); the **`async def` (coroutine) service is still unbounded** (~10–21k calls in 1–2 s, no charge). The original R6-03 coroutine repro still exits 1. · **#168** — plain-`def`/actor completions are bounded on both engines, but a `ver ⇄ arm` cycle built from `async def` services bypasses `_raise_depth` entirely (14k+ laps/s, never trips). **Both are one defect: R7-01.** |
| **DOCUMENTED-ONLY (2)** | **#122** — `tick()`'s docstring now states the real-clock-ladder contract verbatim. **Correctly closed as working-as-designed**: no synchronous call can make wall time pass; the original repro encoded the async engine's wall-clock wait as a sync expectation and is itself invalid. Not counted against the library. · **#174** — `production-characteristics.md` states the blocking-timer behaviour but **no code changed**; busy-loop lateness (~15–30 ms over a 50 ms budget) and the `after:100`-behind-a-500 ms-service class both still reproduce unchanged. Counted as an open documented limitation, covered by BENCH-6 / house rule A2. |
| **NOT-FIXED — reopen (1)** | **#175 (Case D)** — `stop()` still never resolves duplicate-`Event`-instance receipts with `InterpreterStoppedError`: **160/160** receipts across 20 trials resolved as ordinary success. The shipped regression test pins only `ok == applied`, which passes while Case D is broken. This is a **test-strength** defect as much as a code defect. |

**Two closures carry a scope caveat worth recording.** #169 is fixed *at the root* and inert in three residual windows — the async `start()` initial-entry window (R7-05, High), the child-actor branch (R7-07, High), and transition actions on async (R7-10, Medium). #171 is fixed and **introduced R7-03**: `_await_actor_bringups` gathers bring-up tasks with no timeout, so a slow child entry action makes `await start()` hang.

---

## 2. Regressions

**Zero true PASS→FAIL regressions in the gate** (`40-r7-regression.md`, confirmed by direct check-by-check JSON diff of `result-main-cec108b.json` against `result-main-221ce7c.json`). Totals `FAIL=36, PASS=80`; every flagged delta traces to a pre-existing FAIL, a harness bookkeeping gap, or a self-documented PARTIAL. Flaky-check ×5: all deterministic.

**But three regressions were introduced by this round's own fix work, and the gate cannot see any of them** — they are all outside what any existing check exercises:

| # | Item | Severity | Verdict |
|---|---|---|---|
| 1 | **R7-02** — `_deliver_priority`'s provenance test now charges *external* `send(priority=True)` to the chain budget | **Blocker** | **TRUE REGRESSION, new in round 7.** Re-opens the exact failure class (#77) the chain-budget architecture was designed around. Control run proves causation: the same load without `priority=True` drops zero. |
| 2 | **R7-03** — `await start()` hangs unboundedly on a slow invoked child, introduced by #171's untimed `gather` | **High** (downgraded from Blocker) | **TRUE REGRESSION, new in round 7.** |
| 3 | **R7-11** — sync `_deferred_this_step` never cleared on `wait=False`; unbounded growth | Medium | **TRUE REGRESSION.** Its sibling `_guard_denied_this_step` *is* correctly reset (`L-9` negative), so this is an omission, not a design. |
| 4 | `bench_h` RSS/open-order **3.10 KB → 5.18 KB** | unattributed | **Flagged, not asserted.** Single run, no repeat, no bisection; direction is opposite to what #165/#176 claim. Worth a bisected re-run before the tag. Not counted as a finding. |
| 5 | Suite flake: `TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations` | — | **Flake, not a finding.** Failed once inside the full 3 419-test run; passed standalone (1.22 s) and under both hash seeds in the 115-test finding suites. No independent repro obtained inside the time budget. |

Two **harness** defects were found and are ours to fix: **H-1** — `VERIFYM3_BASELINE_FAILURES` records only `["157"]` while the `verify-main-cec108b/` directory has since gained `150_send_threadsafe_budgeted.py` and `probe_144_async*.py`, both 5/5 deterministic pre-existing FAILs that appear in no `cec108b` baseline; **H-2** — the gate gives no baseline-failure allow-list to the `verify` set at all, so `LC-01`/`LC-12`/`LC-26`/`LC-48`/`LC-57` flag every run.

**Suite / coverage:** `3418 passed, 1 failed (flake), 13 skipped` in 8 m 41 s (**+19 vs `cec108b`**); coverage **92.64 %** against the 90 % floor — passes with +2.64 pt headroom, flat vs round 6's 92.77 % (noise band). `interpreter.py` is up to **91 %** (was 89 %) — the module carrying both Blockers. `tests/test_round6_findings.py` carries 17 test functions. `PYTHONHASHSEED` 1 vs 2: 115/115 identical both ways, no order sensitivity. **No tests deleted, no `xfail`/`skip` added anywhere in the diff**; the single edit to an existing test (`TestPriorityLanePersisted`) is a legitimate fixture repair forced by #169's stricter refusal, with its assertion unchanged.

---

## 3. Battle-test scorecard (`221ce7c`, post-refutation)

| Track | Round-6 defects | Now | New defects (final severity) | Coverage this round | Verdict |
|---|---|---|---|---|---|
| **Fuzz** | 1 Blocker (R6-01), 1 High (R6-02) | **D6-fuzz-1 FIXED as filed** — the 8-line `m9_send_hang_min.py` resolves in 0.00–0.20 s on every ablation, **0 hangs** where round 6 had 6/6. The macrostep settle budget is genuinely per-instance. | **R7-01 (Blocker)** — same chart, one word changed: `def svc` trips at lap 22, `async def svc` runs 70 159 laps with no trip; plus the empty-configuration variant 10/10 | 8-line minimal repro + lane instrumentation + 4 ablations + the `rb.py` rollback ablation | **FAIL** — the fix landed on the wrong side of a fork |
| **Concurrency** | 1 High (D6-concurrency-1 → #171) | **Every prior defect FIXED.** 500 fuzzed cyclic configs across both engines → **zero livelocks**; the trip is observable on both engines at the *same lap count*; a 300 s chaos soak and a 100 s / 200-machine shape soak both stayed CPU-bounded with zero torn snapshots and zero task leaks | D7-concurrency-1 → **R7-04 REFUTED** (residual Low, documented plain-`def` inbox starvation); D7-concurrency-2 → R7-10 (M); D7-concurrency-3 → R7-14 (L) | 500 configs, 300 s chaos soak, 16-thread contention | **PASS**, conditional on the documented plain-`def` invoke-cycle shape |
| **Persistence** | 1 High (R6-06 entry window) | **#169 holds in every window except one** — `q1`'s hook property over **320 generated parallel machines / 7 622 snapshot attempts from 8 distinct windows** gives **0 raw exceptions, 0 round-trip mismatches** | **R7-05 (High)** — 720/720 torn blobs land in `entry@start` and nowhere else; **R7-07 (High)**, **R7-08 (High)**, R7-06 (M, downgraded), R7-09 (M) | 320 machines × 7 622 attempts, 8 windows, both engines | **PARTIAL** — root fixed, three residual windows |
| **Semantics** | R6-06 (H), R6-10 (H), R6-11 (M) | **All three FIXED.** Prior suite `n1..n6` **33/33** (was 32/33); `_actors` populated the instant `start()` returns, 20× identical trace on both engines; the `(denied, error, deferred, changed)` matrix is injective | R7-07 (High, via `S1-02`), R7-10 (M) | 11 new attacks in 5 scripts; 300 random nested/parallel machines × 19 945 hook snapshots | **PARTIAL** |
| **Determinism** | 0 | **All prior determinism defects remain FIXED.** Five new attacks aimed squarely at round-6's own fixes found **no new defect**: the chain budget still trips under 16 concurrent external senders; `service_pool_size=1` serialises 50 services and `stop()` mid-service returns cleanly; the threadsafe counter balances to exactly 0 against a racing callback plus a same-future cancel; the loop-side RAISE hook fires exactly once per refusal (236 == 236) | **none** | `n1` N=500, `n7` 90 s, plus new attacks `f1`–`f5` | **PASS** |
| **Observability** | 9 legacy carried | **All 9 re-verified unchanged.** #157's hook parity confirmed | R7-12 (M), R7-14 (L), R7-15 (L) | reduced — the config-fuzzer livelock probe, the Hypothesis persistence property, 50× determinism reruns, the hash-seed sweep and the 12-minute soak were **NOT RUN** this pass (stated, not silent) | **PASS with a reduced-coverage note** |
| **Security** | 1 High (D6-security-1) | Redaction holds; `{"type": "GO"}` still resolved-by-design | **R7-06 (Medium, downgraded from High)** — `machine_hash: None` still ACCEPTED; `accepted_bad=196` identical to `cec108b`, `uncontrolled_exceptions=0` | fuzz reduced 300→120 configs; concurrency reduced to 200/200; hook property 300 cases; 12-min soak not run; **D-security-2/3/4/5 carried forward, NOT re-verified** (no `gh api` this pass) | **PASS at reduced scale** |
| **Soak (1.5 min / 30 machines, reduced)** | 0 | **All prior FIXED and unchanged** — `wait=True` receipts resolve, `SimulatedClock` settlers 0, all 6 hostile fields typed, the #145 stop contract holds. `final_sent 9501 / accepted 9500`, `lost_events_count: 0`, 32 clean restarts | none | heavily reduced: the 12-min / 200-machine soak and the config-fuzzer livelock probe were **NOT RUN** — stated gap, carried from round 6 | **PASS at reduced scale** |

**Diff review `cec108b..221ce7c` (`42-r7-diff-review.md`) was the highest-yield instrument of the round.** It found all three candidate Blockers (L-1/L-2/L-3 → R7-02/R7-03/R7-01) by reading ~1.7k lines of `src/` directly, plus L-4 (→ R7-04, later refuted) and L-6 (→ R7-11), and independently cleared five negatives (`__slots__` compatibility, the #172 counter balance, `_guard_denied_this_step` stickiness, the sentinels / lazy deadline-heap lock / single-pass parser, and `after`-timer charging in practice). **All three Blocker candidates are in the machinery this round added, and all three are in the direction the round-6 notes say the design exists to avoid.**

**Benchmarks.** `bench_a` raw `send()` **257 384 ev/s** (3.89 µs — the fastest recorded, continuing the trend), pure API 35 306 ev/s (in-family). `bench_h`: 500-order fill p95 **0.077 ms** vs a 0.10 ms budget — **PASS**; RSS/open-order 5.18 KB, up from 3.10, unattributed (§2 row 4). `bench_e_actors` 24 216 msgs/s, no leak. `bench_j` policy ratios 0.719 / 0.950 / 0.716 — inside the historical noisy band, **no regression**. `bench_c_timers` ran **reduced** (idle + `load_100` only, `TIMER_SAMPLES` 60→15): ~130–160 ms mean error under 100 busy interpreters, no hang — directionally consistent with BENCH-6's known miss; the `load_500` and `load_500+cpu_hog` tiers were **not run** (time budget), a gap carried forward from round 6, stated not silent. **BENCH-2 unchanged and still missed.** No measurable throughput cost from round 6's per-macrostep settle accounting, with the caveat that no bench here isolates it.

---
## 4. Contract machines (B1–B20) on the library

**All 20 machines build from the corrected catalogue JSON with zero `InvalidConfigError` and zero `ImplementationMissingError`, and drive their invariants end-to-end.** Snapshot/restore at quiescence between every macrostep is clean on every group — zero spurious `SnapshotMidStepError`, zero state/context diffs against the uninterrupted run, identical traces.

| Group | Build | Invariant checks | Snapshot/restore at every macrostep | New **library** defects | Verdict |
|---|---|---|---|---|---|
| **B1–B5** (order core) | 5/5 clean | **112 / 112 PASS** (B1 34, B2 23, B3 21, B4+B5 34) — up from round 6's `B4 9/11`; the round-5/6 OC fixes hold | clean between every macrostep, trace-equal, sync parity | 0 new (exposed to R7-01 via the R6-03 class) | **PASS functionally**, exposed |
| **B6–B10** | 5/5 clean, CD-01-clean | **54 / 55** (was 53/55) — B6 10/10, B7 10/10, B9 16/16, B10 7/7; the single FAIL is `INV-B8-b`, a **stale harness assertion** (HD-01): it asserts the call site raises, but the signal is the receipt, which on `221ce7c` is *better* than before (`denied=False, error=RuntimeError`, #170). The B8 `SL_DEADLINE` pre-emption FAIL from round 6 now **PASSES**. | `c3` **31/31 MATCH**, 0 spurious refusals; `c7` cross-machine reconnect **4/4**, byte-identical to `cec108b` | 1 (LD-03 root-caused into **LD-04 → R7-01**) | **PASS** — B8's remaining failure is liveness and it is **ours** (CD-03) |
| **B11–B15** | 5/5 clean, JSON byte-identical to the baseline | all stated invariants pass; 5/5 happy paths; 5/5 async↔sync parity | 5/5 clean | 1 (LIB-R6-01 → **R7-01**) | **PASS functionally**, **R6-01 class STILL BROKEN** under `async def` |
| **B16–B20** (control) | 5/5 clean | B16 INV-b PASS, B17 **all PASS** (`rollback` replaces the withdrawn `"fail"` cleanly), B18 INV-b/c/e PASS, B19 INV-a + C-02 deferral **closed**, **B20 all PASS**. Failures: C-04 (B16, ours, Blocker), C-05 (B16, ours, Low), C-07b (B18, ours, Blocker), C-06 (B19, ours, High) | clean on all five, zero mid-step refusals, identical traces | 1 (CV-221-01 → **R7-01**) | **PASS on the library for B16/B17/B20**; **B18 and B19 carry the R7-01 shape** |

All six prior control suites (`k0`–`k6`) reproduce **byte-identically** against the `cec108b` results — `SAME` on every one. No regression, and no round-6 improvement, on any behaviour those suites cover.

**The decisive contract-level observation.** B16, B17 and B20 carry **no `invoke` and no `always` at all**, so R7-01 cannot reach them. The library-side exposure is confined to machines that carry an invoke cycle: **B18, B19 on the control side and B1–B9 on the order side.** One operator kill-switch press (`ENGAGE` on B18 with an `async def` service) produced **3 547 `flatten_all_positions` invocations in 3.0 s**, still accelerating, `status="running"`, `changed=True`, `error=None`, with `maxIterations` of 2 / 5 / 25 / 100 / 1000 all behaving identically. The same machine with plain `def` services is bounded exactly at `maxIterations` (7 calls at 5, 52 at 50, 1 002 at the default) with `last_error = RunawayChainError`. **A detail with no semantics in the statechart — how a service function is spelled — decides whether a livelock guard exists at all.**

So: **B10–B17, B19 and B20 PASS on the library**, with B19's exposure closed by CV-C38 (§7) because its only invoke cycle is the `backing_off` retry ladder and that ladder is externally clocked. **B1–B9 and B18 pass functionally but are exposed to R7-01**, and every machine with an external producer is exposed to R7-02.

### Our-contract and wrapper items (the library is correct in every row)

| ID | Sev | Machine | Issue |
|---|---|---|---|
| **C-04** | **Blocker (ours)** | B16 | Elevation survives `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE` and can be acquired *after* `REVOKE` — the `elevation` region declares only `REVOKE`. Correct SCXML parallel semantics; our JSON is wrong. Unchanged, byte-identical to the `cec108b` baseline. |
| **C-07b** | **Blocker (ours)** | B18 | `onUnhandled:"error"` makes a guard-denied `RELEASE` terminal — the kill switch is bricked by a wrong button press. Carried, byte-identical. |
| **CD-03** | High | B8 | `naked ⇄ verifying` unbounded invoke livelock — **4 027 laps / 8.05 s (500/s)**, 4 027 `raise_critical_alert` firings, `status="running"`, `last_error=None`. Our shape; R7-01 is why it is *silent*. Escape hatch intact. Fix: a bounded fallback counter onto `naked_unrecoverable`, edge-trigger the alert on `naked_since`, and a new lint **CV-LINT-XS16** — no two invoking states may target each other on success paths without a bounded counter. |
| **C-06** | High | B19 | `stale_lockout` declares only `RECONNECTED`; the INV-B19-b operator escape hatch does not exist. |
| **C-07** | High | B16–B20 | CV-C31 withdrew `"fail"` in favour of `"rollback"` + explicit `halted` states; **the `halted` states were never written** (`k0_build`: `halted == False` for all five). |
| **CV-B4-01** | High | B4 | `LEG_B_FILL` declared only on `racing`; `completing`/`completed` do not declare it, so it re-defers for ever and `filled_b=0` in a terminal OCO. Patch confirmed; identical at `3ed3099` — not a regression. |
| **OUR-B11-01** | High | B11 | `recording.degraded` has no `STREAM_UNHEALTHY` handler: a second failing stream defers indefinitely and the health map goes stale. One-line JSON fix. |
| **OUR-B14-01** | High | B14 | INV-B14-d's "bounded" pending-delta buffer is prose-only: 1 000 `DELTA` → `buffered_len 1000`, `dropped_by_engine []`. |
| **OUR-B14-02 / OUR-B15-01** | High | B14, B15 | Fallible telemetry (`emit_resync_metric`, `emit_book_desynced`, `write_liquidation_journal`) sits inside the atomic entry set of a **safety** transition under `rollback`, so it cancels the desync / cancels the liquidation. `rollback` behaves as documented — the defect is ours. Note `denied` is asymmetric for the same class of outcome (B15 `True`, B14 `False`), so **`error is not None` is the only usable "did my transition land?" test**. A snapshot after the rollback persists the rolled-back state, so a restart does not clear it. |
| **W-01 / C-01** | High | all | `create_machine` is not a conformance gate — all machines build with a bare `MachineLogic()`. The wrapper must cross-validate the logic table against the JSON at construction. |
| **W-03** | High | B17 | A deferred `ENABLE_REQUESTED` auto-fires the moment evidence lands, reaching `enabled` unattended. |
| **W-04b / DC-3** | **High (wrapper)** | all | `onUnhandled:"defer"` **outranks** the `guard_denied` disposition: 3× `TIGHTEN_SL` denied by a guard → `deferred_count=3`; flip the guard and send `WATCHDOG_MISS` → `set_trading_stop` invocations go 0 → **3**. A refused amend is replayed later against a changed world. Library precedence is defensible; it is the wrong default for an order path. The wrapper must drain denied events from the defer buffer at end of macrostep. |
| **W-05 / DC-2** | Medium | all | `service_executor` / `service_pool_size` do **not** retire CV-C32: `send(PING, wait=True)` latency 0.001 s with `async def` vs **0.441 s** with plain `def` (0.437 s with a custom executor). #149 moves plain services off the loop, but the entering macrostep still awaits the result — the block is **in the macrostep, not the pool**. |
| **C-05** | Low | B16 | `STEP_UP_OK` while already elevated writes no audit record (INV-B16-c). |
| **HD-01** | Low (harness) | B8 | `INV-B8-b` asserts the call site raises; the signal is the receipt. #170 makes `denied` alone correct, so the assertion should be **retired, not re-scored**. |
| **OBS-01** | Low | all | `spawnBlockingTimeout` reads `<missing>` off `MachineNode` on every machine — accepted at `create_machine`, never exposed, so a conformance lint cannot verify the §1.3b block by read-back (library-side R7-17). |

**W-04a is FIXED and retires:** #170 landed, a crashed guard under `guardErrorPolicy:"raise"` now reads `denied=False, error=RuntimeError` on both engines, so `Receipt.denied` alone is once again a correct denial discriminator.

---
## 5. Surviving library defects, by final severity

Refutation moved **three** of the eight Blocker/High candidates, all downward, each with a recorded reason. Nothing was downgraded for convenience; two of the three moves were forced by evidence the refuter generated specifically to *support* the finding and which failed.

### Blocker (2) — both async-only, both silent, both introduced or left open by this round's own fix work

| ID | Refutation | Why it stands |
|---|---|---|
| **R7-01** — `async def` service completions are never charged; every self-generated invoke/rollback cycle is unbounded, and one variant settles into an **empty configuration** reported as success | **CONFIRMED** | Direct lane instrumentation, not inference: plain `{priority:23, inbox:0}` + `RunawayChainError` vs async `{priority:0, inbox:27409}` + `last_error=None`. This **supersedes both competing explanations on file** — it is not the `is_system_event` exemption (`LD-03`, withdrawn) and not merely `_processing` being `False` at resolution (`D7-fuzz-1`, `LD-04`, `CV-221-01`): the coroutine completion never reaches the charging site under *any* value of `_processing`. Arriving `from_inbox` it also resets the settle budget every lap (`:1647`), so it is both uncharged and actively budget-clearing. Every refutation axis fails — **undocumented** (docs present `maxIterations` as unconditional infinite-loop detection); **not API misuse** (`async def` is the library's own recommended style per #174); **no XState v5 cover** (v5 routes actor-done events through the same guarded microstep loop and never exposes an empty configuration while active); **not a duplicate** (all three round-6 pins at `tests/test_round6_findings.py:124/184/486` declare `def svc`, so the suite is structurally blind to this lane). Merges six independently filed findings. Detail: `44-r7-01-refutation.md`. |
| **R7-02** — external `send(priority=True)` is charged to the chain budget; 61 % of legitimate external sends silently dropped as `chain_budget` | **CONFIRMED** | Burst: `sent=3000 processed=1162 dropped=1838 reasons={'chain_budget'}`. A *new non-burst* probe built to refute it (one external send per 0.1 ms from a separate task, 0.5 ms await in the action) still loses **30 %** (1500/890/454). The control — identical load minus `priority=True` — processes **3000, drops 0**, so the public priority lane itself is the cause. **Not documented** (the `send()` docstring promises only ordering plus the `max_queue_size` exemption; the run loop's own architecture note at `:1510-1516` explicitly promises external traffic of any volume is never throttled). **Not API misuse** (public kwarg / `send_priority()`, owning thread, documented fire-and-forget). **No v5 parity** (v5 applies no chain budget to external `actor.send()`; its microstep guard covers raised/eventless transitions only). **Not a duplicate**: #166–#168 concern completions produced *while processing*, and their WHO→WHEN change at `:2287-2288` is precisely what leaks onto the public external path at `:811-812`, while every other enqueue path still uses `_issued_from_own_action()` (`:826`, `:854`, `:1206`). Aggravated by near-silence: the drop path resets `_raise_depth`/`_chain_tripped` (`:1596-1599`) so `last_error` reads `None`. |

### High (4)

| ID | Refutation | Note |
|---|---|---|
| **R7-03** — `await start()` hangs unboundedly on a slow invoked child (#171) | **DOWNGRADE Blocker → High** | Reproduces (no return after 8 s while a child's async entry action sleeps 30 s; `_await_actor_bringups` at `:561`/`:2586` gathers with no timeout and the bring-up awaits user entry actions; no timeout knob exists in `src/`). Downgraded because **the run loop is spawned before the await**: with `asyncio.wait_for(start(), 1.0)` the interpreter is live and unharmed — `POKE` is accepted and processed, the child finishes bring-up afterwards, `stop()` returns cleanly. Impact is a misleading unbounded await with `status="running"`, **fully contained by a one-line caller-side bound** (CV-C39). No deadlock, corruption, lost events or leak. |
| **R7-05** — async `start()` never sets the in-flight flag, so #169's entry-window refusal is inert during initial entry | **CONFIRMED** | `write-accepted / read-refused blobs: async=1 sync=0`; sync REFUSED/REFUSED vs async ACCEPTED with torn `filled_qty=100 avg_px=0` restoring silently, `last_error=None`; 720 torn outcomes **all** in `entry@start`, while `on_transition@start` tears zero times out of 320. Cause confirmed in source: `_processing` is assigned only at `interpreter.py:420/1654/1698`, and `start()` (`:536-556`) runs `_enter_states` + `_settle_transient_transitions` with the flag still `False`, whereas `sync_interpreter.py:370-374` deliberately sets it around the initial descent. #171 *widened* the window by moving initial invoke registration into `start()`. Not documented (`api/index.md:715`/`:1789` promise `SnapshotMidStepError` for exactly this call site), not API misuse (sync refuses on the identical machine; no flag makes async refuse). **One-line fix**: mirror `sync_interpreter.py:370-374`. |
| **R7-07** — a root snapshot harvests a child actor's half-applied context | **CONFIRMED** | Survived the strongest available defence: with the action hook removed entirely and the child's entry action made `async def`, an ordinary caller obeying the documented contract (settled root, `_step_in_flight()` False, snapshot outside every action) still gets `ACCEPTED child=['kid.y'] ctx={'q':100,'p':0}` against settled truth `{'q':100,'p':101}`. Not documented (docs advertise full-hierarchy capture and legality "on both sides"; the #169 comment at `base_interpreter.py:1385-1391` itself says legality is necessary-not-sufficient, then keeps legality as the child-branch test at `:1393-1395`). No v5 cover — v5's synchronous run-to-completion actions have no interleaving point. Not a duplicate: #169 explicitly narrowed to the root. The torn blob restores clean (`error=None`, `status="running"`) because the configuration *is* legal, so no shipped guard detects it. Detail: `44-r7-07-refutation.md`. |
| **R7-08** — `_await_settled_for_snapshot` spins `time.sleep` on the event-loop thread | **CONFIRMED** | `base_interpreter.py:1280-1289` uses `time.sleep(0.0005)`, not `await asyncio.sleep`, inside its deadline loop, and it is called from `get_persisted_snapshot()` (`:1395`) on the child branch. On the async engine this runs on the loop thread, so the mid-step child it waits for **cannot progress**: the wait is guaranteed to burn its full 0.5 s and then return the unsettled blob. Measured 501 ms; with three mid-step children **1 502 ms** — cost scales per child, charged sequentially. A fast/legal child returns in 1 ms, so it is conditional but deterministic once entered. **Compounds R7-07**: the mechanism meant to handle the child case is inoperative on the async engine. |

### Medium (6)

| ID | Note |
|---|---|
| **R7-06** — `machine_hash` `None` or absent silently disables `from_snapshot()` drift verification | **DOWNGRADE High → Medium.** Honest hash → `SnapshotDriftError`; `machine_hash=None` **or the key removed** → ACCEPTED `states=['m','m.a']` while the payload still declares `version 2`, under `verify_machine_hash=True`. `persistence.py:276-277` keys the v0-compat bypass on the **field** instead of the declared **version**, contradicting `snapshots.md:252` and `check_identity`'s own docstring; `tests/test_persistence.py` has no null/absent-hash case. Downgraded because the **tamper framing does not hold** — the hash is a fingerprint, not a MAC, and an attacker able to null it can already rewrite `state_ids`/`context`, which are accepted under any hash setting. The real residual harm is operational: a v2 snapshot whose hash is lost by a lossy transport silently restores into a drifted machine with wrong active states. **One-line fix**: gate on `snapshot.get('version', 0) >= 1`. |
| **R7-09** — a contradictory `configuration` key outranks `state_ids` on restore | Carried from R6-16; covered mechanically by CV-C27′. |
| **R7-10** — `get_persisted_snapshot()` from `on_action_execute` returns a torn blob on async (`status:"running"`, `state_ids: []`); the sync engine refuses the same call | Caught on restore by #143, so this is an observability/parity defect rather than corruption. The third residual window of #169. |
| **R7-11** — sync `_deferred_this_step` never cleared on `wait=False` — unbounded growth | New regression this round; its sibling `_guard_denied_this_step` *is* reset. |
| **R7-12** — `onUnhandled:"error"` fatal kill is invisible to the sender (success-shaped `Receipt`) | One line, same ergonomics class #153 fixed with `denied`. Interacts with our C-07b. |
| **R7-13** — config-level `strict:true` does not gate event names; a `"*"` handler makes `is_known_event()` true for anything | Our catalogue no longer carries `"*"` scaffolding (CV-C34, done), so exposure is bounded by a rule we already enforce. |

### Low (8)

**R7-04 residual** — a self-re-arming **plain-`def`** invoke cycle starves its own inbox by the documented #116 ordering, independent of `maxIterations`, with a documented fix (`async def`). *The budget-renewal claim itself was refuted* — see below. · **R7-14** call-site `QueueOverflowError` refusals fire no `on_event_dropped` (6 021 of 12 087 refusals invisible in a 2 s / 16-thread run; the loop-side half is fixed by #157) · **R7-15** `last_error` is set *after* the drop hooks and cleared by the next success, so it cannot be the backstop · **R7-16** `DEFAULT_SERVICE_POOL_SIZE` documented but absent from `__all__` · **R7-17** `spawnBlockingTimeout` validated then dropped; no attribute on the built machine (our OBS-01) · **R7-18** unknown top-level config keys accepted silently — a typo is a silent downgrade to the default, while a *bad value* for a known key is caught cleanly · **R7-19** `get_persisted_snapshot()` returns a dict, `from_snapshot()` refuses a dict · **R7-20** sync/async lap-count asymmetry inside the *fixed* plain-`def` path.

### The one refutation that killed a finding outright

**R7-04 — REFUTED.** Both repros reproduce, but the *causal claim* ("external traffic renews the per-macrostep settle budget mid-chain") fails three independent tests. (1) **Budget sweep:** varying only `maxIterations` 1→1000 leaves laps-per-event flat at ~3.3 (32 424 / 41 807 / 35 683 / 35 202 laps for 10 800 events) — the claim requires laps to scale with the renewed budget; `maxIterations=1000` is indistinguishable from 50. (2) **The claimant's own control** burned 317 210 laps (4.5× the invoke shape's 70 400) under identical traffic and identical renewal, yet finished with backlog 0 and wedged 0/10 — more renewed laps, zero starvation. (3) **Cause isolation:** holding cycle, budget and traffic fixed and varying only the service form, plain `def` wedges 6/6 (with sleep, without sleep, and with 16× pool workers) while `async def` wedges 0/6 — including a variant burning 54 520 laps, i.e. *more* self-generated work than the wedging case. Removing service latency entirely still wedges, refuting the claim's own cost argument. The discriminating variable is `def` vs `async def` — the documented #116 ordering rule (`production-characteristics.md:95`, `api/index.md:694-695`), with `async def` named as the remedy; applying it clears the wedge. Both repros show `chain_tripped=False`, so the budget is not the governing mechanism for this shape at all. **Merging `L-4` and `D7-concurrency-1` under a budget-renewal cause was a misattribution.** Artefacts: `adversarial/r7-04/`.

*Note the irony worth recording:* R7-04's refutation and R7-01 point at the **same fork** from opposite sides. `def` starves its inbox; `async def` escapes the budget. There is no service kind that is correct on both axes.

### Carried, outside the 20-item count

**#174** (blocking timers — documented, not fixed; busy-loop `after` lateness ~15–30 ms over a 50 ms budget) remains open as a documented limitation, already covered by BENCH-6 and house rule A2. **#175 Case D** (`stop()` leaves duplicate-`Event` receipts unresolved, 160/160) remains open and is reopened this round on the narrower ground that **the shipped regression test is too weak to detect it**. Design-constraint items **DC-1** (`SyncInterpreter` takes neither `max_queue_size` nor `overflow_policy`, so every sync-parity run is an unbounded-inbox comparison — valid for ordering and effects, **not for backpressure**), **DC-2/W-05**, **DC-3/W-04b**, **DC-4** (R7-01 has no configuration that satisfies both it and #174) and **DC-5** (`send_threadsafe(internal=True)` is an honesty-based trust boundary — and it gains weight if provenance moves onto an explicit flag as R7-02's fix requires) are wrapper obligations, not library defects.

---
## 6. Gate decision (per `20-adoption-gate.md` §7)

Applied in order, first match wins, with honest counts:

| Row | Condition | Our count | Matches? |
|---|---|---|---|
| 1 | Any `ERROR` row in the gate output | none — `FAIL=36 / PASS=80`, every FAIL triaged to a known finding, a harness allow-list gap (H-1/H-2) or an expected-FAIL script | no |
| 2 | Suite fails, or coverage < 86 % | 3 418 passed / 1 flake (not reproducible standalone or under either hash seed) / 0 genuine failures; **92.64 %** | no |
| 3 | Snapshot format changed while LC-21 open | LC-21 closed; format versioned and unchanged this round | no |
| 4 | **Any filed Blocker repro still exits 1** | **R7-01 and R7-02 both reproduce unmodified, fresh, at `221ce7c`** | **YES — row 4 wins** |

```
Gate run 2026-09-20 — xstate-statemachine main @ 221ce7c (unreleased 0.8.1)
DECISION: DEFER (order path)  ·  GO for non-order paths under constraints
          — decision-table row 4: the Blocker row is non-empty

  12 issues      : 7 fixed · 2 partial (#167/#168, one defect: R7-01)
                   · 2 documentation-only (#122 correct-as-designed, #174 open)
                   · 1 not-fixed (#175 Case D, with a too-weak shipped test)
  regressions    : 0 true PASS->FAIL in the gate (direct JSON diff vs cec108b)
                   BUT 3 introduced by this round's fix work and invisible to it:
                   R7-02 (Blocker), R7-03 (High), R7-11 (Medium)
  new defects    : 2 Blocker · 4 High · 6 Medium · 8 Low (post-refutation)
                   pre-refutation was 3 Blocker · 5 High · 5 Medium · 7 Low;
                   refutation moved 3 of 8 Blocker/High DOWN, 0 up, 1 REFUTED
  gate script    : verify 29/34 · verifyM 10/15 · verifyM2 3/3 · verifyM3 24/27
                   · repro 13/34 (informational) · probe 1/3
  suite/coverage : 3418 passed / 1 flake / 13 skipped (8m41s) · 92.64% (floor 90%)
                   interpreter.py 91% (was 89%) — the module carrying both Blockers
  benchmarks     : 500-order fill p95 0.077 ms vs 0.10 ms budget PASS;
                   raw send 257,384 ev/s (fastest recorded); policy ratios in band;
                   BENCH-2 unchanged FAIL; BENCH-6 reduced-scope only (load_500 and
                   load_500+cpu_hog NOT RUN) — a stated gap, not a finding;
                   bench_h RSS/order 3.10 -> 5.18 KB, UNATTRIBUTED, needs a bisect
  contracts      : 20/20 build clean; B1-B5 112/112; B6-B10 54/55 (1 stale harness
                   assertion); B11-B15 all invariants; B16-B20 control suites
                   byte-identical to cec108b. B10-B17/B19/B20 PASS on the library;
                   B1-B9/B18 pass functionally but carry the R7-01 shape
  blockers open  : R7-01, R7-02      high open: R7-03, R7-05, R7-07, R7-08
  operative block: UPSTREAM — provenance accounting in interpreter.py: WHO issued an
                   event has been replaced by WHEN it arrived. Self-generated work
                   escapes the budget on the coroutine lane (R7-01); external work is
                   charged on the priority lane (R7-02). Two lines, opposite halves.
  decided by     : adoption audit, round 7
```

**What row 6 would have given.** Absent the two Blockers the open-High count is **4** (R7-03, R7-05, R7-07, R7-08) — inside the ≤5 bar — and each has a **mechanically enforced** mitigation available: CV-C39 (`asyncio.wait_for` around `start()`) for R7-03, CV-C23+CV-C40 (no snapshot before the `children_ready()` barrier) for R7-05, and CV-C41 (root-only snapshots; child state is captured via explicit `sendTo` reporting) for R7-07 and R7-08 together. That is row 6 — **ADOPT WITH CONSTRAINTS**. It is worth being explicit that this is *closer* than round 6 on the High axis in quality terms (every High now has a one-line fix identified in source) and *further* on nothing except that the Blocker count moved from two async-termination defects to two provenance defects.

**Why not "ADOPT with wrappers" anyway — the same answer as round 6, but the evidence is now stronger.** R7-05/R7-07/R7-08 are wrappable and R7-03 is a one-line caller bound. R7-01 and R7-02 are not, and this round *tested* that claim rather than asserting it: DC-4 shows the only mitigation for R7-01 is plain-`def` services, which #174 documents as blocking the machine's own `after` timers, which B19's `backing_off` retry ladder depends on — and the refutation of R7-04 shows plain `def` has its own inbox-starvation failure on the same shape. **There is no service kind that is safe on both axes.** A supervisor cannot help either: R7-01, R7-03 and R7-04's residual all present as `status == "running"` with `last_error is None`, and R7-15 explains why `last_error` cannot be the backstop. **Any supervisor we ship must key on progress counters, never on `status`.**

---

## 7. Constraints

### Retired (3)

| Constraint | Why it retires |
|---|---|
| **W-04a** (read `(denied, error is None)`, never `denied` alone, because a *crashed* guard also set `denied=True`) | **RETIRES.** #170 verified on both engines: the 4-way matrix `(denied, error is None, deferred, changed)` is injective — DENY `(T,T,F,F)`, CRASH `(F,F,F,F)`, unhandled `(F,T,F,F)`, OK `(F,T,F,T)`. `Receipt.denied` alone is a correct denial discriminator again. **The W-04b half does not retire** — `onUnhandled:"defer"` still outranks `guard_denied`, so the wrapper must still drain denied events from the defer buffer (DC-3). |
| **CV-C37** (`children_ready()` barrier because `await start()` returns ~13 ms before invoke children are addressable) | **RETIRES as written — and is immediately replaced by its inverse.** #171 fixed the race: `_actors` is populated the instant `start()` returns, 20× identical trace on both engines. But #171 introduced R7-03, so the barrier is no longer the problem; the *unbounded wait* is. See **CV-C39**. |
| **CV-C36's "hidden shed rate" rationale** (R6-05: loop-side RAISE refusals landed on an unread future with no log and no hook) | **The rationale retires; the rule stands.** #157 is fixed and verified exactly-once (`refused=199, hook_fires=199`; `queue_full_hooks == loopside_refusals` with no other drop reasons). CV-C36 is retained on the independent ground of R7-14 (the **call-site** half still fires no hook — 6 021 of 12 087 refusals invisible) and R7-02 (the chain-budget drop path is visible only through the opt-in hook). |

### Standing (unchanged)

**CV-C01…CV-C22** as amended · **CV-C23** (quiescence-only snapshots via the factory wrapper) — still the primary read-side defence, now covering R7-10 as well · **CV-C25** (no external `send()` from inside an action; gateway queue only) — now *also* the containment for R7-02, since the gateway is the single place a `priority=True` send can be forbidden · **CV-C27′** (`state_ids ⊆ configuration` on restore) — R7-09 is unchanged · **CV-C28** (no `LoggingInspector` in production) · **CV-C31′** (no `"rollback"` with a raisable entry action on an `invoke`-carrying state) — **re-affirmed and widened in effect**: the B18 measurement (3 547 `flatten_all_positions` calls in 3.0 s from one `ENGAGE`) is the sharpest evidence this constraint has ever had · **CV-C32** (async engine → every service `async def`; sync engine → every service plain `def`) — **stands, uncomfortably**: it is what keeps R6-09's downgrade valid and it is exactly what puts every contract machine on R7-01's unprotected lane. Record the consequence plainly: **sync parity remains unavailable, not merely untested, for any machine with services**, and DC-1 adds that sync parity is not a backpressure comparison either · **CV-C33** (`send_threadsafe` only via our gateway) · **CV-C35** (no `always` into an invoked child, no `always` to an ancestor of its own source) · **CV-C36** (every `send_threadsafe` future is read; refusals counted and paged).

### New (5)

| ID | Rule | Enforced by | Covers |
|---|---|---|---|
| **CV-C38** | **No order-path or control-path machine may contain an invoke cycle** — two invoking states that can target each other on success paths, or an `invoke.onDone` that can re-enter its own source — **unless a bounded attempt counter in context gates the re-entry.** | Linter pass over the catalogue JSON (**CV-LINT-XS16**) + a contract test per machine carrying an `invoke` | **R7-01 (Blocker)** containment, CD-03 |
| **CV-C39** | **`await start()` is always bounded**: the factory calls `asyncio.wait_for(interp.start(), CV_START_TIMEOUT)` and treats a timeout as a *warning with the interpreter live*, never as a failure to start. Nothing in the codebase may `await start()` bare. | Factory wrapper (the only construction path) + a lint banning bare `start()` | **R7-03 (High)** |
| **CV-C40** | **No snapshot may be taken before the factory has observed the machine settled after `start()`** — the initial-entry window is explicitly excluded from the snapshot-eligible set, not merely "usually quiescent". | Factory `snapshot()` wrapper: refuses until a post-start settle observation is recorded | **R7-05 (High)** |
| **CV-C41** | **Snapshots capture the root only.** Child-actor state is reported upward by explicit `sendTo` into parent context and persisted from there; the wrapper never relies on the hierarchical capture, and never calls `get_persisted_snapshot()` on a parent whose children may be mid-step. | Factory wrapper + a contract test asserting the persisted blob's child branch is ignored on restore | **R7-07, R7-08 (High)** |
| **CV-C42** | **`priority=True` is forbidden outside wrapper code**, and the gateway never sets it on an externally originated event. Every gateway send records a shed counter keyed by `on_event_dropped` reason, and a non-zero `chain_budget` count on an external send pages immediately. | Gateway API shape + lint on `priority=`/`send_priority(` + an alert rule | **R7-02 (Blocker)** — *containment only, not a fix*; the loss is still upstream |

**Also promoted to constraint clauses, not new IDs.** Under CV-C06: the wrapper's "did my transition land?" test is **`error is not None`**, because `denied` is asymmetric across machines for the same class of outcome (B15 `True`, B14 `False`) — and a snapshot after a `rollback` persists the rolled-back state, so a restart does not clear it. Under CV-C25: the wrapper's health signal is a **progress counter**, never `status` or `last_error` (R7-01/R7-03/R7-15). Under CV-C23: the restore path treats an absent or null `machine_hash` on a `version >= 1` payload as a **drift failure**, since the library accepts it (R7-06).

### Recomputed mandatory configuration block

```jsonc
{
  // --- error handling -------------------------------------------------
  "actionErrorPolicy": "rollback",   // DEFAULT, all non-order machines.
                                     // CV-C31′: FORBIDDEN on any state that carries an
                                     // `invoke` and has a raisable entry action. Measured
                                     // at 221ce7c on the real B18: one ENGAGE produced
                                     // 3,547 flatten_all_positions calls in 3.0 s, still
                                     // accelerating, status="running", error=None, and
                                     // maxIterations 2/5/25/100/1000 all identical (R7-01).
  "actionErrorPolicy": "fail",       // ORDER-PATH states with invoke + raisable entry.
                                     // #145 verified and re-confirmed this round: halts with
                                     // status="stopped", configuration cleared,
                                     // TransitionFailedError retained, halted blob refused by
                                     // from_snapshot. Pair with an explicit `halted` state
                                     // entered from on_transition_failed — C-07: these states
                                     // are STILL MISSING on B16–B20 (E50-T16).

  "guardErrorPolicy": "raise",       // #152 + #170 verified: cancels only the FAILING
                                     // candidate; the unguarded fallback is still taken; and
                                     // (denied, error, deferred, changed) is now INJECTIVE, so
                                     // W-04a retires — `denied` alone is a correct
                                     // discriminator. W-04b stands: `defer` still outranks
                                     // guard_denied, so drain denied events from the buffer.

  "onUnhandled": "defer",            // order path. No "*" scaffolding (CV-C34, done).
                                     // Authorisation/risk events are non-deferrable (W-03).
  "onUnhandled": "error",            // control machines ONLY, and NOT on B18 — C-07b: a
                                     // guard-denied RELEASE is terminal, i.e. the kill switch
                                     // is bricked by a wrong press. Note R7-12: the fatal kill
                                     // is invisible to the sender (success-shaped Receipt).

  "strictTargets": true,             // #147: RootTargetError at build time, non-downgradable.
  "strict": true,                    // NOTE R7-13: config-level `strict` does not gate event
                                     // NAMES; a "*" handler makes is_known_event() true for
                                     // anything. Safe for us only because CV-C34 removed "*".
  "maxIterations": 500,              // KEEP, but DO NOT RELY ON IT. Inert against R7-01: an
                                     // `async def` completion is published on the public inbox
                                     // lane (interpreter.py:2414) and never reaches the
                                     // charging site (:2287-2288), and arriving from_inbox it
                                     // also RESETS the settle budget every lap (:1647).
  "spawnBlockingTimeout": 5000       // R7-17/OBS-01: validated then dropped — no attribute on
                                     // MachineNode, so a conformance lint cannot assert it
                                     // post-build. Also R7-18: a TYPO in any top-level key is
                                     // accepted silently and downgrades to the default, so the
                                     // wrapper must whitelist keys itself.
}
```

```python
# Runtime construction — mandatory
MachineLogic(strict=True)             # W-01: create_machine is NOT a conformance gate; the
                                      # wrapper cross-validates the logic table against the JSON.
Interpreter(..., max_queue_size=64, overflow_policy=OverflowPolicy.RAISE,
            service_pool_size=<explicit>)   # #173 verified; default is 4. DC-1: SyncInterpreter
                                      # accepts NEITHER max_queue_size NOR overflow_policy, so
                                      # sync parity is not a backpressure comparison.

# Services: async def ONLY on the async engine (CV-C32). Blocking work via asyncio.to_thread.
#   Accept explicitly: this is what puts us on R7-01's UNPROTECTED lane. CV-C38 is the
#   containment — no unguarded invoke cycle may exist in the catalogue.
# start():  ALWAYS asyncio.wait_for(start(), CV_START_TIMEOUT) — never bare (CV-C39, R7-03).
# Snapshot: factory wrapper only; at quiescence (CV-C23); never before the post-start settle
#   observation (CV-C40, R7-05); ROOT ONLY, child state via explicit sendTo (CV-C41, R7-07/08).
# Restore:  refuse a version>=1 payload whose machine_hash is null or absent (R7-06);
#   assert state_ids ⊆ configuration (CV-C27′, R7-09).
# Sends:    gateway only; priority=True forbidden outside wrapper code (CV-C42, R7-02);
#   every send_threadsafe future is read and refusals counted (CV-C36, R7-14).
# Health:   progress counters ONLY. `status` and `last_error` are not liveness signals
#   (R7-01, R7-03, R7-15).
```

---
## 8. Release-readiness note for the team (before tagging 0.8.1)

Seven rounds in, the fix quality is high and the *direction* is right: this round closed a genuine Blocker (the `m9` send-hang, 6/6 hangs → 0), landed the root-level snapshot refusal, made the receipt matrix injective, fixed the threadsafe counter, made the pool size public, and made the loop-side RAISE refusal exactly-once observable. Raw `send()` throughput is the fastest ever recorded. Coverage is above its own new floor with headroom, and `interpreter.py` climbed from 89 % to 91 %.

**Four things stand between `221ce7c` and a tag we would pin.**

1. **The version is still unbumped.** `__version__` reports `0.8.0` on a commit whose CHANGELOG describes 0.8.1. Seven verification rounds have now keyed on commits because of this. Bump it in the same commit that tags, or the "key on the commit, never the version" escape hatch has to survive into a *released* artefact — which is much worse than needing it pre-release.
2. **Do not tag until R7-01 and R7-02 land.** A 0.8.1 cut at `221ce7c` releases two silent Blockers: one that makes every `async def` invoke cycle unbounded (with a variant that settles into an empty configuration reporting success) and one that silently drops 30–61 % of external `send(priority=True)` traffic. Both are in code this release added. Both are two lines of provenance accounting. Neither is wrappable.
3. **Parametrise the service kind in the regression suite — this is the highest-value change available.** All three round-6 pins declare `def svc` (`tests/test_round6_findings.py:124/184/486`). Six independently filed findings folded into R7-01, and **one `@pytest.mark.parametrize("kind", ["def", "async def"])` would have caught every one of them** before the fixes shipped. Make it a standing rule: any test that invokes a service runs under both kinds. The same principle applies to engine parity — the round-6 lesson ("fixed on the engine the issue was filed against") and the round-7 lesson ("fixed on the service kind the test was written against") are the same lesson twice.
4. **Strengthen two shipped tests that pass while their defect is live.** #175's regression test pins `ok == applied`, which holds while Case D is broken; `tests/test_persistence.py` has no null/absent-`machine_hash` case (R7-06). A test that cannot fail on the defect it names is worse than no test, because it closes the issue.

**Also worth landing before the tag, in rough value order:** R7-05 (one line, mirror `sync_interpreter.py:370-374` in `Interpreter.start()`); R7-03 (a timeout parameter on `_await_actor_bringups`); R7-08 (`await asyncio.sleep` instead of `time.sleep` — a one-token fix that currently blocks the event loop for 0.5 s per mid-step child); R7-06 (gate on `snapshot.get('version', 0) >= 1`); R7-11 (clear `_deferred_this_step` on the `wait=False` path, exactly as its sibling already does); R7-12, R7-14, R7-15, R7-16, R7-17, R7-18, R7-19 — all small, all ergonomics or observability, all independently reproduced.

**One measurement to repeat before tagging:** `bench_h` RSS per open order moved 3.10 KB → 5.18 KB across this round. We are explicitly **not** asserting that as a regression — single run, no bisection, and the direction is opposite to what the hot-path PRs claim. But 67 % on a memory figure that gates BENCH-4 deserves a bisected re-run rather than a shrug.

---

## 9. What would change the verdict

**Close R7-01 and R7-02 with pinned tests that are parametrised over service kind → the Blocker row clears.** Open-High is then **4** (R7-03, R7-05, R7-07, R7-08), inside the ≤5 bar, each with a mechanically enforced mitigation and a contract test in `tests/xstate_contract/` (CV-C39, CV-C40, CV-C41 covering the last two together). That is decision-table **row 6 — ADOPT WITH CONSTRAINTS on the order path.** If R7-03 and R7-05 land alongside — both are one-liners in the same file — the count is 2 High and the margin is comfortable.

Nothing else needs to move. The Medium and Low rows are wrappable, ticketed, or documentation.

**Re-verification recipe (~45 minutes):**

```
gate/run_gate.py                                         # incl. the new verify-main-221ce7c set
battle-221ce7c/fuzz/q1_async_invoke_runaway.py           # R7-01: async def MUST trip like def
battle-221ce7c/fuzz/q14_torn_repro.py                    # R7-01: 0/10 empty configurations
issues/post-221ce7c/new/repro/R7-01_async_service_lane_uncharged.py
issues/post-221ce7c/new/repro/R7-02_external_priority_charged_to_chain_budget.py  # 0 dropped
battle-221ce7c/persistence/q1b_start_entry_window_min.py # R7-05: async==sync==0
battle-221ce7c/contracts/q10_wrapper.py                  # B18 bounded under async def
battle-221ce7c/contracts/repro/g5_r603_r601_shapes.py --service-kind=async
contracts: B1, B8, B18, B19 end-to-end on both service kinds
bench_c_timers load_500 + load_500_plus_cpu_hog          # the tier not run for two rounds
bench_h                                                  # bisect the RSS/open-order move
```

**What would make the verdict *worse*:** a 0.8.1 tag cut at `221ce7c` as it stands — see §8 item 2. Second worst: closing #167/#168/#175 on the strength of the currently shipped tests, since all three pass while their defect is live.

---

## 10. Next steps for CandleViewer

1. **Post round 7 upstream.** Drafts staged in `issues/post-221ce7c/` (**not posted**): 7 confirm-closed comments, 2 narrow reopens (#167, #168 — one defect, R7-01), 1 reopen on test-strength grounds (#175), 1 documentation-only acknowledgement (#174), 1 confirm-as-designed (#122), new-issue files with standalone repros for every CONFIRMED Medium-and-above library defect (R7-01, R7-02, R7-03, R7-05, R7-06, R7-07, R7-08, R7-09, R7-10, R7-11, R7-12, R7-13), and a refreshed `meta-26.md` carrying this scorecard and the release note. Manifest: `issues/post-221ce7c/manifest.json`. **Lead with the service-kind parametrisation** — as in round 6, the test-surface change is worth more to the project than any individual fix.
2. **Start the non-order machines on the library now** (E50 enablement): B10–B17, B19, B20 under CV-C01…CV-C42 as recomputed in §7. A real GO. Those machines build clean, pass every invariant, snapshot and restore at every macrostep with trace equality, and the control suites reproduce byte-identically against the previous round. B19 is included because CV-C38 bounds its only invoke cycle; B18 is **excluded** until R7-01 lands, because its kill-switch path *is* the unbounded shape.
3. **Order path stays on the in-house shim.** `E50-X01` re-runs when the two provenance lines land upstream.
4. **Fix our own catalogue first — two of our defects are Blockers on any runtime.** C-04 (B16 elevation survives `LOGOUT`/`REVOKE`) and C-07b (B18 kill switch bricked by a guard-denied `RELEASE`). Then CD-03 (B8, with the new CV-LINT-XS16), C-07 (the `halted` states CV-C31 promised and nobody wrote), CV-B4-01, C-06, OUR-B11-01, OUR-B14-01, OUR-B14-02/OUR-B15-01 (move fallible telemetry out of the atomic entry set of safety transitions).
5. **E50 ticket movement:** mark the round-6 chores verified; record the X01 verdict as DEFER (order) / GO (non-order); **retire** `E50-T19` (the `children_ready()` barrier — #171 fixed the race) and replace it with the bounded-`start()` ticket; **new** tickets for CV-C38 (invoke-cycle lint), CV-C40/CV-C41 (snapshot window and root-only capture), CV-C42 (the `priority=True` ban and shed alerting), and the two harness fixes H-1/H-2 in `run_gate.py`; **re-scope** `E50-T16` to write the missing `halted` states.
6. **Shim retirement plan — a ladder, not a switch.** (a) Non-order machines move now; the shim keeps the order path and B18. (b) When R7-01 and R7-02 close, run the dual-runtime conformance harness (`E50-T03`) over B1–B9 and B18 on **both service kinds** for one full sprint with the library in shadow mode — same events, compared dispositions, zero divergences required. (c) Cut over one machine at a time, starting with B9 `rule_instance` (no money on it) and ending with B1 `order`. (d) The shim is deleted only after B1 has run 30 days in production with no divergence. Budget two sprints *after* the upstream fix lands, not before.
7. **Pin policy:** `xstate-statemachine == 0.8.1` **once tagged, and only if the tag is cut after R7-01/R7-02 land**. Until then, git commit `221ce7c` for evaluation only, endorsement withheld, with source sha256 recorded. Key on the commit, never the version string.

---

## Evidence index

`43-r7-findings-register.md` (register of record) · `40-r7-regression.md` · `41-r7-suite-bench.md` · `42-r7-diff-review.md` · `44-r7-01-refutation.md` · `44-r7-07-refutation.md` · `adversarial/r7-04/README.md` (+ `a1_budget_scaling.py`, `a2_cause_isolation.py`) · `issues/post-cec108b/new/r7-02-refutation.md` · `battle-221ce7c/*.md` (8 tracks) · `battle-221ce7c/contracts/*.md` (4 groups) · `issues/verify-main-221ce7c/*` (11 scripts + 12 result files) · `gate/result-main-221ce7c.json` · `probes/main-221ce7c/p1..p10` · suite / coverage / bench runs recorded in §2 and §3 (2026-09-20, Python 3.13.7, Windows 11 Pro 10.0.26200).
