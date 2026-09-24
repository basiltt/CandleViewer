# 49 — Round-8 FINAL readiness verdict: `xstate-statemachine` main @ `6db65d8` (unreleased 0.8.1)

Date: 2026-09-21. Question asked by the owner: *"Verify all reported issues are genuinely closed; is the library completely ready, fully battle-tested, and are we good to proceed?"*

**Identify this build by commit, never by version string.** `__version__` still reports `0.8.0` on `6db65d8` (merge of PR #191, `fix/0.8.1-round7`) while `CHANGELOG.md [Unreleased]` targets 0.8.1. Every pin, gate baseline and CI assertion keys on the commit plus its source sha256.

Method: 16 issue verifications (round-7 fixes #179–#190 plus reopened #167/#168/#174/#175) re-run live in a fresh venv; full regression sweep (`45-r8-regression.md`); library suite + coverage (`46-r8-suite-bench.md`); diff review `221ce7c..6db65d8` (`47-r8-diff-review.md`); all 8 battle tracks re-run with new attacks against this round's own machinery (`battle-6db65d8/*.md`); all 20 contract machines driven end-to-end **on both service spellings** (`battle-6db65d8/contracts/*.md`, `contracts/r8/`); then triage → dedupe → **independent adversarial refutation of every Blocker and High** (`48-r8-findings-register.md` + the refutation verdicts applied below, `49-r8-04-refutation.md`, `49-r8-05-refutation.md`, `issues/refute-r8/R8-03-verdict.md`).

**Financial-OMS standard applied throughout:** nothing counted without a standalone repro on a clean interpreter, and **every service-related check run with both `def` and `async def` services** — the axis that round 7 proved decides whether a guard exists at all.

---

## 0. The answer

### Are the 16 reported issues genuinely closed?

**Fifteen of sixteen changed code and hold on re-verification; one was documentation-only. But five of the fifteen are closed *narrower than they were claimed*, and one of those five opened this round's only Blocker.**

- **FIXED, clean, verified on both service kinds and both engines (10):** **#167, #168, #175, #182, #183, #184, #187, #188, #189, #190.** Each re-runs green in `issues/verify-main-6db65d8/*.result.md`, each with the `def` / `async def` cells at parity. #175's duplicate-`Event` `stop()` race is 300/300 with 0 bad successes. #183/#184 close the child mid-step harvest *and* the loop-spin together. #189 makes the `onUnhandled:"error"` kill visible on the sender's receipt on both engines.
- **FIXED with a surviving residual (5):** **#179** (completions are charged now — but the parity claim "same lap count on both spellings" is false for `invoke` ping-pong and rollback+`onDone`: **R8-11**), **#180** (external priority sends are no longer charged — but the drop site was never taught the same provenance rule, which is **R8-01, this round's Blocker**), **#181** (`start(children_timeout=)` bounds a coroutine child entry action — but is a **no-op against a plain-`def` child entry action, and suppresses its own WARNING**: **R8-03**), **#185** (null/absent `machine_hash` on a versioned blob is drift — but a `version: 0` downgrade walks past it: **R8-06**, refuted down to Low), **#186** (`configuration`/`state_ids` must agree — but the rule is **one-sided**; emptying either field short-circuits it: **R8-08**).
- **DOCUMENTED-ONLY, no code change (1):** **#174.** A plain-`def` service still blocks its own machine's `after` timers (~514 ms against a 100 ms budget, unchanged). The `async def` remedy now fires near on-time (125 ms) as a side effect of the round-7 rework. Correctly documented at `docs/_guide/production-characteristics.md:93`, and that documentation is load-bearing for the refutation of R8-02.

**The round's one sentence: the provenance rule that round 7 introduced was implemented on one side of the ledger.** `_deliver_priority` consults *who issued* an event when deciding whether to **charge** it (`interpreter.py:2342-2389`), and does not consult it when deciding whether to **shed** it (`:1598`). So a priority event issued from an action is never charged and runs unbounded, while an external priority event arriving at an already-tripped chain is silently destroyed. Same lane, same FIFO, opposite errors — exactly the shape of round 7's own headline mistake, one layer down.

### Is the library fully battle-tested and ready?

**No — not for the order path, and the reason is one defect, not a class.** After independent refutation the round leaves **1 Blocker · 3 High · 7 Medium · 4 Low** live library defects. Refutation moved **three of six** Blocker/High candidates *down* (R8-02 Blocker→High, R8-04 High→Medium, R8-06 High→Low) and **none up**. That is the best post-refutation position in eight rounds: round 7 closed with 2 Blocker · 4 High, round 6 with 2 Blocker · 2 High, round 5 with 4 Blocker · 8 High.

The single surviving Blocker:

- **R8-01 (Blocker, CONFIRMED)** — **the priority lane charges by provenance and sheds by position.** Reproduced both halves fresh at `6db65d8`, both service kinds. *(a)* `r8b_priority_self_send_livelock.py` → **2/2 priority cells LIVELOCK past the watchdog**, `trip_observable: false`, `start()` never returns, no drop hook, `last_error is None`; the plain-lane control with an identical machine shape is bounded (27 laps against `maxIterations` 25, `RunawayChainError` + a `chain_budget` drop). *(b)* `d8_s1_priority_shed.py` → the `def` lane silently loses **8–9 of 2 000 external `EXT` events** as `chain_budget`, with `send()` accepted and `last_error is None`; the `priority=False` control loses **0** on both service kinds. Every refutation axis fails: **not documented** — `docs/api/index.md:1788` promises the opposite ("a caller's `send()` on either lane (`priority=True` included) never is [charged]") and `docs/_guide/interpreters.md:514-524` presents `priority=True` as ordinary usage; **not API misuse** — the identical construct on the plain lane is explicitly supported, charged at `:898-908` via `_issued_from_own_action()` (#90), and behaves correctly in the control; **no XState v5 cover** — v5 has no priority lane and no chain budget, so it cannot sanction either half; **not a duplicate** — this is the regression surface of #180, and `tests/test_round7_findings.py:413-520` only ever exercises *externally issued* priority sends, never one issued from an action and never an external priority event arriving at an already-tripped chain.

### Are we good to proceed?

- **Non-order paths (B10–B17, B19, B20 — recording, replay, connection, ingestion supervision, paper matching, auth, live-enablement, reconciliation, risk lockout): YES — proceed now**, under the constraints recomputed in §7. Every one builds clean from the corrected catalogue JSON, passes its invariants on **both** service spellings, and snapshots/restores at every macrostep with trace equality. `battle-6db65d8/contracts/r8/` records **B16–B20 all LIBRARY-GO** with round 7's CV-221-01 Blocker closed *at identical lap counts on both lanes* (`maxIterations` 2/5/100 → 4/7/102 service calls, `max+2` exactly, cell-for-cell identical `def` vs `async def`). B18 is **no longer excluded on library grounds** — the kill-switch livelock plateaus at 1 002 calls with `last_error = RunawayChainError`. What still blocks B16 and B18 is **ours**: C-04 and C-07b, both catalogue Blockers on any runtime.
- **Order path (B1–B9, B18): NO — DEFER.** One Blocker, unwrappable in the general case, and it sits on the exact lane an OMS uses for risk checks, cancels and kill switches: silent unbounded livelock on a self-issued priority event, silent destruction of external priority events on the acknowledged-success order path.

**What blocks, and whose it is.** The block is **UPSTREAM**, and it is now **one line**: teach the drop site at `interpreter.py:1598` the provenance rule the charge site at `:2342-2389` already knows. Concretely — (i) charge a priority event whose `_issued_from_own_action()` provenance is truthy, whatever `engine_completion` says; (ii) never shed an externally-issued priority event on `_raise_depth > limit`, because that counter is about *self-generated* work. Same two-clause fix, same file, same function family as round 7's #180. Nothing in our wrapper can substitute for it: we can forbid `priority=True` in our own code (CV-C43 below), but we cannot stop the library from shedding external priority traffic that the *library itself* routes onto that queue, and we cannot make an unobservable livelock observable from outside — `status` stays `"running"`, `last_error` stays `None`, and in-process `asyncio.wait_for` never fires because the loop thread is the thing that is starved.

**Two things that would have been Blockers and are not, and why that matters.** R8-02 (plain-`def` services) was refuted down to High: the headline claim — that the service runs inline on the loop thread and blocks the process — is **false**; #149 moved it to `loop.run_in_executor` (`interpreter.py:2811-2836`), the stall is `interpreter.py:1571-1577` awaiting `_await_inline_services()` and starves **only that machine's inbox**, and that behaviour is documented at `docs/_guide/production-characteristics.md:93` under #174, including the prescribed remedy. What survives is narrower and real: a `def` service is **uncancellable** (CANCEL loses to `done.invoke` on the priority lane) and a `def` invoke is **not unwound by `rollback` or by an `always` roll-forward**, because the executor handoff happens at entry, before the `always` chain and the rollback epilogue — whereas the `async def` task's arming *is* unwound. That is contained mechanically by CV-C32 ("always `async def` + `asyncio.to_thread`"), which we already mandate and lint. R8-04 was refuted down to Medium after its trigger was shown to be a chart the library documents as invalid (an unguarded `always` targeting a state in its own region, which self-re-enables and trips `RunawayChainError` with **zero** external traffic) and after its "permanent starvation" claim failed against a 12 s settle: 300/300 delivered, both queues drained, machine back in stable `m.a`.

---

## 1. The 16 issues

| # | Claim in `CHANGELOG [Unreleased]` | Verified disposition at `6db65d8` | Residual |
|---|---|---|---|
| **#167** | rollback → re-arm spin is bounded | **FIXED** — bounded at 1002 (`maxIterations`+2 slack) across `def`/`async def` × `Interpreter`; `chain_budget` drop fires; sync trips via the `boom` `RuntimeError`. `SyncInterpreter`+`async def` correctly `NotSupportedError` (N/A). | — |
| **#168** | invoke ping-pong trips `RunawayChainError` | **FIXED** — `ver`↔`arm` trips with a `chain_budget` drop for both kinds on `Interpreter`, and for `def` on `SyncInterpreter`. | lap counts differ sync vs async (**R8-11**, Medium) |
| **#174** | blocking-timer behaviour documented | **DOCUMENTED-ONLY** — plain-`def` service still blocks the same machine after a timer (~514 ms vs a 100 ms budget), unchanged in code; `async def` remedy fires at 125 ms as a side effect of the round-7 rework. | the documentation is now load-bearing (refutes R8-02's headline) |
| **#175** | duplicate-`Event`-instance `stop()` race | **FIXED** — 300/300 success, 0 bad successes, both action kinds, 20×20 trials. | — |
| **#179** | all completions via `_publish_completion` → priority lane, charged | **FIXED (verified)** — repro no longer reproduces; both cells trip `RunawayChainError` at parity; pinned tests pass. | parity claim false for ping-pong / rollback+`onDone` (**R8-11**); `_chain_owed` leaks on `BaseException` exit (**R8-10**) |
| **#180** | external priority sends never charged (provenance by WHO) | **FIXED on the charge side only** — 0 drops for both `priority=True/False` in the filed repro. | **R8-01 (Blocker)** — the *drop* site never learned the rule |
| **#181** | `start(children_timeout=, default 2 s)` | **FIXED for coroutine child entry actions** — repro returns in ~2.01 s instead of hanging 30 s. | **R8-03 (High)** — no-op against a plain-`def` child entry action; WARNING suppressed; bound is aggregate not per child |
| **#182** | in-flight flag over `start()` descent and every action hook | **FIXED (verified)** — both engines REFUSE the initial-entry snapshot, 0 torn blobs each. | **R8-09** (Medium): the hook `on_interpreter_start` still yields a torn blob |
| **#183** | child mid-step refused instantly; cross-thread child waited | **CONFIRMED-FIXED** — never harvested half-applied, both engines, 37/37. | **R8-14** (Low): `child=False` mis-reported |
| **#184** | wait no longer spins the loop thread | **CONFIRMED-FIXED** — same-thread children refused in <0.1 s instead of burning 0.5 s. | — |
| **#185** | null/absent `machine_hash` on a version ≥ 1 payload = drift | **CONFIRMED-FIXED** — both mutations refused; v0 and `verify_machine_hash=False` paths unaffected. | **R8-06** (Low after refutation): `version: 0` downgrade walks past it |
| **#186** | contradictory `configuration`/`state_ids` refused | **CONFIRMED-FIXED** — `SnapshotCorruptError`; agreeing/absent cases restore normally. | **R8-08** (Medium): one-sided — empty either field short-circuits |
| **#187** | `on_action_execute` snapshot refused | **FIXED** — both engines, `def`+`async def`, live + pytest, no residual. | — |
| **#188** | sync per-step scopes cleared every step | **FIXED** — `_deferred_this_step` bounded at 1 on `wait=False` (5000×) and `wait=True`. | — |
| **#189** | `onUnhandled: error` kill visible on sender's receipt | **FIXED** — both engines, `def`+`async def`, live + pytest. | — |
| **#190** | config-level `strict` inherited; `*` does not defeat strict | **FIXED** — both engines; dispatch unaffected. | **R8-15** (Low): unknown top-level keys still accepted silently |

**Score: 15 fixed in code (10 clean, 5 narrower than claimed), 1 documentation-only, 0 not-fixed.** For the first time in eight rounds there is **no "NOT-FIXED" row**.

---

## 2. Regressions

**Zero true PASS→FAIL regressions in the gate.** `45-r8-regression.md` records exactly 2 PASS→FAIL deltas against `result-main-221ce7c.json`, both in the `verifyM3` set (`154` sync-restore clock attach, `158` non-str event-type restore), and both are **ours, not the library's**: those two round-6 scripts hand-build a `version: N` snapshot blob with no `machine_hash` field, a shape that #185 now — correctly, and per the CHANGELOG — refuses as drift before the script reaches the behaviour it was written to probe. `158`'s sub-case `[B]`, the one path that does not depend on identity-check ordering, still PASSes, confirming the underlying #158 fix is intact. **Documented-superseded, not a regression.** Action item on our backlog: add a `machine_hash` to both fixtures.

Totals moved `FAIL 36→38, PASS 80→89` only because this run folds in the 11 round-7 `verifyM4` checks that had not been wired into the recorded JSON at `221ce7c`; **every `verifyM4` cell matches its recorded round-7 value 1:1** (10 PASS, 1 expected FAIL at `167`). The 17 blocking FAILs are all pre-existing and already triaged; none is new. Flake re-runs ×5 on `167`, `PROBE-01` and `PROBE-03` were deterministic — same cells, same details, every run.

**Regressions introduced by this round's own fix work, invisible to the gate — the count fell from three to one:**

| # | Item | Severity | Verdict |
|---|---|---|---|
| 1 | **R8-01** — #180 taught the *charge* site provenance and left the *drop* site keyed on queue position | **Blocker** | **TRUE REGRESSION, new in round 7's fix set.** Re-opens half of the failure class #180 was written to close. Causation proven by control: the same load on the plain lane drops 0; the same machine shape with `priority=False` is bounded. |
| 2 | **R8-10** — `_chain_owed` leaks permanently on a `BaseException` service exit and is settled by a bare counter, not matched to the debt | Medium | **TRUE REGRESSION** — new machinery from #179. |
| 3 | **R8-11** — #179's service-kind parity claim is false for `invoke` ping-pong and rollback+`onDone`; sync and async cut the same chart at different lap counts | Medium | **PARTIAL REGRESSION / over-claim.** The fix is real; the parity statement in the CHANGELOG is not. |
| 4 | `bench_h` RSS/open-order 3.10 → 5.18 KB | unattributed | **Carried forward unresolved from round 7.** Still one run, still no bisection. Not counted as a finding; still deserves the bisect before a tag. |
| 5 | Suite flake: `TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations` | — | **Flake, not a finding.** 2 subtest failures inside the full 3 457-test run; 3/3 standalone passes at 2.2–2.3 s. Same load-sensitive lap-count assertion round 7 saw. |

**Suite / coverage:** `3 457 passed, 2 failed (one flake, both subtests of it), 13 skipped` in 878.9 s; coverage **92.70 %** against the 90 % floor (+2.70 pt). `tests/test_round7_findings.py` collects **37** tests and its `KINDS = ("def", "async def")` parametrisation was verified by direct read across the service/action-bearing tests and both engines — the round-7 release note's highest-value ask **landed**. `PYTHONHASHSEED` sweep and the full benchmark series were **not run** this pass (the coverage run alone consumed ~15 of the 20-minute budget) — stated, not silent, and carried as a gap into §8.

**Harness defects (ours):** H-1/H-2 from round 7 are **fixed** in `run_gate.py` (`VERIFYM3_BASELINE_FAILURES` now carries `150`/`probe`; `VERIFY_BASELINE_FAILURES` exists). **H-3, new:** the two stale `machine_hash`-less fixtures above. **H-4, new:** `run_gate.py` had no `verify-main-6db65d8` set — added by this pass (§10).

---

## 3. Battle-test scorecard (`6db65d8`, post-refutation)

Async-lane coverage is called out per track because it is the axis that decided the last two rounds. "Both lanes" means every service-bearing cell was run twice, `CV_SVC_STYLE=async` and `CV_SVC_STYLE=def`, with the two runs compared cell by cell.

| Track | Prior defects re-run | Async-lane coverage this round | New findings | Verdict |
|---|---|---|---|---|
| **Concurrency** | `D7-concurrency-1/2/3` re-run; all closed on the coroutine lane | **Full** — 80 s / 200-machine soak on `async def`: 12 350 external priority events, **0 dropped, 0 wedged, 0 torn snapshots, 0 task leaks**, CPU 1.01 s/wall s | R8-01(a), R8-02 residual, R8-03, R8-09, R8-13 | **The round's inversion: the coroutine lane is now the healthy one; the residue moved to plain `def`** |
| **Determinism & replay** | all 19 round-6/7 scripts copied verbatim and re-run; **all prior defects remain FIXED** | **Full** — `g7_livelock_fuzz.py`: 500 configs × {`def`,`async def`} × {sync, async}: **0 hangs, 0 silent runaways, 0 lap mismatches** | 0 | **PASS** — the strongest track result recorded in eight rounds |
| **Fuzz** | round-7 suite re-run + new attacks on `_publish_completion`/`_chain_owed` | **Full** — every service check on both spellings | R8-04 (→Medium), R8-07, R8-08, R8-14, R8-01(b) corroboration | **PASS with residue**, no Blocker of its own |
| **Observability** | prior 2 scripts re-run unmodified; + `rerun_prior_async.py` (the one `def`-only prior attack, re-done on the coroutine lane) | **Targeted** — the previously blind attack converted; 6 new attacks (P–T) on round-7 machinery | R8-12, R8-13, R8-15 | **PASS**, nothing above Medium; **time-bounded**, the full requested matrix was not run and is stated in-track |
| **Persistence & crash consistency** | all three carried defects **FIXED**; core sound at scale | **Full** — `out/<script>.DEF.txt` records a parallel plain-`def` lane for every script | R8-05 (High), R8-06 (→Low), R8-08, R8-11 | **PASS on the core; the residue is all on the blob-integrity boundary** |
| **Security** | D6-security-1 **FIXED by #185**; D6-security-2 unchanged (informational, now probed on **both** kinds); #157 holds 199/199; chain-budget-under-external-load holds and is *strengthened* by #180; hook-snapshot never torn, 300 runs, 0 torn | **Full on the re-run**; the livelock config fuzz at n=120 gives `sync 120/120, async 120/120, DEFECT: 0` — against `58/120 async RUNAWAY` at `221ce7c` | R8-05 (forged `DoneEvent`/`AfterEvent`) | **PASS on everything mechanical; the one High is a trust-boundary design gap** |
| **Semantics** | whole prior suite re-run twice — unmodified, then under `asyncify.py`, which converts every plain-`def` service to a coroutine | **Full by construction** (that is what `asyncify.py` is for) | R8-01(b) (`d8_s1_priority_shed.py`), R8-11 | **PASS, with the Blocker's second half found here** |
| **Soak** | prior scripts byte-identical re-run + an `async def` mirror of the one `def`-only prior attack (#173 pool/stop churn) | **Targeted**; the ≥500-config livelock fuzz is cited from the determinism track rather than duplicated | 0 new | **PASS**; the 12-minute/200-machine full soak was **not** re-run standalone (time budget, stated in-track) |

**Reductions taken against the 20-minute bound, stated rather than applied silently:** the security track's livelock fuzz ran at n=120 rather than ≥500 (the ≥500 version exists in the determinism track and is clean); the 12-minute soak and the hash-seed sweep were not run; the benchmark series (`bench_a/c/e/h/j`) was not run this pass. None of these gaps sits on the Blocker's evidence path.

---

## 4. Contract machines (B1–B20) on the library, both service spellings

**All 20 build from the corrected catalogue JSON with zero `InvalidConfigError` and zero `ImplementationMissingError`, on both spellings, and drive their invariants end to end.** Snapshot/restore at quiescence between every macrostep is clean on every group — zero spurious `SnapshotMidStepError`, zero state/context diffs against the uninterrupted run, identical traces.

| Group | `async def` lane | plain `def` lane | Snapshot/restore | New **library** defects | Verdict |
|---|---|---|---|---|---|
| **B1–B5** (order core) | **132/132 PASS** (B1 34, B2 23, B3 21, B4+B5 34, persistence 15, build 5) | **132/132 PASS** (+10 build) | clean at every macrostep, trace-equal, sync parity | 0 new; **round 7's R7-01 is gone on every shape these contracts exercise** | **PASS both lanes.** Exposed to R8-01 via any gateway `priority=True` |
| **B6–B10** | **52 run / 52 PASS** | **52 run / 49 PASS, 3 FAIL** — all three one root cause (**LD-01** → the R8-02 residual: a `def` service is invoked even when the arming step was rolled back and even when an `always` guard left the invoking state) | all crashpoints MATCH (state *and* context), 0 spurious refusals; sync parity 15/15 identical configuration, action trace *and* service-call trace | 1 (LD-01 → R8-02 residual, High) | **PASS on the async lane; the `def` lane is the one that fails** — inverted from round 7 |
| **B11–B15** | happy paths 5/5; all catalogue invariants; snapshot/restore 5/5; async↔sync parity 5/5 | 5/5 both lanes on every scenario | 5/5 **both lanes** | LIB-R6-01 now **bounded** (~130 laps / 0.19 s, was 131 k / 20 s) but **silent**; CV-6DB-01 (`def` service never cancelled on state exit) → R8-02 residual | **PASS**; the round-6 rollback-storm class is closed |
| **B16–B20** (control) | **LIBRARY-GO on all five.** CV-221-01 closed: `maxIterations` 2/5/100 → **4/7/102** service calls, `max+2` exactly | **identical, cell for cell** to the async lane | 20/20 snapshot cells clean, zero mid-step refusals, identical traces | **0 new** | **ALL FIVE LIBRARY-GO.** Blocked only by **ours**: C-04 (B16, Blocker), C-07b (B18, Blocker), C-06 (B19, High), C-05 (B16, Low), W-03 (B17, wrapper) |

**The decisive contract-level observations this round:**

1. **B18 is no longer excluded on library grounds.** The kill-switch livelock that produced 3 547 `flatten_all_positions` calls in 3.0 s at `221ce7c`, still accelerating, now **plateaus at 1 002 calls** with `last_error = RunawayChainError` and a flat trail from t=0.5 s to t=4.1 s on both lanes. `maxIterations` is live again and **lane-independent**. The service-kind asymmetry that was the entire content of CV-221-01 is gone.
2. **External priority sends into B18 are never charged** — 50 concurrent `send(priority=True)` into an open macrostep: 0 dropped, 0 `chain_budget` refusals, both lanes. #180's claimed half holds exactly as claimed. R8-01's shed half is a *different* trigger (an already-tripped chain), which is precisely why the shipped tests miss it.
3. **What blocks B16 and B18 is ours, on any runtime.** C-04: only `REVOKE` clears elevation, so `LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE` leave it standing and elevation can be acquired *after* revocation. C-07b: `onUnhandled: "error"` turns two ordinary operator mistakes into a dead kill switch. Neither is a library defect, and neither gets better by waiting for upstream.

### Our-contract and wrapper items (the library is correct in every row)

| ID | Sev | Machine | Issue |
|---|---|---|---|
| **C-04** | **Blocker (ours)** | B16 | Elevation survives `LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE`; can be re-acquired after revocation |
| **C-07b** | **Blocker (ours)** | B18 | `onUnhandled: "error"` + a guard-denied `RELEASE` bricks the kill switch |
| **C-06** | High (ours) | B19 | `stale_lockout` only listens for `RECONNECTED` |
| **CD-01** | High (ours) | B8 | The kill switch is deferrable as catalogued |
| **C-07** | High (ours) | B16–B20 | The explicit `halted` states CV-C31 promised are still unwritten |
| **C-05** | Low (ours) | B16 | `STEP_UP_OK` while already elevated writes no audit |
| **W-01** | wrapper | all | Never write a non-coroutine service — **upgraded from style to hard prerequisite** by the R8-02 residual |
| **W-02** | wrapper | all | A chain-budget trip never reaches the originating caller's receipt (R8-12) |
| **W-03** | wrapper | B17 | Authorisation/risk events must be non-deferrable |

---

## 5. Surviving library defects, by final severity

Refutation moved **three of six** Blocker/High candidates, all downward, each with a recorded reason and each with evidence generated specifically to *support* the finding that then failed. Nothing was downgraded for convenience; nothing was moved up.

### Blocker (1)

| ID | Refutation | Why it stands |
|---|---|---|
| **R8-01** — the priority lane **charges by provenance and sheds by position**: a priority event issued from an action is never charged and livelocks unbounded and unobservably; an external priority event arriving at an already-tripped chain is silently destroyed as `chain_budget` | **CONFIRMED** | Both halves reproduced fresh at `6db65d8`, both service kinds, with controls that isolate causation. (a) 2/2 priority cells livelock past the watchdog, `trip_observable: false`, `start()` never returns, no drop hook, `last_error is None`; the plain-lane control on an identical machine is bounded at 27 laps with `RunawayChainError` and a `chain_budget` drop. (b) 8–9 of 2 000 external `EXT` events lost on the `def` lane with `send()` accepted; the `priority=False` control loses 0 on both kinds. Cause read in source: provenance is consulted at the charge site (`interpreter.py:2342-2389`, keyed on `engine_completion`) and not at the drop site (`:1598`, `= self._raise_depth > limit`), over a single FIFO `_priority_queue` that carries external sends and engine completions together; `engine_completion` is `False` for every `send(priority=True)` whatever the issuer. All four refutation axes fail (documentation promises the opposite at `docs/api/index.md:1788`; the identical plain-lane construct is supported and charged at `:898-908` via `_issued_from_own_action()`; XState v5 has neither a priority lane nor a chain budget; `tests/test_round7_findings.py:413-520` covers only externally issued priority sends into an untripped chain). |

### High (3)

| ID | Refutation | Note |
|---|---|---|
| **R8-02** — a plain `def` service is **uncancellable** (a mid-service `CANCEL` loses to `done.invoke` on the priority lane, landing `cursor=4242` and `m.done` instead of `m.cancelled`) and a `def` invoke is **not unwound by `actionErrorPolicy: "rollback"` nor by an `always` roll-forward**, because the executor handoff happens at entry, before the `always` chain and the rollback epilogue — while the `async def` task's arming *is* unwound | **DOWNGRADE Blocker→High** | The Blocker-level claim was **refuted**: the service does *not* run inline on the loop thread (#149 moved it to `loop.run_in_executor`, `interpreter.py:2811-2836`); the stall is `:1571-1577` awaiting `_await_inline_services()` and starves only that machine's inbox, other interpreters keep running — and that is documented at `docs/_guide/production-characteristics.md:93` (#174) including the remedy. What survives is spelling-dependent cancellation and rollback semantics, contained mechanically by CV-C32. Not API misuse (plain callables are a first-class `MachineLogic` spelling accepted silently under `strict=True`); not a duplicate of #116/#149/#173/#174. |
| **R8-03** — `start(children_timeout=)` is a **no-op against a plain-`def` child entry action** and **suppresses its own WARNING**; the bound is aggregate, not per child | **CONFIRMED** | 1 child → 3.00 s; 5 → 15.0 s; 50×1 s → 50.04 s; and 20×100 ms → 2.02 s at *every* bound (0.05 / 0.2 / 1.0 / `None`) with no WARNING in any case. `async def` rows bound and warn correctly. Cause: `interpreter.py:601` → `_await_actor_bringups:2753` `asyncio.wait(timeout=)` cannot pre-empt a non-yielding `def` entry action on the loop thread inside `child.start()` (`:2973`); bring-ups are serial, hence exact N×D scaling; the WARNING sits on the same timeout path and is suppressed with it. `docs/api/index.md:701` justifies the bound by "a child's bring-up runs its entry actions — user code (#181)" with no coroutine restriction. **The guarding test is vacuous:** `tests/test_round7_findings.py:557` parametrises over `KINDS` but gives the `def` arm `time.sleep(0.05)` against the async arm's `asyncio.sleep(3.0)`, so the `def` branch cannot fail. |
| **R8-05** — `DoneEvent` / `AfterEvent` carry **no provenance marker** and are exempt from `strict`/`onUnhandled`: a forged completion drives a real `onDone` | **CONFIRMED** | `VERDICT: FAIL`, 6 failures, both kinds. Both classes are in `__all__`, documented with field tables, and accepted by `send()`'s own type signature; `is_system_event` (`events.py:280`) returns `True` on bare `isinstance`, so the "provenance not name" invariant at `docs/api/index.md:1193` is false for exactly the two classes that assert engine authorship. No correct alternative exists (`system_event()` mints plain `Event` only). XState v5 binds `onDone` to actor lifecycle; this port matches on name + `event.src == inv.id` (`base_interpreter.py:4484`) with **no liveness check**, so a forgery fires `onDone` while the genuine service is still running. **Escalating vector that forecloses a documentation-note downgrade:** `restore_event` (`events.py:392`) reconstitutes a trusted `DoneEvent` from an attacker-authored snapshot record with no integrity check over `pending_events` — a wire vector, not only in-process misuse. On the `def` path the forgery is a *second* failure mode: accepted as trusted, then discarded unmatched via the executor lane, i.e. silent loss with neither transition nor `strict`/`onUnhandled` error (timing ruled out across 0.5/1.0/2.0 s settles against an 8 s service). |

### Medium (7)

| ID | Item |
|---|---|
| **R8-04** | `always` → invoking child → `onDone` re-entry: events are delivered but silently **do not apply** because `_settle_tripped=True` (`settle_iters=52`) with `last_error=None`, `drops={}`, `status=running`; plus a genuine parity gap against #179 — with an invoke in the cycle the runaway trips `RunawayChainError` on `def` (27/400 samples) but never on `async def` (0/400), from the chain-end reset at `interpreter.py:1725-1735`. **DOWNGRADE High→Medium**: the trigger is a chart the library documents as invalid (`docs/api/index.md:1788`) and detects on 3 of 4 engine × kind combos; correct usage (guarded `always`, the `faq.md:278` decision-state form) gives 300/300 on **both** kinds, as does a legitimate invoke→`onDone`→re-enter cycle without the `always`; and the "permanent starvation" claim is refuted (12 s settle: `on_event_received` 300/300, both queues drain to 0, machine returns to stable `m.a`). |
| **R8-07** | `await send(EV, wait=True)` can resolve at an instant when `current_state_ids == []`, success-shaped |
| **R8-08** | #186's `configuration`/`state_ids` agreement rule is **one-sided**: emptying either field short-circuits the check, so an emptied `state_ids` lets a forged `configuration` relocate the machine |
| **R8-09** | `get_persisted_snapshot()` from `on_interpreter_start` returns a torn blob (`status:"running"`, empty configuration), 600/600, both engines |
| **R8-10** | `_chain_owed` leaks permanently on a `BaseException` service exit and is settled by a bare counter, not matched to the debt. Regression from #179 |
| **R8-11** | #179's service-kind parity claim is false for `invoke` ping-pong and rollback+`onDone`; sync and async cut the same chart at different lap counts |
| **R8-12** | A chain-budget trip never reaches the originating caller's receipt or the `on_error` hook (DESIGN-CONSTRAINT → NEEDS-WRAPPER) |

### Low (4)

| ID | Item |
|---|---|
| **R8-06** | #185's drift check is bypassable by a `version: 0` downgrade. **DOWNGRADE High→Low**: mechanism reproduces on both engines and is in fact *stronger* than claimed (all three downgrade shapes restore a mismatched machine while the intact control is correctly refused, `persistence.py:320-329`), but the security framing is refuted — `machine.structure_hash` is a public, unkeyed, deterministic SHA-256 prefix of the machine definition (`persistence.py:120-126`), a **checksum, not a MAC**. Under the claim's own threat model an attacker who can edit the blob can simply set `machine_hash` to the *target* machine's hash and leave `version: 2` intact — accepted, no downgrade needed — so the downgrade path confers zero additional capability. A narrow non-adversarial residue survives (a transport that drops a null `machine_hash` may also drop `version`), but it cannot be fixed in-band: genuine 0.7.x snapshots carry neither field and must still restore, so unchecked-v0 is a deliberate back-compat contract. Proper fix is an API addition (`expected_machine_hash=` / `minimum_version=1`) plus a docstring correction. |
| **R8-13** | Call-site `QueueOverflowError` refusals fire no `on_event_dropped`; hook coverage of the shed rate collapsed to 0.3 % |
| **R8-14** | `SnapshotMidStepError` from an invoked child's entry action reports `child=False` |
| **R8-15** | The validator accepts unknown top-level config keys silently; `spawnBlockingTimeout` is parsed and dropped |

### Eight-round trend

| Round | Commit | Blocker | High | Medium | Low |
|---|---|---|---|---|---|
| 5 | `3ed3099` | 4 | 8 | 8 | 1 |
| 6 | `cec108b` | 2 | 2 | 7 | 9 |
| 7 | `221ce7c` | 2 | 4 | 6 | 8 |
| **8** | **`6db65d8`** | **1** | **3** | **7** | **4** |

---

## 6. GATE DECISION (per `20-adoption-gate.md` §7)

Applied in order, first match wins, with honest counts:

| Row | Condition | Our count | Matches? |
|---|---|---|---|
| 1 | Any `ERROR` row in the gate output | none — `FAIL=38 / PASS=89`, every FAIL traced to a known finding, an allow-listed baseline, or the two stale `machine_hash` fixtures (ours, H-3) | no |
| 2 | Suite fails, or coverage < 86 % | 3 457 passed / 2 subtest failures of a single load-sensitive flake (3/3 standalone passes) / 13 skipped; **92.70 %** | no |
| 3 | Snapshot format changed while LC-21 open | LC-21 closed; the format is versioned and unchanged this round (#185/#186 tighten *validation*, not layout) | no |
| 4 | **Any filed Blocker repro still exits 1** | **R8-01 reproduces unmodified, fresh, at `6db65d8`, both halves, both service kinds** | **YES — row 4 wins** |

**The conditional the brief specifies is not met.** The rule is: *if the Blocker row is empty AND open-High ≤ 5 with mechanical mitigations → **ADOPT WITH CONSTRAINTS***. Open-High is **3** (R8-02, R8-03, R8-05) — comfortably inside the ≤ 5 bar, and each has a mechanical mitigation available (CV-C32 lint for R8-02; CV-C44 explicit per-child bring-up bound for R8-03; CV-C45 completion-event provenance assertion at the restore boundary for R8-05). **But the Blocker row is not empty.** Row 4 precedes row 6, and the governing rule in `issues/00-META-candleviewer-adoption-readiness.md` §3 — "a defect is closed when its repro script exits 0, never by a changelog entry" — admits no discretion here.

**Decision: DEFER on the order path; GO on the non-order paths under constraints.**

```
Gate run 2026-09-21 - xstate-statemachine main @ 6db65d8 (unreleased 0.8.1)
DECISION: DEFER (order path)  ·  GO for non-order paths under constraints
          -- decision-table row 4: the Blocker row is non-empty (R8-01)
          -- row 6 (ADOPT WITH CONSTRAINTS) is otherwise SATISFIED:
             open-High = 3 (bar <=5), each with a mechanical mitigation

  16 issues      : 15 fixed in code (10 clean, 5 narrower than claimed)
                   · 1 documentation-only (#174) · 0 not-fixed
  regressions    : 0 true PASS->FAIL in the gate (2 deltas are OUR stale
                   machine_hash fixtures, superseded by #185)
                   1 introduced by this round's fix work and invisible to it:
                   R8-01 (Blocker); plus R8-10/R8-11 (Medium) from #179
  new defects    : 1 Blocker · 3 High · 7 Medium · 4 Low (post-refutation)
                   pre-refutation was 2 Blocker · 4 High · 6 Medium · 3 Low;
                   refutation moved 3 of 6 Blocker/High DOWN, 0 up
  gate script    : verify 29/34 · verifyM 10/15 · verifyM2 3/3 · verifyM3 23/27
                   · verifyM4 10/11 · repro 13/34 (informational) · probe 1/3
  suite/coverage : 3457 passed / 2 flake subtests / 13 skipped (878.9s)
                   · 92.70% (floor 90%)
  benchmarks     : NOT RUN this pass (time budget) - stated gap, carried
  contracts      : 20/20 build clean on BOTH service spellings.
                   B1-B5 132/132 both lanes; B6-B10 async 52/52, def 49/52
                   (one root cause, LD-01 -> R8-02); B11-B15 all invariants
                   both lanes; B16-B20 ALL FIVE LIBRARY-GO, CV-221-01 closed
                   at identical lap counts on both lanes (maxIterations
                   2/5/100 -> 4/7/102 service calls, max+2 exactly)
  blockers open  : R8-01 (library)   |   C-04, C-07b (OURS, any runtime)
  high open      : R8-02, R8-03, R8-05
  operative block: UPSTREAM - ONE line. interpreter.py:1598 sheds by queue
                   position; interpreter.py:2342-2389 charges by provenance.
                   Teach the drop site the rule the charge site already knows.
  constraints    : CV-C01..CV-C45 (see s.7); CV-C42 widened, CV-C43/44/45 new
  decided by     : adoption audit, round 8
```

**What would have given row 6.** Close R8-01 with a test parametrised over *issuer* (external vs action-issued) as well as service kind, and the Blocker row clears. Open-High is then 3, inside the bar, each mechanically mitigated and each with a contract test in `tests/xstate_contract/` — **row 6, ADOPT WITH CONSTRAINTS, on the order path.** This is the closest eight rounds have come: the gap is one function, in one file, of the same shape as the fix that created it.

**Why not "adopt with wrappers" anyway.** R8-02, R8-03 and R8-05 are all wrappable, and the mitigations are listed in §7. R8-01 is not, and this round tested that claim rather than asserting it. We can forbid `priority=True` in our own code — but the library itself routes engine completions onto that same FIFO, so an external priority event our gateway never sent can still be shed; and the self-send half produces a livelock that is unobservable *from inside the process*, because the starved thing is the loop thread that any in-process watchdog would run on. `status` stays `"running"`, `last_error` stays `None`, no drop hook fires. The only supervisor that can see it is out-of-process and keyed on **progress counters** — which we already mandate, and which is a detector, not a mitigation: it tells you the order path is wedged, it does not stop the order path from wedging.

**Pin policy (recorded here, and identically in ADR-0016 Amendment 8 and `20-adoption-gate.md`):**

> **`xstate-statemachine == 0.8.1` once tagged, and only if the tag is cut after R8-01 lands. Until then: git commit `6db65d8` plus its source sha256, evaluation only — endorsement withheld. Key the pin on the commit, never on the version string.** A **vendored copy per MUST-08** is carried for the non-order paths that go live now, so a retag, a force-push or a deleted branch cannot move what production runs.

---

## 7. Constraints

### Retired (3)

| Constraint | Why it retires |
|---|---|
| **CV-C38** (no invoke cycle in any order- or control-path machine without a bounded attempt counter in context) | **RETIRES as a machine-shape prohibition.** #179 closed R7-01 at the root: completions of both spellings now route through `_publish_completion` → the charged priority lane, and the engine bounds the cycle itself. Measured on the real B18: `maxIterations` 2/5/100 → 4/7/102 service calls, `max+2` exactly, **identical cell-for-cell on `def` and `async def`**; the kill-switch storm plateaus at 1 002 with `last_error = RunawayChainError`. **The lint (CV-LINT-XS16) is retained as defence in depth, downgraded from error to warning** — an unguarded invoke cycle is still a design smell and is still the trigger R8-04 needs. |
| **CV-C31′** (no `"rollback"` with a raisable entry action on an `invoke`-carrying state) | **RETIRES on the async lane and is re-scoped, not dropped.** The measurement that gave it its force — 3 547 `flatten_all_positions` calls from one `ENGAGE` — is gone; the same cell is bounded and observable now. **It is re-issued as CV-C31″ for plain-`def` services only**, on the entirely different ground that R8-02's residual shows a `def` invoke is not unwound by `rollback` at all. Since CV-C32 already bans `def` services on the async engine, CV-C31″ is redundant in practice and exists to make the lint's reason correct. |
| **The `maxIterations` "inert, do not rely on it" annotation** (Amendments 6 and 7) | **RETIRES.** `maxIterations` is live again and lane-independent, verified on the real contract machines and by a 500-config × 2 spellings × 2 engines fuzz with 0 silent runaways. It goes back to being a real bound. **The one place it is still inert is R8-01's self-issued priority send** — which is why that annotation is replaced by a narrower one in the config block rather than deleted. |

### Standing (unchanged)

**CV-C01…CV-C22** as amended · **CV-C23** (quiescence-only snapshots via the factory wrapper) · **CV-C25** (no external `send()` from inside an action; gateway queue only) · **CV-C27′** (`state_ids ⊆ configuration` on restore — **strengthened in effect by R8-08**: the library's own check is one-sided, so ours is now the only two-sided one) · **CV-C28** (no `LoggingInspector` in production) · **CV-C32** (async engine → every service `async def`; sync engine → every service plain `def`) — **stands, and for the first time it is comfortable**: the coroutine lane is now the healthy one on every track, and CV-C32 is precisely what keeps us off R8-02's uncancellable, un-rolled-back `def` path · **CV-C33** (`send_threadsafe` only via our gateway) · **CV-C35** (no `always` into an invoked child, no `always` to an ancestor of its own source) — **load-bearing for R8-04**, whose entire trigger is the shape this forbids · **CV-C36** (every `send_threadsafe` future is read; refusals counted and paged) — retained on R8-13's ground, the call-site half still fires no hook · **CV-C39** (`await start()` always bounded) · **CV-C40** (no snapshot before the post-start settle observation) — **retained on R8-09's ground**, since the `on_interpreter_start` hook still yields a torn blob even though #182 closed the descent window · **CV-C41** (root-only snapshots; child state via explicit `sendTo`).

### Widened (1)

| ID | Change |
|---|---|
| **CV-C42** | Was: "`priority=True` is forbidden outside wrapper code, and the gateway never sets it on an externally originated event." **Now also:** *the gateway never sets `priority=True` at all, on any event, from any origin, and no action body may call `send(..., priority=True)`.* R8-01 makes both halves of the lane unsafe — self-issued priority events livelock, external ones are shed at an already-tripped chain. Enforced by a lint on `priority=`/`send_priority(` across the whole codebase, plus an alert on any non-zero `chain_budget` drop reason. **Containment only, not a fix:** the library routes its own completions onto that queue regardless of what we do. |

### New (3)

| ID | Rule | Enforced by | Covers |
|---|---|---|---|
| **CV-C43** | **The order-path liveness signal is an out-of-process progress counter with a wall-clock deadline.** No in-process watchdog (`asyncio.wait_for`, a loop-resident supervisor task, `status`, `last_error`) may be the sole detector for an order-path machine, because the failure mode being detected starves the loop thread those detectors run on. | Supervisor process + a contract test that starves a test loop and asserts the out-of-process detector fires while the in-process one does not | **R8-01 (Blocker)** — detection only |
| **CV-C44** | **Child bring-up is bounded by us, per child, not by `start(children_timeout=)`.** Every invoked child's entry action is a coroutine that yields at least once (CV-C32 already requires this for services; this extends it to entry actions on invoke-bearing states), and the factory bounds each child's bring-up itself rather than relying on the library's aggregate bound. | Lint: no non-`async def` entry action on a state carrying `invoke`; factory per-child bound + a contract test at N=20 children asserting total time ≈ the bound, not N × the bound | **R8-03 (High)** |
| **CV-C45** | **Completion events are never accepted from a wire.** The restore path strips `pending_events` of every `DoneEvent` / `AfterEvent` before `from_snapshot()`, and the gateway rejects any externally submitted event whose type is an instance of either class. In-flight completions are re-derived from the restored configuration, never replayed from the blob. | Gateway type check + restore-path filter + a contract test that plants a forged `DoneEvent` in a blob and asserts it is stripped | **R8-05 (High)** |

**Also promoted to constraint clauses, not new IDs.** Under CV-C23: the restore path refuses a payload whose declared `version` is absent or `0` **when we wrote it** (our envelope always sets `version ≥ 1` and a `machine_hash`), closing R8-06's residue on our side without depending on the library — and asserts agreement in **both** directions between `configuration` and `state_ids`, since #186's rule is one-sided (R8-08). Under CV-C06: a `send(wait=True)` receipt is never read for configuration; read the configuration separately at quiescence (R8-07). Under CV-C25: a chain-budget trip is invisible to the caller, so the gateway correlates its own send with the `on_event_dropped` hook rather than with the receipt (R8-12).

### FINAL mandatory configuration block

```jsonc
{
  // --- error handling -------------------------------------------------
  "actionErrorPolicy": "rollback",   // DEFAULT, all non-order machines.
                                     // CV-C31' RETIRES on the async lane: the
                                     // rollback + invoke.onDone storm is bounded
                                     // and observable at 6db65d8 (B18: plateau at
                                     // 1002 calls, last_error=RunawayChainError,
                                     // identical on both spellings).
                                     // CV-C31" replaces it, plain-`def` services
                                     // only: a `def` invoke is NOT unwound by
                                     // rollback at all (R8-02). Moot under CV-C32.
  "actionErrorPolicy": "fail",       // ORDER-PATH states with invoke + raisable entry.
                                     // #145 still verified: halts with status="stopped",
                                     // configuration cleared, TransitionFailedError
                                     // retained, halted blob refused by from_snapshot.
                                     // Pair with an explicit `halted` state entered from
                                     // on_transition_failed - C-07: these states are
                                     // STILL MISSING on B16-B20 (E50-T16).

  "guardErrorPolicy": "raise",       // #152 + #170: cancels only the FAILING candidate;
                                     // the unguarded fallback is still taken; the
                                     // (denied, error, deferred, changed) matrix is
                                     // INJECTIVE. W-04a stays retired. W-04b stands:
                                     // `defer` outranks guard_denied, so denied events
                                     // must be drained from the buffer.

  "onUnhandled": "defer",            // order path. No "*" scaffolding (CV-C34, done).
                                     // Authorisation/risk events are non-deferrable (W-03).
  "onUnhandled": "error",            // control machines ONLY, and NOT on B18 - C-07b:
                                     // a guard-denied RELEASE is terminal, i.e. the kill
                                     // switch is bricked by a wrong press. OURS, Blocker.
                                     // #189 FIXED: the fatal kill is now visible on the
                                     // sender's Receipt.error on both engines.

  "strictTargets": true,             // #147: RootTargetError at build time, non-downgradable.
  "strict": true,                    // #190 FIXED: config-level strict is inherited and a
                                     // "*" handler no longer defeats strict/is_known_event.
                                     // R8-15 stands: a TYPO in any top-level key is still
                                     // accepted silently and downgrades to the default, so
                                     // the wrapper whitelists keys itself.
  "maxIterations": 500,              // LIVE AGAIN and lane-independent - the Amendment 6/7
                                     // "inert, do not rely on it" annotation RETIRES.
                                     // Verified: maxIterations 2/5/100 -> 4/7/102 service
                                     // calls (max+2), identical `def` vs `async def`;
                                     // 500-config x 2 spellings x 2 engines fuzz, 0 silent
                                     // runaways. ONE residual inertness: it does NOT bound
                                     // a priority event issued from an action (R8-01) -
                                     // which is why CV-C42 bans priority=True outright.
  "spawnBlockingTimeout": 5000       // R8-15/OBS-01: validated then dropped - no attribute
                                     // on MachineNode, so a conformance lint cannot assert
                                     // it post-build. Whitelist top-level keys in the wrapper.
}
```

```python
# Runtime construction - mandatory (round 8)
MachineLogic(strict=True)             # W-01: create_machine is NOT a conformance gate; the
                                      # wrapper cross-validates the logic table against the JSON.
Interpreter(..., max_queue_size=64, overflow_policy=OverflowPolicy.RAISE,
            service_pool_size=<explicit>)   # default is 4. DC-1: SyncInterpreter accepts
                                      # NEITHER max_queue_size NOR overflow_policy, so sync
                                      # parity is not a backpressure comparison.

# Services: async def ONLY on the async engine (CV-C32). Blocking work via asyncio.to_thread.
#   Round 8 inverts the reason: the coroutine lane is now the HEALTHY one. A plain `def`
#   service is uncancellable and is not unwound by rollback or by an `always` (R8-02), and
#   it blocks its own machine's `after` timers (#174, documented).
# Entry actions on invoke-bearing states: async def, yielding at least once (CV-C44, R8-03).
# start():  ALWAYS asyncio.wait_for(start(), CV_START_TIMEOUT) - never bare (CV-C39).
#   Bound each child's bring-up ourselves; start(children_timeout=) is a no-op against a
#   non-yielding `def` entry action and suppresses its own WARNING (CV-C44, R8-03).
# Snapshot: factory wrapper only; at quiescence (CV-C23); never before the post-start settle
#   observation (CV-C40 - #182 closed the descent, R8-09 leaves the hook torn); ROOT ONLY,
#   child state via explicit sendTo (CV-C41).
# Restore:  our envelope always writes version>=1 + machine_hash, and the restore path
#   refuses version 0/absent on OUR blobs (R8-06 residue, closed on our side);
#   assert configuration and state_ids agree in BOTH directions (CV-C27', R8-08);
#   STRIP every DoneEvent/AfterEvent from pending_events before from_snapshot (CV-C45, R8-05).
# Sends:    gateway only; priority=True forbidden EVERYWHERE, any origin (CV-C42, R8-01);
#   every send_threadsafe future is read and refusals counted (CV-C36, R8-13);
#   correlate drops via on_event_dropped, never via the receipt (R8-12).
# Health:   OUT-OF-PROCESS progress counters ONLY (CV-C43). `status`, `last_error` and any
#   in-process watchdog are not liveness signals for the order path - R8-01 starves the very
#   loop thread they run on.
```

---

## 8. Release-readiness note for the team (before tagging 0.8.1)

Eight rounds in, this is the best round yet, and it is worth saying plainly before the criticism. **The single highest-value change we asked for in round 7 landed**: `tests/test_round7_findings.py` parametrises over `KINDS = ("def", "async def")` and cross-checks both engines, 37 tests. The effect is immediate and measurable — the async livelock fuzz went from **58/120 RUNAWAY at `221ce7c` to 0/120 here**, the determinism track's 500-config × 2 spellings × 2 engines sweep found **0 hangs, 0 silent runaways, 0 lap mismatches**, `maxIterations` is a real bound again on both lanes at identical lap counts, and the B18 kill-switch storm that was the sharpest measurement in round 7 is now a flat plateau with a named error. **Both round-7 Blockers are closed, no issue is "not fixed", and the Blocker count is 1 for the first time since round 3.** Coverage 92.70 %, 3 457 tests.

**Three things stand between `6db65d8` and a tag we would pin.**

1. **Do not tag until R8-01 lands.** A 0.8.1 cut here releases one silent Blocker with two faces on the same queue: a priority event issued from an action is never charged and livelocks the loop thread with `status="running"`, `last_error=None` and no drop hook; an external priority event arriving at an already-tripped chain is silently destroyed with `send()` reporting success. It is **one function's worth of work** — `interpreter.py:1598` needs the provenance test that `:2342-2389` already performs — and it is the regression surface of this release's own #180.
2. **The version is still unbumped.** `__version__` reports `0.8.0` on a commit whose CHANGELOG describes 0.8.1. **Eight** verification rounds have now keyed on commits because of this. Bump it in the same commit that tags, or the "key on the commit, never the version" escape hatch survives into a *released* artefact — far worse than needing it pre-release.
3. **Two shipped tests pass while their defect is live, and one of them is vacuous by construction.** `tests/test_round7_findings.py:557` parametrises the `children_timeout` test over `KINDS` but gives the `def` arm `time.sleep(0.05)` against the async arm's `asyncio.sleep(3.0)` — the `def` branch **cannot fail**, and R8-03 is exactly the defect it is named for; `test_bringup_timeout_is_observable` is async-only. Similarly `tests/test_round7_findings.py:413-520` exercises only *externally issued* priority sends into an *untripped* chain, which is why R8-01 got through. **Round 7's lesson generalises one more time: parametrise over the axis the defect lives on.** Rounds 6, 7 and 8 have each been "fixed on the axis the test was written against" — engine, then service kind, now **issuer provenance and chain state**. The matrix that closes all three permanently is (engine × service kind × issuer × chain state), and the `def` arm of every cell must be given work that can actually exceed the bound.

**Also worth landing before the tag, in rough value order:** R8-03 (bound each child's bring-up, and move the WARNING off the timeout path so it is not suppressed with it); R8-05 (an engine-only construction path for `DoneEvent`/`AfterEvent`, plus a liveness check on `event.src == inv.id` at `base_interpreter.py:4484`, plus stripping completion events out of `restore_event`); R8-02's residual (unwind a `def` invoke's executor handoff on rollback and on an `always` roll-forward, and make it cancellable on state exit); R8-08 (make #186's agreement check two-sided — it is one `or`); R8-09 (`on_interpreter_start` should sit inside the same in-flight window #182 established); R8-10 (`_chain_owed` settled by matched debt, and released in a `finally` that catches `BaseException`); R8-11 (either fix the parity or correct the CHANGELOG claim); R8-06 (an `expected_machine_hash=` / `minimum_version=1` API addition, plus a docstring correction noting that `structure_hash` is a **checksum, not an auth tag**, and that v0 is unchecked by design); R8-07, R8-12, R8-13, R8-14, R8-15 — all small, all ergonomics or observability, all independently reproduced.

**Two measurements we owe and did not make this pass**, stated rather than glossed: the full benchmark series (`bench_a/c/e/h/j`) was not run — the coverage run alone took ~15 of the 20-minute budget — so `bench_h`'s RSS/open-order move of **3.10 → 5.18 KB**, flagged unattributed in round 7, is **still unbisected two rounds later**; and the `PYTHONHASHSEED` sweep was not run. Neither sits on the Blocker's evidence path, but the RSS figure gates BENCH-4 and deserves a bisected re-run rather than a third shrug.

---

## 9. What would change the verdict

**Upward — what turns DEFER into ADOPT WITH CONSTRAINTS on the order path.** One thing: **close R8-01 with a test parametrised over issuer provenance and chain state, not just service kind.** The Blocker row then clears, open-High is **3** (R8-02, R8-03, R8-05) against a bar of 5, each with a mechanically enforced mitigation (CV-C32 lint, CV-C44, CV-C45) and a contract test in `tests/xstate_contract/`, and all Medium items are triaged. That is decision-table **row 6**. Nothing else needs to move. If R8-03 and R8-05 land alongside — both are small and both are in the same file family — the count is 1 High and the margin is comfortable.

**Re-verification recipe (~40 minutes):**

```
gate/run_gate.py                                   # now incl. the verify-main-6db65d8 set
issues/post-6db65d8/new/repro/R8-01_priority_self_send_livelock.py   # MUST terminate, bounded
issues/post-6db65d8/new/repro/R8-01_external_priority_shed.py        # MUST lose 0 of 2000
battle-6db65d8/semantics/repro/d8_s1_priority_shed.py                # both spellings
battle-6db65d8/contracts/r8/s1_livelock.py  s2_plateau.py  s5_prio.py
issues/verify-main-6db65d8/181_children_timeout.py --kind=def        # R8-03
battle-6db65d8/persistence/r10_doneevent_forgery.py + r10_forgery_snapshot.py   # R8-05
battle-6db65d8/determinism/g7_livelock_fuzz.py                       # 500 x 2 x 2, must stay 0
contracts: B1, B8, B18, B19 end-to-end on BOTH service kinds
bench_h (bisect the 3.10 -> 5.18 KB RSS/open-order move) ; bench_c_timers load_500
```

**Downward — what would make the verdict worse.**

1. **A 0.8.1 tag cut at `6db65d8` as it stands.** It releases R8-01 and removes the commit-keyed escape hatch in the same motion.
2. **Closing R8-03 on the strength of the shipped test.** `tests/test_round7_findings.py:557` passes while the defect is live, by construction. A test that cannot fail on the defect it names is worse than no test, because it closes the issue.
3. **Relaxing CV-C32.** Round 8 inverted which lane is dangerous but did not make either safe; if `def` services were ever permitted on the async engine, R8-02's uncancellable, un-rolled-back invoke would be live on the order path and the kill switch would be the first casualty.
4. **Treating `maxIterations` as universal again.** It is a real bound once more — except against a priority event issued from an action. Writing it into a design as an unconditional guarantee re-creates R8-01's blast radius the next time someone reaches for `priority=True`.
5. **Discovering that the two stale `machine_hash` fixtures hid a real behaviour change.** We attributed `154`/`158` to #185 and reproduced the attribution directly; if adding a `machine_hash` does not restore those assertions, the attribution is wrong and there is an unexamined regression underneath.

---

## 10. Next steps for CandleViewer

**The decision is DEFER on the order path, so the exit condition governs — but the non-order GO is real and widens this round.**

> **EXIT CONDITION (order path).** R8-01's two repros exit 0 at the commit under test — `R8-01_priority_self_send_livelock.py` terminates bounded with an observable trip on both service kinds, and `R8-01_external_priority_shed.py` loses 0 of 2 000 external events against an already-tripped chain — *and* the upstream fix ships with a test parametrised over issuer provenance × chain state × service kind. On that commit, re-run §9's recipe and `E50-X01`. Expected outcome on the evidence to hand: **ADOPT WITH CONSTRAINTS (CV-C01…CV-C45), order path included.**

1. **Post round 8 upstream.** Drafts staged in `issues/post-6db65d8/` (**not posted**): 16 per-issue comments (10 confirm-closed, 5 confirm-with-residual naming the residual issue, 1 documentation-only acknowledgement for #174), new-issue files with standalone repros for every CONFIRMED Medium-and-above library defect (R8-01, R8-02, R8-03, R8-05, R8-07, R8-08, R8-09, R8-10, R8-11), a refreshed `meta-26.md` carrying this scorecard and the release note, and `manifest.json`. **Lead with the test-axis lesson**, as in rounds 6 and 7: the axis moved again, from service kind to issuer provenance, and the matrix that ends the pattern is (engine × service kind × issuer × chain state).
2. **Non-order machines: proceed, and widen the set.** B10–B17, **B19 and B20** under CV-C01…CV-C45. **B18 is no longer excluded on library grounds** — CV-221-01 is closed and the kill-switch storm is bounded and observable — so B18 moves out of the library-blocked column and into the *ours-blocked* column, behind C-07b. That is the headline movement of this round for our own plan.
3. **Order path stays on the in-house shim.** `E50-X01` re-runs on the commit that closes R8-01.
4. **Fix our own catalogue — this is now the critical path, not upstream.** Two of our defects are Blockers on any runtime and both sit on control machines the library has cleared: **C-04** (B16 elevation survives `LOGOUT`/`REVOKE`) and **C-07b** (B18 kill switch bricked by a guard-denied `RELEASE`). Then C-06 (B19), CD-01 (B8), C-07 (the `halted` states CV-C31 promised and nobody wrote), C-05. Stated bluntly: **for B16 and B18, we are the blocker now.**
5. **E50 ticket movement.** Mark the round-7 chores verified; record the X01 verdict as **DEFER (order) / GO (non-order)**; **retire** `E50-T21` (CV-C38's invoke-cycle lint as an error — downgraded to a warning, the engine bounds it now); **re-scope** `E50-T23` to CV-C42's widened form (ban `priority=True` outright, any origin); **new** tickets for CV-C43 (out-of-process progress supervisor), CV-C44 (per-child bring-up bound + the async-entry-action lint), CV-C45 (completion-event stripping at the restore boundary), H-3 (the two stale `machine_hash` fixtures) and the `verify-main-6db65d8` gate set (H-4, landed by this pass).
6. **Shim retirement plan — phased by machine group, now with a real first phase.**
   - **Phase 1 — control plane, now.** B17, B20 move to the library immediately: LIBRARY-GO, no outstanding contract defect, no `invoke` cycle, no external priority producer. One sprint, shadow mode for the first week.
   - **Phase 2 — platform, now, behind our own fixes.** B10–B15 and B19 move as their contract defects close (C-06 for B19; none for B10–B15). These are the machines with services, so Phase 2 is also the first real test of CV-C32 + CV-C44 in production shape.
   - **Phase 3 — control plane, ours-blocked.** B16 and B18 move once C-04 and C-07b are fixed in the catalogue. The library is already ready for both.
   - **Phase 4 — order path, upstream-blocked.** B1–B9 move only after R8-01 closes, and then only through the dual-runtime conformance harness (`E50-T03`) run over all nine on **both** service kinds for one full sprint in shadow mode with zero divergences required. Cut over one machine at a time, starting with B9 `rule_instance` (no money on it) and ending with B1 `order`.
   - **Deletion.** The shim is deleted only after B1 has run 30 days in production with no divergence. Budget two sprints *after* the upstream fix lands, not before.
7. **The contract suite becomes our standing gate.** `tests/xstate_contract/` runs in CI on every commit, under 60 s (`E50-T06`), and **every service-bearing case runs on both spellings** — the harness knob already exists (`CV_SVC_STYLE`, `cv6db.py`, `r8/h.py`) and this pass proved its value twice. `run_gate.py` runs as a scheduled job against each new upstream commit (`E50-T04`), now including the `verify-main-6db65d8` set. **Standing amendment 13 to `20-adoption-gate.md`:** a gate row that exercises a *send* must be parametrised over issuer provenance (external vs action-issued) and chain state (untripped vs tripped), exactly as amendment 12 requires for service kind.
8. **Pin policy.** `xstate-statemachine == 0.8.1` once tagged, **and only if the tag is cut after R8-01 lands**. Until then git commit `6db65d8` plus its source sha256, evaluation only, endorsement withheld, **with a vendored copy per MUST-08** for the non-order machines going live now. Key on the commit, never the version string.

---

## Evidence index

`48-r8-findings-register.md` (register of record) · `45-r8-regression.md` · `46-r8-suite-bench.md` · `47-r8-diff-review.md` · `49-r8-04-refutation.md` · `49-r8-05-refutation.md` · `issues/refute-r8/R8-03-verdict.md` · `battle-6db65d8/*.md` (8 tracks) · `battle-6db65d8/contracts/*.md` (4 groups) + `battle-6db65d8/contracts/r8/` (B16–B20) · `issues/verify-main-6db65d8/*` (16 scripts + result files) · `gate/result-main-6db65d8.json` · `issues/post-6db65d8/` (drafts, **not posted**). Runs 2026-09-21, Python 3.13.7, Windows 11 Pro 10.0.26200, `.venv-main`, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. Library source never modified; no `git` run in the adopting repository; GitHub read-only.
