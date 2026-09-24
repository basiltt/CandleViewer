# 59 — Round-10 FINAL readiness verdict: `xstate-statemachine` main @ `19cb1f1` (unreleased 0.8.1)

Date: 2026-09-22. Round 10. Prior decision (round 9, `f28719c`): **ADOPT WITH CONSTRAINTS**, decision-table **row 6**.

**Identify this build by commit, never by version string.** `__version__` still reports `0.8.0` on `19cb1f1` (merge of PR #211, commit `4dbf86e`) while `CHANGELOG.md [Unreleased]` targets 0.8.1. Every pin, CI assertion and gate baseline keys on the commit plus its source sha256.

Method: 8 issue verifications (#203–#210) re-run live (`issues/verify-main-19cb1f1/`); full regression sweep (`55-r10-regression.md`); suite + benchmarks (`56-r10-suite-bench.md`, plus `suite-19cb1f1.log` which **finished after that agent's bound** — see §2); diff review `f28719c..19cb1f1` (`57-r10-diff-review.md`); all 8 battle tracks re-run (`battle-19cb1f1/*.md`); all 20 contract machines driven end-to-end **on both service spellings**; triage → dedupe (`58-r10-findings-register.md`) → **independent adversarial refutation of every Blocker and High**, applied below.

**Financial-OMS standard applied throughout:** nothing counted without a standalone repro on a clean interpreter from neutral cwd `C:/Users/basil`, and **every service/action check run with both `def` and `async def`**.

---

## 0. The answer

### Are the reported issues genuinely closed?

**Yes — all eight. This is the first round in ten where every issue the release claims to have fixed verifies clean, on both engines and both service spellings, with no "fixed on one axis only" residual.**

All eight scripts under `issues/verify-main-19cb1f1/` pass on first run: #203 (`after` gated on `is_system_event`), #204 (`invoke` deferred past the eventless settle, SCXML §6.1 `statesToInvoke`), #205 (`minimum_version` + `expected_machine_hash` refuse untrusted payloads), #206 (delayed self-send charged as engine work), #207 (`RunawayChainError.stranded` + `on_invocation_stranded` + `pending_invocations()` live on all three lanes), #208 (0 empty-config-while-`ok` violations across 60 laps × 3 lanes), #209 (`rollback_ondone` lap shape agrees `sync == async_def == async_async` at all limits 1–25), #210 (real convergence poll, exact plateau, 5/5 green). Two footnotes, neither changing a verdict: #209's paired `nested_invoke` shape is **inert padding** in both the verify script and `tests/test_round9_findings.py` — it never exits state `a`, so it fires exactly 2 calls at every limit and never trips — and #207's reporter-side "failure" was under-waiting after an async `send()`, not a regression.

### Is the library fully battle-tested and ready?

**The best position in ten rounds, and the first with an empty Blocker row *and* an empty High row.** After independent refutation the round leaves **0 Blocker · 0 High · 5 Medium · 7 Low** live library defects, plus 1 refuted outright.

Refutation moved **all three** Blocker/High library candidates *down* and **none up**: **R10-01 Blocker → Low**, **R10-02 High → REFUTED outright**, **R10-03 High → Medium**. On the contract side, **R10-C1 and R10-C2 are refuted as library defects** (both are our chart, confirmed by corrected-usage probes that pass on both engines), **R10-C3 High → Medium** and **R10-C4 High → REFUTED (Low)**.

The single most consequential correction is **R10-01**. It was filed as a Blocker on the strength of seven forgery vectors against engine-event provenance. The vectors all reproduce exactly as filed — but they partition into two classes and **neither crosses a trust boundary**. Class A (import path `engine_after`, `type(held)(...)`, `pickle`, `deepcopy`, private `_EngineAfter`, `_replace`) presumes attacker-controlled Python in-process; a control run shows a plain registered action with no forgery at all writes context arbitrarily and a live `Interpreter` exposes `_enter_states` / `_exit_states` directly, so forging an `AfterEvent` is *strictly weaker than the premise*, and any per-interpreter nonce would be readable by the same reach. Class B (forged `"engine": true` record, `restore_event`) requires blob-write — and rather than accept the library's claim, we tested it: a hand-edited snapshot with **no event forgery at all** restores to `{'z.late'}` with context `{'n': 999}`. The flag adds zero capability over what the blob writer already holds. The boundary #195/#203 actually target — external name/shape confusion — **holds in every probe** (V1, B and G all refused under `strict:True` + `onUnhandled:"error"`). What survives is hardening-grade: unprefixed `engine_*` factories in a public module, `restore_event` trusting a plaintext boolean where the docs should mandate signing the whole snapshot, and `_replace` re-typing a genuine event.

**We also closed the measurement round 9 owed and could not make.** The full suite finished after the bench agent's bound: **3505 passed, 13 skipped, 0 failed, 566.57 s, coverage 92.78 %** (`suite-19cb1f1.log`). That is above both the library's own 90 % floor and our 86 % gate bar, and up from 92.70 % at `6db65d8`. Decision-table row 2 — which fires *before* the adoption rows and was round 9's single largest open risk — is now cleanly not-triggered on measured evidence rather than on inference.

### Are we good to proceed?

**Yes, and on a materially lighter regime than round 9.** The decision moves from **row 6** (Blockers clear, 1–5 High open with enforced mitigations) to **row 8** (all Blocker and High closed, all Medium triaged, BENCH-2/BENCH-6 still unmet) — **ADOPT WITH CONSTRAINTS, benchmark-derived constraints only**. §9 of the round-9 verdict named row 8 as "the honest ceiling for this library in our system." **We have reached it.** Two safety constraints retire outright as a consequence: **CV-C46** (order path never on `SyncInterpreter`) and **CV-C45's send-side clause**; **CV-C32** falls back from a safety rule to a performance/liveness preference (it is still mandatory, for `#193`/`R10-D2` reasons, but no longer carries a High).

The honest qualifier: the binding constraint on our order path is now **entirely our own catalogue**, and it has been for two rounds. **R10-C1 (B16) and R10-C2 (B18/C-07b) remain Blockers — against *us*.** Both were refuted as library defects this round by probes that show corrected charts pass on both engines and both spellings; the engine follows the chart in every cell. Ten rounds of library verification have converged on the right problem to have, and it is ours to fix.

### The sharper question: may Phase-3 order-path shim retirement begin?

**Yes. Both round-9 Highs that gated Phase 3 are closed, and the one measurement precondition Phase 3 named is now satisfied.**

- **R9-02 → #203 — CLOSED.** `base_interpreter.py:4624` now gates `after` selection on `isinstance(event, AfterEvent) and is_system_event(event)`, the same test the `Done`/`Error` branch already used. The discriminating control that made R9-02 a High — a public `AfterEvent` with the correct type string firing a 60 s timer instantly at the **default** `strict=False` — is dead: `contracts/repro/r9_after_provenance.py` refuses it at `send()` with a named `UnknownEventError` on both spellings, and `u2_after_forgery.py`'s controls B and G refuse under our hardened config. R10-01's surviving vectors do **not** revive it: every one is either in-process Python (weaker than the premise) or blob-write (which already suffices without any forgery), and R10-01 now sits at **Low**. The external-submission boundary CV-C45 was built to hold is held by the library itself.
- **R9-04 → #204 — CLOSED.** The roll-forward half landed, on **both engines and both service kinds**: `g9_d1_always.py` reports 0 service submissions in all 8 cells; the `LD-01` repro goes **3 leaked → 0 leaked** across all 6 lanes; B6–B10's `def` lane goes 51/52 → **52/52** and drives D1–D3 go 13/14 → **14/14**; `CV-F28-01` is withdrawn as fixed. The `167 rollback_reinvoke_spin` gate cell — recorded at `f28719c` as an expected FAIL because "#201 explicitly does not promise the sync re-arm" — now **PASSes 5/5 stably** on both `verifyM4` and `verifyM5`. That was the sync-engine lane whose leak was CV-C46's entire ground.

Phase 3's four acceptance conditions therefore stand as: **(iii) the ≥ 86 % coverage measurement — NOW MET (92.78 %)**; **(i) contract suite green on both spellings for five consecutive nightlies**, **(ii) the named constraint tests green under lint**, and **(iv) the two-week low-notional canary** — all three of which are **our** engineering work, with **no remaining library dependency**. Phase 3 may begin. It should not *complete* before (i), (ii) and (iv) are discharged, and **CV-C42, CV-C23's HMAC clause and the wrapper attempt counter still do not retire in this phase** — they answer R10-03/R10-04/R10-05/R10-D1, which are Medium and open.

One caveat stated rather than glossed: **Phase 2 (control plane, B16/B18) remains blocked on C-04 and C-07b — ours, now open five rounds.** Phase 3 is not blocked behind Phase 2 (different machine groups, different shims), but B18 appears in both the order-path and control-plane lists, so **B18's shim retires with Phase 2, not Phase 3**, regardless of Phase 3's progress.

---

## 1. The 8 issues

| # | Claim in `CHANGELOG [Unreleased]` | Verified disposition at `19cb1f1` | Residual |
|---|---|---|---|
| **#203** | `after` transitions match on provenance; only an engine-minted `AfterEvent` drives an `after` | **FIXED** — selection gated on `is_system_event` at `base_interpreter.py:4624`; both vectors + regressions pass on both engines. **Closes round-9 High R9-02.** | Migration cliff for 0.8.0-era persisted `after` records → **R10-05** (Medium) |
| **#204** | `invoke` arms after the eventless settle (SCXML §6.1 `statesToInvoke`); a state entered+exited in one macrostep never submits | **FIXED** — roll-forward *and* rollback, both engines, both kinds. `LD-01` 3 leaks → 0/6; B6–B10 `def` lane 52/52; drives 14/14. **Closes round-9 High R9-04.** | — |
| **#205** | `from_snapshot(minimum_version=, expected_machine_hash=)` lets a caller refuse a payload that selects its own checking level | **FIXED** — both refuse on both engines; docstring states the trust boundary as "fingerprint, not MAC/authentication" (semantically equivalent to the "checksum" wording asked for) | Restore still bypasses `strict` → **R10-05(a)** (Medium) |
| **#206** | A delayed self-`send` is a debt of the arming step, charged as engine work; external delayed sends stay external | **FIXED as specified** — trips within ±1 lap of the zero-delay cycle; external delayed sends correctly unshielded per #192 | **Undeclared behaviour break** for `raise(delay=)` periodic work → **R10-03** (Medium, downgraded from High) |
| **#207** | `RunawayChainError.stranded` + `on_invocation_stranded` hook + ERROR log + `pending_invocations()` | **FIXED** — all four confirmed live on `Interpreter` (`def`/`async`) and `SyncInterpreter`; exactly-once with a correct payload (R10-M3). Reporter's own repro "failed" only from under-waiting after an async `send()` | Trip still never reaches `on_error`/`interpreter.error`; `last_error` lane-asymmetric → **R10-13** (Low) |
| **#208** | Receipts resolved after the in-flight flag is down; refuse `ok` over an illegal configuration | **FIXED** — 0 empty-config-while-`ok` across 60 laps × 3 real lanes, plus a forced-illegal-configuration unit check proving the refusal path genuinely refuses. Also flipped `verify/LC-42 send_receipt` FAIL → PASS 5/5 | The illegal-config branch is unreachable on a live machine (`_repair_configuration` runs first) → **R10-11** (Low, doc) |
| **#209** | Lap parity across all three lanes at limits 1–25, pinned as a sweep | **FIXED on the discriminating shape** — `rollback_ondone` scales with `maxIterations` and agrees `sync == async_def == async_async` at all limits 1–25, odd and even. `g2_lap_parity.py` def-lane mismatches 13 → 0 | (a) the paired `nested_invoke` shape is **inert padding** — never exits state `a`, 2 calls at every limit, never trips — in both the verify script *and* `tests/test_round9_findings.py`; (b) the *general* claim is false on engine-work-only charts → **R10-06** (Medium, doc) |
| **#210** | `TestAsyncRollbackRearmCycleBounded` waits for convergence and asserts the exact plateau | **FIXED** — real convergence-poll loop, asserts `maxIterations + 3 = 1003`, 5/5 green; independently reran, 1 passed in 2.05 s. No flake under `PYTHONHASHSEED` 1 or 2 (85/85 each) | CHANGELOG `+2` vs `+3` self-contradiction → **R10-10** (Low, doc; both figures are right for their own shapes — R10-M1) |

**The round's one sentence: for the first time, every fix landed on every axis it claimed.** Rounds 6, 7, 8 and 9 each found at least one fix that held on one engine or one service spelling and not the other. Round 10 finds none. The service-kind axis is flat across the entire corpus except for one *documented, intended* divergence (`def` services are non-preemptable — `production-characteristics.md` §2, R10-D2).

---

## 2. Regressions — ours-fixtures vs library

### 2a. Library — NO TRUE REGRESSION

`gate/run_gate.py --timeout 120` (254.5 s) diffed against the recorded `gate/result-main-f28719c.json` baseline. **All 15 status deltas are new lanes or improvements**; every FAIL present at `19cb1f1` reproduces the same pre-existing, already-triaged set.

| kind / id | f28719c | 19cb1f1 | Verdict |
|---|---|---|---|
| `verify` / LC-42 `send_receipt` | FAIL | **PASS ×5/5** | **Improvement** — consistent with #208's receipt-resolution tightening |
| `verifyM4` / `167` `rollback_reinvoke_spin` | FAIL | **PASS ×5/5** | **Improvement** — round 9 recorded this as expected-FAIL ("#201 does not promise the sync re-arm"). Now stable, consistent with #204. **This is CV-C46's ground disappearing.** |
| `verifyM5` / `167` | FAIL | **PASS ×5/5** | Same (second copy of the check) |
| `verifyM6` / 9 ids | MISSING | PASS | Not a delta — `verifyM6` is the round-9 set, absent from a result file that predates it |
| `verifyM6` / `201 lap_parity_stated_exactly` | MISSING | FAIL ×5/5 | **Stale repro, not a defect** — asserts the pre-#201/#209 "sync stops early with `RuntimeError`" shape. Superseded by `209_lap_parity_sweep_1_25.py`, which passes. The live residual in this area is **R10-06**, which this script does not measure. |

Unchanged FAIL sets: `verify` LC-01/12/26/48/57 · `verifyM` LC-01/07/N-1/N-3/N-8 · `verifyM3` 150/154/157/158 · `repro` 21 (informational, library defaults) · `probe` PROBE-01 16/20 and PROBE-03 13/17 **on the same cells** (A3/A6/A10/A18, C6/C7/C15/C17) — no widening.

### 2b. The owed measurement — DISCHARGED

Round 9 carried "coverage unmeasured" as its largest open risk and made it the first item of its re-verification recipe. The suite ran in background here and **finished after the bench agent's reporting bound**, at `suite-19cb1f1.log`:

```
3505 passed, 13 skipped, 15 warnings in 566.57s (0:09:26)
TOTAL  8923 stmts  474 miss  3848 branch  350 partial  93%
Required test coverage of 90.0% reached. Total coverage: 92.78%
```

**0 failures, 92.78 % coverage** — above the library's own 90 % floor, above our 86 % gate bar, and up from 92.70 % at `6db65d8`. `56-r10-suite-bench.md` reports this as incomplete (~25 % observed) because it was written before the run finished; **this verdict supersedes that line**. Decision-table row 2 is not triggered, on measured evidence.

### 2c. Ours — stale fixtures, not library regressions

| Script | Why it exits 1 | Action |
|---|---|---|
| `verify-main-f28719c/201_lap_parity_stated_exactly.py` | Asserts the pre-#201/#209 shape | **Retire** — superseded by `verify-main-19cb1f1/209_lap_parity_sweep_1_25.py` |
| `post-6db65d8/new/repro/R8-02_def_service_uncancellable…py` | Pre-#193 expectation; now a documented contract | Retire (carried from round 9, still owed) |
| `…/R8-03_children_timeout_def_noop.py` | #194 changed the contract | Retire (carried) |
| `…/R8-04_always_ondone_reentry_settle_tripped.py` | #196 moved `always` into the settle pass | Retire (carried) |
| `…/R8-11_service_kind_lap_parity.py` | Superseded by the `209_*` sweep | Retire (carried) |
| `…/R8-05_doneevent_forgery.py` | `check2` does not catch `UnknownEventError` — **which is the protection firing** | Fix: treat `UnknownEventError` as the success mode (carried) |
| `post-f28719c/new/repro/CV-F28-01*.py`, `CV-F28-02*.py` | Both fixed upstream by #204 / #207+#209 | Retire → convert to regression pins that FAIL if the fix is lost |
| `battle-19cb1f1/fuzz/n6_shrunk_repros.py` §D2 | Correct — this is **R10-06**, a live doc defect | Keep |
| Library `tests/test_round9_findings.py` `nested_invoke` cell | Inert padding — never exits state `a`, 2 calls at any limit | **File upstream**: the pin's second shape proves nothing |

Also owed and unchanged from round 9: `gate/run_gate.py` has **no `verifyM7` stage** for `issues/verify-main-19cb1f1/`, and its `BASELINE_COMMIT` and special-case tables still target `f28719c`. The gate correctly reported `19cb1f1` as "NOT a recorded baseline" rather than silently passing it — the harness was honest, it is just behind. Fixed in §10.

---

## 3. Scorecard per battle track (both service kinds)

`async` = `async def` services on `Interpreter`; `def` = plain `def` services, run on `Interpreter` and, where the track covers it, on `SyncInterpreter`.

| Track | async | def | New defects (post-refutation severity) | Verdict |
|---|---|---|---|---|
| **semantics** | clean | clean | R10-01 (Low), R10-05 (Med) | #203/#204 hold on both kinds. `d10_sem_1_after_replace` reproduces on both kinds but is Class-A in-process (refuted to Low). |
| **concurrency** | clean | clean | R10-01 (Low), R10-08 (Low) | **R10-02 REFUTED outright.** `t1_after_provenance_forgery` 8/8 forged — all Class A. 100-machine stranded storm behaves correctly once the shape is spelled with `reenter: true`. |
| **persistence** | clean | clean | R10-04 (Med), R10-05 (Med), R10-09 (Low) | `u2_after_forgery` controls B/G refused — the external boundary holds. The surviving items are the armed-timer snapshot gap and the 0.8.0 migration cliff, both real. |
| **determinism** | clean | clean | — | All prior determinism fixes hold. `#209` sweep 25/25 exact on the discriminating shape. |
| **security** | clean | clean | R10-01 (Low, downgraded from Blocker) | The one Blocker candidate of the round. Every vector reproduces; none crosses a trust boundary. External name/shape confusion — the boundary #195/#203 target — refused in every probe under `strict:True` + `onUnhandled:"error"`. |
| **fuzz** | clean | clean | R10-06 (Med, doc) | `n6` §D2: 24/25 limits differ on engine-work-only charts (async ~`3·mi+3`, sync ~`2·mi+3`). Both lanes still trip. `n5` 1408 cells: 0 success-shaped receipts over an illegal configuration. |
| **observability** | clean | clean | R10-08 (Low), R10-13 (Low) | #207 materially improves the stranded-vs-slow ambiguity (R10-M3: exactly-once, correct payload, both engines). Residual: the trip never reaches `on_error`, and 99.3 % of call-site shed is invisible to `on_event_dropped`. |
| **soak** | clean | clean | — | Prior scripts re-run. `r18`/`r19`/`n7`: 915 600/915 600 external priority sends applied, 0 lost — R9-03's starvation claim stays refuted and is now withdrawn as FIXED. |
| **contracts B1–B5** | clean | clean | 0 library | Happy paths 5/5, invariants+parity 27/27, snapshot/restore 5/5, all both lanes. |
| **contracts B6–B10** | clean | clean | **0 library** (was 1 High) | **LD-01 closed by #204**: 3 leaked → **0/6**. `def` lane 51/52 → **52/52**; drives 13/14 → **14/14**. W-01 retired. Ours: CD-01, CD-02 unchanged. |
| **contracts B11–B15** | clean | clean | 0 library | **CV-F28-01 and CV-F28-02 both FIXED.** Three-lane lap parity 25/25, plateau `limit+2`. B18 priority under a chain: 60/60 applied, 0 dropped, kill pre-empts. |
| **contracts B16–B20** | clean | clean | **0 new library** | 10/10 build clean; sharp edges 13/13 per lane; snapshot/restore clean on every drive; sync parity 5/5 incl. service-call trace. **Every B16–B20 failure on this commit is OURS.** |

**The service-kind axis is now completely flat.** Round 9's headline was "flat on every track except R9-04." R9-04 is closed. The only surviving `def`/`async` divergence in the entire corpus is the documented, intended one: `def` services are non-preemptable and block their own machine's timers (`production-characteristics.md` §2 — R10-D2), plus `SyncInterpreter` + `async def` → `NotSupportedError`, also documented.

**Time-boxed reductions, stated rather than glossed:** `bench_c_timers` timed out with zero output for a **second consecutive round** and `bench_e_actors` was not attempted; no matched-load A/B between `f28719c` and `19cb1f1` was run, so this round's ~5× throughput jump (and Budget 1 flipping from missed to met) **cannot be attributed to the fix set** and is more likely host contention — the *ratios* between policies held steady while the absolute baseline moved, which is the signature of load, not of engine change. No item sits on a Blocker/High evidence path.

---

## 4. Contract machines — PASS/FAIL under async AND def

All 20 machines built from the corrected catalogue JSON (byte-compared before use; `B16.machine.json` sha1 `9d8ad9937417`, `ka_killswitch` sha1 `3d0de943effd`, B18 policy block sha1 `4e9e8a9b60be`) and driven end-to-end with the mandatory config block on every machine and every interpreter.

| Group | Machines | async | def | Library defects | Ours |
|---|---|---|---|---|---|
| **B1–B5** | order lifecycle core | PASS | PASS | **0** | — |
| **B6–B10** | order lifecycle algos | PASS | PASS | **0** (LD-01 closed) | CD-01 (→ R10-C4, **refuted**, Low), CD-02 (→ R10-C2, ours) |
| **B11–B15** | market data / recording | PASS | PASS | **0** (CV-F28-01/02 closed) | — |
| **B16–B20** | control plane | PASS | PASS | **0** | **C-04** (Blocker), **C-07b** (Blocker), C-06 (→ R10-C3, Medium), C-04b (→ R10-C5, Medium) |

**Zero library defects across all 20 machines on both spellings.** That is a first.

### Status of OUR C-04 and C-07b

Both were re-filed this round as library candidates (R10-C1 Blocker, R10-C2 Blocker) and **both are refuted as library defects**, by corrected-usage probes rather than by argument:

- **C-04 / R10-C1 — REFUTED as a library defect; retained as OUR Blocker.** The symptom reproduces in both arities (`LOGOUT`, `IDLE_DEADLINE`, `ABSOLUTE_DEADLINE` leave `elevation.elevated` with `elevated_until_us=9999999`; `STEP_UP_OK` re-elevates a dead session). The cause is our chart: `elevation.elevated.on` **omits those events**, while `REVOKE` — listed in *both* regions — clears correctly, which proves engine dispatch is sound. SCXML §3.4/§3.7 and XState v5 agree that parallel regions process events independently and a `final` child ends only its own region. Not a convergence artefact (polled to convergence). **Corrected usage** — all revocation events handled in the elevation region plus a `session_alive` guard on `STEP_UP_OK` — yields `still_elevated=False` and `re_elevated_dead=False` for all four kills, on both `def` and `async def`.
- **C-07b / R10-C2 — REFUTED as a library defect; retained as OUR Blocker.** Reproduced in all four cells (async/def × error/defer) past convergence, but it is **documented opt-in policy**: the README defines `onUnhandled:"error"` as stopping with `UnhandledEventError` (the default is XState's ignore), and CHANGELOG #170 states a guard-denied event *is* an unhandled event. SCXML §3.13 `selectTransitions` and XState v5 both consume an event whose only guarded arm denies, selecting no transition; **neither spec even defines an error-on-unhandled disposition**. Fixable in config alone: adding the ordered unguarded fallback `RELEASE` arm while **keeping** `onUnhandled:"error"` yields `denied → running/engaged` and `authorised → running/clear` on both engines. The defect is our catalogue's policy choice — the round-6 Amendment-6 removal **never landed in the JSON** and is still present at `19cb1f1`.

**Both gate B16/B18 on *any* runtime and gate no library decision.** They are now open **five rounds** and are the critical path for Phase 2.

Also refuted this round, on the same standard:

- **R10-C4 → REFUTED (residual Low, CV-C4x).** Kill/cancel deferrable for a full service duration is a contract-modelling error: B6/B9 declare the kill event only on *sibling* states, so no handler exists on the active invoking state or any ancestor. Isolated repro (both styles, polled to convergence): sibling-only **1.458 s**, parent-level handler **0.001 s**, invoking-state handler **0.000 s**. XState v5/SCXML would drop the event outright; `onUnhandled:"defer"` replaying after the next state change is documented (README:1462) and **loses less**. `priority=True` is documented as an inbox lane, not configuration-level selection; no send dropped or charged. Residual constraint: declare kill/cancel on an **ancestor of all invoking states** — statically lintable.
- **R10-C3 → DOWNGRADE High → Medium.** The symptom is CONFIRMED in both lanes, polled to convergence (`OPERATOR_RESOLVED` in `reconciliation.stale_lockout` is deferred, state unchanged). The *stated cause* is refuted: `RECONNECTED` is an ordinary external event with no engine, contract or interpreter restriction on its source, and driving it from the same call site clears the lockout to `reconciliation.idle` with `reset_failures` applied and `consecutive_failures=0`, identically in both lanes. **The critical account-locked state is escapable by the operator**, so the High rating — which rested on "clearable only by an event the operator cannot produce" — does not hold. Residual real defects justifying Medium: catalogue **INV-B19-b** says `stale_lockout` is "cleared only by `OPERATOR_RESOLVED`" while `B19.machine.json` declares only `RECONNECTED` (**the contract contradicts its own normative invariant**); `RECONNECTED` is a *connectivity* signal, so an automatic reconnect can clear a paged critical state with no operator in the loop and no distinct audit record; the escape is venue-conditional; and deferred events accumulate without bound (1 → 8 across presses, still 8 after escaping to idle).

---

## 5. Surviving defects by final severity

Post-refutation. **0 Blocker · 0 High · 5 Medium · 7 Low** library defects, + 1 refuted outright.

### Blocker (0)

**None.** R10-01 refuted Blocker → Low. R10-C1 and R10-C2 are ours, not the library's.

### High (0)

**None — the High row is empty for the first time in ten rounds.** R9-02 closed by #203, R9-04 closed by #204, R10-02 refuted outright, R10-03 downgraded to Medium, R10-C3 downgraded to Medium, R10-C4 refuted.

### Medium (5)

| ID | Title | Disposition |
|---|---|---|
| **R10-03** | `#206` charges self re-armed delayed sends per lap with no time awareness, so `raise(delay=)` self-paced periodic work dies at `maxIterations` on the async engine | **DOWNGRADE High → Medium.** Reproduces robustly (polled to convergence, 15 s/2 s plateau: still 9 beats; both kinds; 30/100/250 ms alike — the charge is purely per-lap, period-independent). But it is **not undeclared**: CHANGELOG #206 states a delayed self-raise trips at the same lap as a zero-delay raise cycle, and `json-config.md:110` already scopes `maxIterations` to unbroken self-raise/self-send chains. **The documented heartbeat idiom (`after`) is unaffected** — measured 185/183 beats in 6 s with **zero drops** at the same 30 ms and `maxIterations=8`, versus 9 for the `raise(delay=)` spelling; and **no doc presents self-`raise(delay=)` as a heartbeat**. Failure is loud (`RunawayChainError` on `last_error`, `on_event_dropped("chain_budget")`, WARNING; machine stays `running`) and any external traffic clears the chain. Residual real defect: the chain-clear test is **time-blind**, and `production-characteristics.md:95` ("a budget is not a deadline") now misleads. Doc/behaviour gap on a non-idiomatic spelling. **CV-C47** (new). |
| **R10-04** | An armed-but-unfired delayed self-`raise` has no snapshot representation and is silently lost on restore | **CONFIRMED.** `interpreter.py:1480-1497` reads only the priority queue and inbox deque; #206 made the delayed self-send a debt of the arming step and a snapshot discharges that debt with no hook, no warning, no error. Restore does not re-run entry, so the machine resumes into a state whose only exit was the lost event. An **external** delayed send survives — asymmetry confirmed in the same run, both kinds. Contained by **CV-C23** (quiescence-only snapshots) + **CV-C49** (new). |
| **R10-05** | Restore bypasses `strict` and drops lane provenance; a persisted `after` is now **refused rather than demoted** (0.8.0 migration cliff) | **CONFIRMED**, two symptoms one path. (a) `_check_strict` runs at the `send()` call site (`base_interpreter.py:1767`) but restore re-enqueues via `_enqueue_restored` → `_put_inbox`, bypassing it — contradicting the documented restore contract at `events.py:403-414`. (b) Records carry only `['kind','payload','type']`; the restored `_priority_queue` is `[]`. A 0.8.0-written record has `kind:"after"` but no `engine` flag, so #203's gate refuses it — **the deadline is dropped with no raise, no warning, nothing in `last_error`**. The security *direction* of #203 is right; the failure *mode* is not. **CV-C48** (new). |
| **R10-06** | `#209`'s "all three lanes agree at limits 1–25" is false on engine-work-only charts; the gap grows with the limit | **CONFIRMED, DOC-DEFECT.** `n6` §D2 (`always` + zero-delay `raise` cycle, limits 1–25): **24/25 differ.** mi=1 sync 4 / async 6; mi=10 sync 23 / async 33; mi=19 sync 41 / async 60. Both lanes trip at every limit. #209 genuinely fixed the two shapes it *measured* and then re-asserted the claim generally. At mi=25 the same chart is permitted ~47 % more work on one engine than the other. **The runaway budget is a safety control, so an overstated guarantee about it is worth fixing.** Compounded by the `nested_invoke` pin being inert (§1). No runtime consequence for us. |
| **R10-07** | Unknown top-level config keys accepted silently; a misspelled safety policy downgrades to its permissive default | **CONFIRMED, carry-forward unchanged from `6db65d8`/`f28719c`.** `create_machine({..., 'spawnBlockingTimeoutMs': 1234})` builds clean and the attribute is `None`. Bad *values* for *known* keys are still correctly refused. Material because the keys most likely to be mistyped are the safety policies (`actionErrorPolicy`, `guardErrorPolicy`). Contained by the **wrapper key whitelist** (CV-C-whitelist, already mandated). |

### Low (7)

**R10-01** (engine-event provenance is type identity — **refuted Blocker → Low**; hardening asks: prefix or privatise the `engine_*` factories, mandate signing the whole snapshot rather than trusting a plaintext boolean, document the `_replace` re-typing footgun) · **R10-08** (call-site `QueueOverflowError` refusals fire no `on_event_dropped`; 241 414/243 225 = **99.3 %** of shed invisible to metrics — contained by CV-C36) · **R10-09** (`SnapshotMidStepError` from an invoked child's entry action reports `child=False`; the refusal itself is correct, only the attribution is wrong) · **R10-10** (CHANGELOG `+2` vs `+3` contradiction; both are right for their own shapes per R10-M1, the changelog conflates them) · **R10-11** (`#208`'s illegal-configuration branch is unreachable on a live machine because `_repair_configuration()` runs on every settle trip; harmless and correctly conservative, but an unexercised O(states) recursive walk on the `wait=True` receipt hot path — measure before adopting `wait=True` broadly) · **R10-12** (`after` does not fire under `SimulatedClock.increment()`; **pre-existing, identical on `f28719c`, NOT caused by #203** — needs isolation from the harness) · **R10-13** (chain trip never reaches `on_error`/`interpreter.error`; `last_error` **cleared on the `async def` lane and retained on `def`**, so a supervisor sampling asynchronously misses the runaway on the *recommended* spelling — contained by CV-C50).

### Refuted outright (1)

**R10-02** — "a self-targeting `onDone` never re-arms the invoke; the machine parks dormant and silent." **API misuse against documented, XState-v5-aligned semantics.** The behaviour reproduces (`SELF` submits=1, dormant=True), but `onDone: {target: "work"}` from inside `work` is an **internal** self-transition by contract: `base_interpreter.py:3021-3028` routes `source == target && !reenter` to `_execute_internal_transition`, so no exit/re-entry occurs and there is correctly no `statesToInvoke` record to arm. The report's SCXML §3.12 premise describes an **external** transition; SCXML also defines `type="internal"`, and **XState v5 makes internal the DEFAULT for self-transitions with `reenter: true` as the opt-in** — which this library follows and documents three times (`pythonic-api.md` L576-599, `api/index.md` L260, `troubleshooting.md` L284-289, which names this exact wedge shape and its fixes; CHANGELOG 0.4.2 L1913-1921). Verified with a standalone probe from neutral cwd, both kinds, both engines, polled to convergence (stable submit count over 6×0.1 s, converged at 0.7 s — **not sampled**): with `"reenter": True` every live lane gives `entries == submits == 22 == maxIterations + 2`, `last_error = RunawayChainError`, and `on_invocation_stranded` fired `[["m.work","spin"]]` — identical to the HOP control plus the #207 stranding report. Without `reenter`, every lane gives exactly `submits = 1`. **Zero violations.** The "silent/indistinguishable" half also fails: `has_dormant_invocations == True` in the plain rows **is** the documented liveness answer (`:1641-1643`) and `pending_invocations()` names the invoke; the stranded hook is silent because nothing was cut, which is #207's stated scope (`_stranded_by_cut`, `:1921`) — the probe's own oracle was miscalibrated. **Residual Info only:** `validation.py:205` warns for an `always` self-target that cannot progress but has no equivalent for an `onDone`/`on` self-target restart loop.

### Ours, not the library's

**Catalogue Blockers: C-04** (R10-C1) and **C-07b** (R10-C2) — refuted as library defects, retained as ours, **open five rounds, and the only Blockers of any kind left in this study**. **Medium: R10-C3** (B19 `stale_lockout` contradicts INV-B19-b; escapable via `RECONNECTED` but unauditably and venue-conditionally), **R10-C5** (B16 re-elevation via the `elevated→elevated` arm is unaudited — `audit_step_up=1` for 2 `STEP_UP_OK`), **CD-02**. **Low: R10-C4** (→ CV-C4x, statically lintable), C-05, C-01, C-07.

### Design constraints (documented behaviour, wrapper obligations, not defects)

**R10-D1** (rollback + `invoke.onDone` re-arms a side-effecting service — each lap is a real exchange order; make invoked services idempotent, client order id keyed on chart state not on lap) · **R10-D2** (invoke-bearing states with an escape transition must use `async def`; on the `def` lane the escape is not an escape — binds B12 `buffering`/`stepping`, B13 `subscribing`) · **R10-D3** (hand-built `AfterEvent` refused at the inbox — **correct**, it is R10-01's control arm; wrapper timeout supervisors drive timers through the clock or a domain event) · **R10-D4** (`send()` stays success-shaped after `status="error"`; read `status`/`error` after each send).

### Harness errors

**R10-H1** — `send(wait=True)` treated as "the service chain finished." **The receipt is a macrostep receipt**, not a chain receipt; fixed-width settles race under CPU load. Ours was wrong, not the library.

---

## 6. GATE DECISION (per `20-adoption-gate.md` §7)

Applying the decision table in order, first match wins:

| Row | Condition | Status at `19cb1f1` |
|---|---|---|
| 1 | Any `ERROR` row in gate output | **No.** 254 checks, no ERROR rows. |
| 2 | Suite fails, or coverage < 86 % | **No — and measured, not inferred.** `suite-19cb1f1.log`: **3505 passed, 13 skipped, 0 failed**; **coverage 92.78 %** (library's own 90 % floor reached). This discharges round 9's single largest open risk. |
| 3 | Snapshot format changed while LC-21 open | **No.** LC-21 closed; `version` + `machine_hash` present, #198 tightened v1, #205 added `minimum_version` / `expected_machine_hash`. The format did **not** change at `19cb1f1` — but see **R10-05**, a *restore-compatibility* break for 0.8.0-era `after` records, triaged Medium and contained by CV-C48. |
| 4 | Any filed **Blocker** repro still exits 1 | **No. The Blocker row is EMPTY.** LC-01/02/03/16 closed; R8-01 closed by #192; R9-01 refuted; **R10-01 refuted Blocker → Low**; R10-C1/R10-C2 are ours. |
| 5 | All Blockers closed; **> 5 High** open | **No** — open-High is **0**. |
| 6 | All Blockers closed; 1–5 High open with enforced mitigations | **No** — open-High is **0**, so this row (round 9's match) no longer applies. |
| 7 | All Blockers closed; 1–5 High open *without* enforced mitigations | **No.** |
| **8** | **All Blocker and High closed; all Medium triaged; BENCH-1/2/6 not all met** | **MATCH.** All 5 Medium triaged with named containment (§5). **BENCH-2 misses by ~4.5×** (443.6 market ev/s async / 394.0 sync vs a 2 000 budget) and **BENCH-6 (timer drift under load) is UNMEASURED** — `bench_c_timers` timed out with zero output for a second consecutive round, so its threshold **cannot be claimed met**. BENCH-1 reads as met (p95 144.6 ms vs 300 ms, 2.07× headroom) but on an unmatched-load run and is **not** relied on. |
| 9 | All closed, all Medium triaged, **all** benchmark thresholds met | **Not reached** — BENCH-2 missed, BENCH-6 unmeasured. |

### → **ADOPT WITH CONSTRAINTS** (row 8 — benchmark-derived constraints only)

**Stated plainly: this is the lightest regime this library has ever qualified for, and it is the ceiling round 9 predicted.** The decision advances from row 6 to row 8. The difference is not cosmetic: under row 6 the adoption *rested on* our own mitigation mechanisms for two open Highs, and a red contract-suite cell would have collapsed it to row 7 (DEFER). Under row 8 there are no open Highs to mitigate. The constraints that remain are **architectural consequences of the benchmarks** — the dedicated event loop, the ≥99 % pre-filter, the external `MonotonicScheduler` — plus a shorter list of Medium-derived wrapper obligations. None of them is load-bearing for a Blocker or a High.

**Row 9 is not reachable and we should not plan for it.** BENCH-2 is a ~4.5× architectural gap, not a tuning gap (it was ~14× at round 9; the improvement is most likely host contention, not engine change — see §3). BENCH-6 is unmeasured, and the honest reading of two consecutive timeouts is that the bench needs re-scoping, not that the threshold is met. The ≥99 % pre-filter and the external scheduler are **permanent features of our design**, not temporary mitigations.

### The constraints that carry the decision

| Unmet threshold | Constraint | Enforcing mechanism |
|---|---|---|
| **BENCH-2** (rule rate 443.6 ev/s vs 2 000) | Statecharts own rule **lifecycle only**; per-tick predicate evaluation is a plain function pass behind a **≥99 % pre-filter** | Benchmark test in CI |
| **BENCH-6** (timer drift — **UNMEASURED**, 2 rounds) | `after` only for coarse, non-critical timeouts where seconds of lateness is tolerable; **all** algo timing uses an external `MonotonicScheduler` with absolute deadlines in context | Linter rule banning `after` in algo machine definitions |
| **BENCH-1** (met, but on an unmatched-load run) | Order path runs on a **dedicated event loop / process**, no rule or market-data traffic on it | Startup assertion on loop identity. **Retained on precaution**, not on a measured miss. |
| **LC-27** (no clock injection) + **R10-12** | Replay/backtest cannot use `after` at all; virtual time supplied entirely by the external scheduler | Contract test. R10-12 (`after` inert under `SimulatedClock`) **re-grounds** this independently of LC-27. |
| **LC-43** | All `send()` on the owning loop; cross-thread via `run_coroutine_threadsafe` / our gateway | Contract test |

### Pin policy

> **`== 0.8.1` once tagged; until then commit `19cb1f1` + its source sha256.**
> A **vendored copy per MUST-08** is kept in-tree and is what CI builds against. `__version__` still reports `0.8.0` on this commit, so **no pin may key on the version string.** The pin flips to `== 0.8.1` only when a tag exists whose `__version__` actually reports `0.8.1` and whose tree hash matches what we verified here.

### Standing gate

**The contract suite (`tests/xstate_contract/`) remains in CI as a standing, blocking gate** — on every commit and nightly against the vendored copy: 20 contract machines end-to-end on **both** service spellings, the three mandated drives, and the constraint tests named in §7. **Any red cell blocks merge.** Under row 8 a red cell no longer collapses the decision to DEFER, but it still blocks the merge and still blocks Phase-3 completion.

---

## 7. Constraints — retire / stand / new

### Retired (3)

| Constraint | Why it retires |
|---|---|
| **CV-C46** (the order path never runs on `SyncInterpreter`) | **RETIRES.** Its entire ground was R9-04: 2 of the 3 leaking roll-forward lanes were sync-engine lanes, and the `167 rollback_reinvoke_spin` gate cell was a sync-only FAIL. #204 closes the roll-forward half **on both engines and both service kinds** — `LD-01` 0/6 leaks, `167` PASS ×5/5 on both `verifyM4` and `verifyM5`. Retiring it as a *safety mandate*. **Downgraded to a design preference**: the async engine remains our order-path engine for throughput and preemptability reasons (R10-D2), but that is now an engineering choice, not a defect containment. |
| **CV-C45's send-side clause** (the gateway rejects any externally submitted `AfterEvent`) | **RETIRES.** Its ground was R9-02 — a public `AfterEvent` with the right type string firing a 60 s timer instantly at the default `strict=False`. #203 closes it in the engine: `r9_after_provenance.py` refuses the forgery at `send()` with a named `UnknownEventError` on both spellings, and `u2_after_forgery`'s controls B and G refuse under our hardened config. **The restore-side clause of CV-C45 does NOT retire** — it is re-grounded on R10-05 and widened below. |
| **CV-C32 as a safety rule** (async engine ⇒ every service `async def`) | **RETIRES as a safety rule; the rule itself STANDS on new ground.** It was load-bearing for R9-04 and is no longer. It remains **mandatory** for R10-D2 (an invoke-bearing state with an escape transition cannot be pre-empted on the `def` lane — the escape is not an escape) and for `def` services blocking their own machine's timers. Same text, different and weaker justification; keeping the old justification is how constraints rot. |

### Standing (unchanged or re-grounded)

**CV-C01…CV-C22** as amended · **CV-C23** (quiescence-only snapshots via the factory wrapper; envelope always `version ≥ 1` + `machine_hash` + **HMAC tag**) — **re-grounded and strengthened**: #205 gives the caller `minimum_version` and `expected_machine_hash`, which we now pass explicitly, but R10-01 Class B proves a blob writer needs no event forgery at all, so **signing the whole snapshot remains the only real boundary**. CV-C23 additionally now carries R10-04 (an armed delayed self-`raise` is lost across a snapshot — quiescence-only makes the window small but not zero) · **CV-C25** (no external `send()` from inside an action; gateway queue only) · **CV-C27′** (two-sided `configuration`/`state_ids` agreement on restore; defence in depth since #186) · **CV-C28** (no `LoggingInspector` in production) · **CV-C32** (see above — stands, re-grounded on R10-D2) · **CV-C33** (`send_threadsafe` only via our gateway) · **CV-C34** (no `"*"` scaffolding) · **CV-C35** (no `always` into an invoked child, no `always` to an ancestor of its own source) · **CV-C36** (every `send_threadsafe` future read; refusals counted and paged) — **re-grounded on R10-08**: the gateway must count call-site `QueueOverflowError` refusals **itself**, because 99.3 % of shed is invisible to `on_event_dropped` · **CV-C39** (`await start()` always bounded) · **CV-C40** (no snapshot before the post-start settle observation; in depth since #199) · **CV-C41** (root-only snapshots; child state via explicit `sendTo`) · **CV-C42** (no `priority=True` anywhere, any origin) — **re-grounded**: R9-06 is superseded by #206, but R10-03 keeps a self-paced delayed chain shedable-but-fatal, and R10-C4's refutation confirms `priority=True` is an inbox lane, not configuration-level selection, so it never buys what people expect · **CV-C44** (entry actions on invoke-bearing states are `async def`, yielding at least once; in depth since #194) · **CV-C06 clause** (never read a `send(wait=True)` receipt for configuration — R9-08 closed by #208, retained on **R10-H1**: a receipt is a *macrostep* receipt, never a chain receipt) · **wrapper top-level config-key whitelist** (R10-07, unchanged and still required).

**CV-C45 (restore side only), widened:** strip every `DoneEvent`/`ErrorEvent`/`AfterEvent` record from `pending_events` before `from_snapshot()`, **matching on the serialised record `kind` as well as the class**, and **re-arm the corresponding deadlines explicitly from context** rather than relying on the restored record. Ground: R10-05 — a persisted `after` is now silently *refused*, so a restore that relies on it loses a deadline with no raise, no warning and nothing in `last_error`.

### New (4)

| ID | Constraint | Ground | Enforcement |
|---|---|---|---|
| **CV-C47** | **No `raise(delay=)` self-paced periodic work** on the async engine. Periodic work is driven by the external `MonotonicScheduler`, or by `after` (measured clean: 185/183 beats in 6 s, zero drops), or by the sync engine's `tick()`. | R10-03 | Lint: ban `{"type":"raise","params":{"delay":…}}` targeting the machine's own events in any machine definition. `test_cv_c47_no_self_delayed_raise`. |
| **CV-C48** | **0.8.0-era snapshots are migrated before restore.** Any `pending_events` record with `kind:"after"` and no `engine` flag is rejected at the envelope, the blob is refused, and the deadline is re-armed from context. A refused restored deadline must be **loud** in our code since it is silent in the library's. | R10-05 / O-2 | `test_cv_c48_pre_0_8_1_after_record_refused_loudly`; envelope version fence. |
| **CV-C49** | **Snapshot only at quiescence with no armed self-delayed debt.** The wrapper asserts there is no in-flight delayed self-`raise` before snapshotting; any state whose only exit is a delayed self-`raise` is forbidden on the persisted path. | R10-04 | `test_cv_c49_no_armed_self_delay_at_snapshot`; static check over the catalogue. |
| **CV-C50** | **`CvErrorHooks` implements `on_invocation_stranded` and samples `on_event_dropped(..., "chain_budget")`** rather than polling `last_error`; the supervisor's health sweep asserts `has_dormant_invocations() is False`. | R10-13 (+ R10-02's Info residual) | `test_cv_c50_chain_trip_observed_on_both_lanes` — must pass on **both** `def` and `async def`, since `last_error` is cleared on the `async def` lane. |
| **CV-C4x** | **Kill/cancel events are declared on an ancestor of every invoking state**, never only on siblings. | R10-C4 (refuted → residual Low) | Statically lintable over the catalogue: `test_cv_c4x_kill_declared_on_ancestor`. |

### FINAL mandatory config block

```jsonc
// Every CandleViewer machine definition. Round 10, main @ 19cb1f1.
{
  "actionErrorPolicy": "rollback",   // R10-D1: rollback + invoke.onDone RE-ARMS the service,
                                     // and each lap is a real exchange order. Services MUST
                                     // be idempotent under re-entry - client order id keyed
                                     // on CHART STATE, not on lap. Plateau is maxIterations+2
                                     // (event-entered) / +3 (initial-state invoke): BOTH are
                                     // correct for their shape (R10-M1); the CHANGELOG
                                     // conflates them (R10-10).
  "guardErrorPolicy": "deny",        // A guard-denied event IS an unhandled event (#170), and
                                     // guard_denied outranks it - so denied events must be
                                     // drained from the buffer, and any state whose only arm
                                     // is guarded needs an ORDERED UNGUARDED FALLBACK.
                                     // This is exactly C-07b (R10-C2): refuted as a library
                                     // defect, SCXML 3.13 and XState v5 both agree the engine
                                     // is right. OURS to fix, and fixable in config alone.

  "onUnhandled": "defer",            // order path. No "*" scaffolding (CV-C34).
                                     // Authorisation/risk events are non-deferrable (W-03).
                                     // R10-C4 (REFUTED, residual Low -> CV-C4x): defer only
                                     // looks like a kill-switch latency bug when the kill
                                     // event is declared on SIBLINGS. Sibling-only 1.458s;
                                     // ancestor handler 0.001s; invoking-state 0.000s.
                                     // Declare kill/cancel on an ANCESTOR of all invoking
                                     // states. priority=True does NOT help - it is an inbox
                                     // lane, not configuration-level selection.
  "onUnhandled": "error",            // control machines ONLY, and NOT on B18 - C-07b, OURS,
                                     // Blocker, open FIVE rounds (E50). Keeping "error" is
                                     // fine IF engaged carries an unguarded RELEASE fallback
                                     // that audits the denial as a no-op - verified to yield
                                     // denied->running/engaged and authorised->running/clear
                                     // on both engines. The Amendment-6 removal still has not
                                     // landed in ka_killswitch JSON (sha1 3d0de943effd).

  "strictTargets": true,             // #147: RootTargetError at build time, non-downgradable.
  "strict": true,                    // #190/#195/#203: config-level strict is inherited; a "*"
                                     // handler does not defeat it; hand-built Done/Error/AFTER
                                     // events are refused on both engines and both kinds.
                                     // #203 CLOSES R9-02 - the after selection site now gates
                                     // on is_system_event. The send-side clause of CV-C45
                                     // RETIRES. Two residuals remain, both ours to contain:
                                     //  - strict does NOT gate events restored from
                                     //    pending_events (R10-05a) -> CV-C45 restore clause.
                                     //  - a 0.8.0-era persisted `after` record is now silently
                                     //    REFUSED, not demoted (R10-05b) -> CV-C48. The
                                     //    deadline is DROPPED with no raise and no warning.
                                     // R10-01 (Blocker->Low): in-process forgery via
                                     // engine_after / _replace / pickle / deepcopy is real but
                                     // presumes attacker-controlled Python, which already
                                     // grants strictly more. R10-07 STANDS: a TYPO in any
                                     // top-level key is still accepted silently -> the wrapper
                                     // WHITELISTS top-level keys before create_machine.
  "maxIterations": 500,              // LIVE and lane-parity-verified on the discriminating
                                     // shape at limits 1-25 (#209). TWO residuals:
                                     //  - on ENGINE-WORK-ONLY charts the lanes DIVERGE and the
                                     //    gap grows with the limit (R10-06): async ~3*mi+3,
                                     //    sync ~2*mi+3; 24/25 limits differ. Do not rely on
                                     //    cross-engine budget equivalence as a safety property.
                                     //  - the chain-clear test is TIME-BLIND, so a self-paced
                                     //    raise(delay=) heartbeat dies at maxIterations beats
                                     //    regardless of period (R10-03) -> CV-C47. Use `after`
                                     //    (measured 185 beats / 6s, ZERO drops) or the external
                                     //    MonotonicScheduler. NOTE: BENCH-6 is UNMEASURED for
                                     //    two rounds, so `after` is still coarse-timeouts-only.
  "spawnBlockingTimeout": 5000       // Reads back as spawn_blocking_timeout_ms == 5000.0 on
                                     // B11-B15 (verified). A trailing-Ms TYPO would still be
                                     // accepted silently (R10-07) -> key whitelist.
}
```

```python
# Runtime construction - mandatory (round 10, main @ 19cb1f1)
MachineLogic(strict=True)             # W-01: create_machine is NOT a conformance gate; the
                                      # wrapper cross-validates the logic table against JSON.
Interpreter(..., max_queue_size=64, overflow_policy=OverflowPolicy.RAISE,
            service_pool_size=<explicit>)   # default is 4. DC-1: SyncInterpreter accepts
                                      # NEITHER max_queue_size NOR overflow_policy.
                                      # The gateway COUNTS call-site QueueOverflowError
                                      # refusals ITSELF - 99.3% of shed never reaches
                                      # on_event_dropped (R10-08, CV-C36).

# ENGINE:   the order path runs on the async Interpreter. CV-C46 RETIRES as a mandate -
#   #204 closed the roll-forward leak on BOTH engines and `167 rollback_reinvoke_spin`
#   now PASSES 5/5 on the sync lane. This is now a design preference, not a containment.
# Services: async def ONLY on the async engine (CV-C32, re-grounded). Blocking work via
#   asyncio.to_thread. Ground is now R10-D2, NOT R9-04: an invoke-bearing state with an
#   escape transition cannot be pre-empted on the `def` lane - the escape is not an
#   escape (binds B12 buffering/stepping, B13 subscribing). A `def` service also blocks
#   its own machine's `after` timers (#174, documented, unchanged).
# Entry actions on invoke-bearing states: async def, yielding at least once (CV-C44).
# SELF-TRANSITIONS: a transition that targets its own source state is INTERNAL by
#   contract (XState v5 default; the library documents it three times). A self-targeting
#   onDone/on meant to RESTART the state's invoke or entry MUST carry "reenter": true -
#   with it, every lane re-arms to maxIterations+2 and the #207 stranded hook fires;
#   without it, submits=1 forever. R10-02, REFUTED. The validator has no warning for
#   this shape (Info) - our LINT must.
# start():  ALWAYS asyncio.wait_for(start(), CV_START_TIMEOUT) - never bare (CV-C39).
# Timers:   NO raise(delay=) self-paced periodic work (CV-C47). `after` for coarse
#   timeouts only until BENCH-6 is actually measured; all algo timing on the external
#   MonotonicScheduler with absolute deadlines in context.
# Snapshot: factory wrapper only; at quiescence (CV-C23); ROOT ONLY (CV-C41); and NOT
#   while a delayed self-raise is armed - it is discharged silently on restore (R10-04,
#   CV-C49). Never read a send(wait=True) receipt for configuration NOR as "the chain
#   finished" - it is a MACROSTEP receipt (CV-C06 clause, R10-H1).
# Restore:  pass minimum_version=1 and expected_machine_hash=<ours> explicitly (#205);
#   our envelope ALSO writes and VERIFIES an HMAC TAG over the whole blob - #205's
#   fingerprint is explicitly "not a MAC", and a blob writer needs no event forgery at
#   all to relocate the machine (R10-01 Class B). Assert configuration/state_ids agree
#   BOTH ways (CV-C27'). STRIP every done/error/AFTER record from pending_events,
#   matching the SERIALISED `kind` as well as the class, and RE-ARM deadlines from
#   context (CV-C45 restore clause + CV-C48).
# Observability: CvErrorHooks implements on_invocation_stranded; the supervisor samples
#   on_event_dropped(..., "chain_budget") and asserts has_dormant_invocations() is False.
#   NEVER poll last_error - it is CLEARED on the async def lane and RETAINED on def
#   (R10-13, CV-C50).
```

---

## 8. Release-readiness note for 0.8.1

**Would we pin a tag cut at `19cb1f1`? Yes — with one blocking precondition and three that should land in the same release.**

This is the first commit in ten rounds we would pin without a caveat that touches correctness. Zero suite failures, 92.78 % coverage, every claimed fix verified on every axis, zero library defects across all 20 contract machines on both service spellings, an empty Blocker row and — for the first time — an empty High row.

### Blocking before tagging (1)

1. **Bump `__version__` to `0.8.1`.** It still reports `0.8.0` on `19cb1f1`. Round 9's §9 named "a 0.8.1 tag cut with `__version__` still reporting `0.8.0`" as a **verdict-moving process signal** — not a library defect, but evidence that the release process does not check its own claims. Our pin flips from commit+sha256 to `== 0.8.1` **only** when a tag exists whose `__version__` actually reports `0.8.1` and whose tree hash matches what we verified here. Add a release test asserting `__version__` equals the tag.

### Should land in the same release (3 doc fixes, zero code risk)

2. **R10-10** — the CHANGELOG contradicts itself on the runaway plateau (`#207` says `maxIterations + 2`, `#210` says `+ 3`). Both are right for their own shape (R10-M1: an event-entered state has no initial descent and costs one lap less); the changelog conflates them. Code and the library's own tests say `+2` at `:580` and `:643`. **One sentence to fix, and it is a safety control's documented constant.**
3. **R10-06** — `#209`'s "all three lanes agree at limits 1–25" is **false on engine-work-only charts** (24/25 limits differ; at mi=25 one engine is permitted ~47 % more work than the other). Either narrow the claim to the two shapes actually measured, or fix the parity. An overstated guarantee about a safety control is the one class of doc defect worth blocking on.
4. **R10-03's scope** — `production-characteristics.md:95` ("a budget is not a deadline") now misleads, and nothing names `#206` as a **behaviour break** for `raise(delay=)` self-paced periodic work. The changelog describes the fix in terms of a 1 ms ping-pong; the consequence is that self-paced heartbeats stop after `maxIterations` beats on the async engine regardless of period. Name it in the changelog as a break, with the `after` idiom as the migration.

### Should land, but need not block (test hygiene)

5. **The `#209` `nested_invoke` pin is inert.** In both `issues/verify-main-19cb1f1/209_*.py` and the library's own `tests/test_round9_findings.py`, the paired `nested_invoke` shape never exits state `a`, so it fires exactly 2 calls at every limit 1–25 and **never trips `RunawayChainError`**. It is padding, not coverage. The discriminating `rollback_ondone` shape does the real work and passes, so the FIXED verdict stands — but the test claims two shapes and delivers one. Give it a shape that scales, or drop it.
6. **`R10-11`** — `#208`'s illegal-configuration refusal branch is unreachable on a live machine, because `_repair_configuration()` runs on every settle trip before the receipt resolves. Correctly conservative, but it is an unexercised branch guarded by an **O(states) recursive walk on the `wait=True` receipt hot path**. Either exercise it or gate it behind a debug flag; either way, do not describe it in the changelog as a path that fires.

### Not blocking, recorded

`bench_c_timers` has now timed out with zero output for **two consecutive rounds** — it buffers all results to a single JSON dump at the end, so nothing is recoverable from a timeout. That is a harness shape problem (ours), not a library one, but it means **BENCH-6 is unmeasured across two rounds** and is why row 9 is not claimed.

---

## 9. What would change the verdict

### Downward — what would turn ADOPT WITH CONSTRAINTS (row 8) back toward row 6, or to DEFER

1. **A vector that reaches the `after` or `done` selection site from genuinely outside the process** — i.e. without attacker-controlled Python (R10-01 Class A) and without blob-write (Class B). That is the exact boundary the refutation rests on. Such a vector would restore R10-01 toward Blocker and put CV-C45's send-side clause back on duty. The refutation is falsifiable by construction and should be attacked first in round 11.
2. **Evidence that R10-01 Class B is *not* equivalent to blob-write** — e.g. a deployment where the snapshot store is writable but the payload is otherwise constrained (schema-validated, field-whitelisted), such that the `"engine": true` boolean genuinely adds capability the writer did not already hold. Our own envelope is HMAC-tagged, which is why this does not bind us; a consumer without that tag is in a different position.
3. **Coverage or the suite regressing** on a later commit. This round measured it cleanly (3505 passed, 92.78 %); row 2 fires before any adoption row is reached, so a single regression here outranks everything else in this document.
4. **A `raise(delay=)` chain proving shedable-but-fatal on a shape we actually use.** R10-03 is Medium because the idiom is non-idiomatic and `after` measures clean. If a catalogue machine turns out to depend on the delayed-self-raise spelling, R10-03 returns to High and CV-C47 becomes load-bearing rather than precautionary.
5. **A restored deadline silently lost in a real drill.** R10-05's migration cliff is contained by CV-C48, but the containment is *ours* and untested in anger. A failed restore drill would move it to High.
6. **A fourth round of "fixed on one axis only."** Round 10 found zero. That streak breaking would re-open the process question round 9 raised, independently of any single defect.
7. **A 0.8.1 tag cut with `__version__` still reporting `0.8.0`** (§8, item 1).

### Upward — what would turn this into unconstrained ADOPT (row 9)

**Row 9 needs all Blocker and High closed (✅ done), all Medium triaged (✅ done), and *all* benchmark thresholds met (❌).** Concretely, two things stand between us and row 9:

- **BENCH-2**: 443.6 market ev/s against a 2 000 budget — a **~4.5× architectural gap**. It was ~14× at round 9; almost all of that improvement is host contention, not engine change (the *ratios* between policies held steady while the absolute baseline moved ~5×). Closing it means not running per-tick predicates through statecharts at all, which is already our design.
- **BENCH-6**: **unmeasured for two rounds.** Measuring it is cheap (re-scope `bench_c_timers` to stream results instead of buffering, or reduce its two-tier `load_500` structure) and is the single highest-value benchmark action for round 11 — it is the only threshold whose status is *unknown* rather than *known-missed*.

**Row 9 remains out of reach and we still should not plan for it.** The dedicated-loop rule, the ≥99 % pre-filter and the external `MonotonicScheduler` are permanent features of our architecture. **Row 8 was named as the honest ceiling in round 9 and we have now reached it** — the correct next milestone is not row 9, it is discharging Phase 3's own acceptance criteria.

### Re-verification recipe for round 11 (~45 min, priority order)

```
# 1. Attack the refutation that carries the decision
#    R10-01: find a vector that is neither in-process Python nor blob-write
battle-19cb1f1/fuzz/n1_after_forgery.py            # controls V1/B/G MUST stay refused
battle-19cb1f1/persistence/u2_after_forgery.py     # under strict:True + onUnhandled:"error"

# 2. Hold the two closures that unblock Phase 3
issues/verify-main-19cb1f1/203_after_provenance_gate.py    # R9-02 must stay closed
issues/verify-main-19cb1f1/204_statesToInvoke.py           # R9-04 must stay closed
battle-19cb1f1/contracts/.../ld01_always_rollforward.py    # MUST stay 0/6 leaks
gate: verifyM4/verifyM5 `167 rollback_reinvoke_spin`       # MUST stay PASS

# 3. The measurement that is UNKNOWN rather than known-missed
bench_c_timers  -- RE-SCOPED to stream results; BENCH-6 has been unmeasured 2 rounds
bench_e_actors  -- not attempted for 2 rounds
bench_a + bench_h A/B f28719c vs 19cb1f1 on MATCHED host load

# 4. Regression + containment
pytest tests/ --cov=src --cov-report=term          # must stay >= 86% (92.78% here)
gate/run_gate.py                                   # now incl. verify-main-19cb1f1 as verifyM7
tests/xstate_contract/                             # the standing gate, BOTH spellings
```

---

## 10. Next steps — Phase-3 shim retirement, re-gated against this evidence

Shims retire only when the contract suite covers what the shim protected, green on **both service spellings**, for the stated number of nightly cycles.

### Phase 1 — non-order (B10–B15, B17, B19, B20) — **PROCEED, unchanged**

Retire: the `always`-ordering shim (#196), the `children_timeout` wrapper bound as a *mandate* (#194; CV-C44 stays in depth), the one-sided-agreement restore check as the primary gate (#186; CV-C27′ stays in depth), the `on_interpreter_start` snapshot guard as the primary gate (#199; CV-C40 stays in depth). **Precondition:** contract suite green in CI on both spellings for one nightly. **No new blocker from round 10** — B11–B15 report 27/27 invariants and zero library defects on both lanes.

### Phase 2 — control plane (B16, B18) — **STILL BLOCKED ON US, five rounds**

Both remain **LIBRARY-GO** — B16–B20 report **0 new library findings**, 10/10 clean builds, 13/13 sharp edges per lane, clean snapshot/restore on every drive, 5/5 sync parity including the service-call trace. What blocks them is **C-04** and **C-07b**, and round 10 **refuted both as library defects with corrected-usage probes that pass on both engines and both spellings**. There is no longer any ambiguity about whose bug these are. They block on *any* runtime. Add to Phase 2 the two Mediums that surfaced against the same charts: **R10-C5** (B16 re-elevation unaudited) and **R10-C3** (B19 `stale_lockout` contradicts its own invariant INV-B19-b; escapable via `RECONNECTED`, but unauditably, venue-conditionally, and with unbounded deferral accumulation).

### Phase 3 — order path (B1–B9, B18) — **MAY BEGIN**

**The two library gates are closed.** R9-02 → #203 and R9-04 → #204, both verified on both engines and both service kinds (§0, §1). The sync-engine leak that grounded CV-C46 is gone (`167` PASS ×5/5), and CV-C46 retires. **Of Phase 3's four acceptance conditions, (iii) the ≥ 86 % coverage measurement is NOW MET at 92.78 %** — it was the one condition with a library dependency, and it is discharged.

The remaining three are **entirely our engineering work, with no library dependency**:

- **(i)** contract suite green on both spellings for **five consecutive nightlies**;
- **(ii)** CV-C45 (restore clause, widened), CV-C47, CV-C48, CV-C49, CV-C50 and CV-C4x enforced by lint **and** covered by their named tests;
- **(iv)** a **canary**: one low-notional order machine group in production behind the full constraint set for two weeks with zero constraint-test failures.

**Do not retire in this phase:** **CV-C42**, **CV-C23's HMAC clause**, the **wrapper attempt counter** on any `rollback` + `invoke.onDone` state, and the four new constraints — they answer R10-03/04/05/13 and R10-D1, which are Medium and open. **B18's shim retires with Phase 2, not Phase 3**, since C-07b gates it on any runtime.

### E50 backlog

**Close (round-9 residuals now verified fixed upstream):** the guard ticket for **R9-02** (`after` matched on the public class — #203), the guard ticket for **R9-04** (roll-forward `def` invoke submitted — #204), **R9-06** (delayed self-send unshedable — #206, superseded by R10-03), **R9-07** (rollback+`onDone` storm silent — #207), **R9-08** (success-shaped receipt over an empty configuration — #208), **R9-09** on its named shape (#209), **R9-03** (refuted, now withdrawn as FIXED: 915 600/915 600 applied, 0 lost). Also close the **CV-C46** lint ticket (retired), the **CV-C45 send-side** ticket (retired), and re-label the **CV-C32** ticket's justification from R9-04 to R10-D2.

**X01 verdict recorded: ADOPT WITH CONSTRAINTS — decision-table row 8** (up from row 6), pin `== 0.8.1` once tagged / commit `19cb1f1` + sha256 until then, vendored per MUST-08.

**Add:**
- **CV-C47** lint + `test_cv_c47_no_self_delayed_raise` (R10-03)
- **CV-C48** envelope fence + `test_cv_c48_pre_0_8_1_after_record_refused_loudly` (R10-05)
- **CV-C49** snapshot precondition + `test_cv_c49_no_armed_self_delay_at_snapshot` (R10-04)
- **CV-C50** `on_invocation_stranded` + chain-budget sampling, **both lanes** (R10-13)
- **CV-C4x** kill/cancel declared on an ancestor of every invoking state — statically lintable (R10-C4)
- **Self-transition lint**: any self-targeting `onDone`/`on` intended to restart a state must carry `"reenter": true`. The library's validator warns for the `always` case only (R10-02 residual Info).
- Gateway counts call-site `QueueOverflowError` refusals itself (R10-08)
- Wrapper top-level config-key whitelist (R10-07, carried)
- `gate/run_gate.py`: add **`verifyM7`** for `issues/verify-main-19cb1f1/`; move `BASELINE_COMMIT` to `19cb1f1`; retire `201_lap_parity_stated_exactly.py`
- Retire the five stale round-8 fixtures; fix `R8-05_doneevent_forgery.py` to treat `UnknownEventError` as success; convert `CV-F28-01`/`CV-F28-02` into regression pins
- Re-scope `bench_c_timers` to stream results — **BENCH-6 unmeasured two rounds running**
- Shim-retirement tickets, one per phase, with the preconditions above as acceptance criteria
- Upstream chores: bump `__version__`; fix the `+2`/`+3` changelog contradiction; narrow or fix the #209 lap-parity claim; name #206 as a behaviour break; replace the inert `nested_invoke` pin

**Keep open (ours, and now unambiguously the critical path):** **C-04** and **C-07b** — the only Blockers of any kind left in this study, both refuted as library defects this round with corrected charts proven to pass, and both open five rounds. Ten rounds of library verification have arrived at a state where the binding constraint on our order path is **our own catalogue, and nothing else.** That should be the next thing worked.
