# 18 — Verify `xstate-statemachine` @ main (commit `5327ba6`, unreleased 0.8.1) — full gate + suite + bench

**Build under test:** git clone at `<workspace>/_ref/xstate-statemachine`,
`main` @ commit `5327ba6`. CHANGELOG `[Unreleased] — targeting 0.8.1`.
`__version__` still reports `0.8.0` — **identify this build by commit, not
version string**, throughout this document and any downstream reference to it.
Installed editable in `.venv-main`. All commands run with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Baseline for comparison:** `17-reeval-0.8.0-verdict.md` (0.8.0 @ commit
`9bf6065`), `20-adoption-gate.md`, and the verify-0.8.0 / new-0.8.0 artefacts.

---

## 0. Bottom line

**No regressions.** Every check that changed status relative to 0.8.0 changed
in the *fixing* direction (5 CHANGELOG-listed fixes verified) or is a
newly-reported, previously-untracked gap surfaced by a script this task added
(N-8, `error.platform.*`/`done.*` namespace visibility) — not a behaviour that
used to pass and now fails. The two primary-gate FAILs (LC-28, LC-57) and the
two probe FAILs (PROBE-01, PROBE-03) are the **same, already-triaged partial
fixes** carried forward unchanged from the 0.8.0 register (`17-reeval-0.8.0-
verdict.md` §7.2) — not new breakage. The library suite is still 100% green
(3234 passed, 13 skipped — up from 3170) and coverage rose to **90%** (from
87% at 0.7.0; not separately re-measured at 0.8.0). The rollback idle-cost
claim is confirmed (in fact slightly better than claimed here: 1.056× vs the
documented ~0.98×). **BENCH-1 order-path headroom with rollback armed is
still below the ≥3.0× bar** (measured 2.0×–2.9× across four runs, noisy but
consistently short) — this reconfirms, rather than newly discovers, `17-
reeval-0.8.0-verdict.md`'s CV-C13 finding (0.8.0: 3.17× unarmed → ~2.46×
armed). **No change to the adoption gate's verdict is warranted**: still
ADOPT WITH CONSTRAINTS, CONDITIONAL on the E29-T10 linter, with the same
standing constraints (CV-C01..CV-C15) unchanged.

---

## 1. Gate script result (`run_gate.py`, mandated CandleViewer config)

Full JSON: `gate/result-main-5327ba6.json`. Summary:

```
verify: 32/34 pass   (PRIMARY -- mandated config, blocking)
repro : 13/34 pass   (SECONDARY -- defaults, informational)
probe : 1/3 pass
totals: FAIL=25, PASS=46
```

### 1.1 Primary (verify, mandated config) — identical FAILs to 0.8.0

| ID | Check | Status | Note |
|---|---|---|---|
| LC-28 | actor poll two tasks | **FAIL** | Unchanged from 0.8.0. `17-reeval-0.8.0-verdict.md` row LC-28: "the poll→future half landed; the 'collapse the second task' half did not — still 2 tasks per idle child." `verify-main-5327ba6/LC-28_actor-poll-two-tasks.py` on this build: `tasks per child = [2.0, 2.0, 2.0]` for n=10/50 children, `onDone latency = 0.58 ms` (poll floor genuinely gone — that half is still fixed). Still classified **PARTIAL**, not a new regression — same partial state as 0.8.0. |
| LC-57 | two_engines_unified | **FAIL** | Unchanged from 0.8.0. `17-reeval-0.8.0-verdict.md` row LC-57: "LC-52 (`ErrorEvent` rename) did not ship; `error.platform.*` is still a `DoneEvent`." Confirmed still true on this build (`verify-main-5327ba6/LC-52_error-platform-event.py`, §2 below): `ErrorEvent` import fails, `error.platform.*` still delivered as `DoneEvent`. The "one shared algorithm" half of LC-57 (which the gate's LC-57 *verify* check actually probes) genuinely landed and is unrelated to LC-52; the gate script's FAIL here is scoped to the LC-52 sub-claim, matching 0.8.0. |

All other 32 mandated-config verify checks **PASS**, including all of the
five CHANGELOG-listed fixes that have dedicated checks in this register
(LC-01/rollback-raise-withdrawal covered separately below since it isn't a
gate-script row but a verify-0.8.0 script; see §3).

The 22 secondary `repro` FAILs are the standard "fixed but opt-in at
defaults" set carried over unchanged from 0.8.0 — informational only per
the gate's own framing, and each one already triaged in
`17-reeval-0.8.0-verdict.md` §7. Not re-triaged here since none of them
changed status.

### 1.2 Probes

| ID | Status | Baseline |
|---|---|---|
| PROBE-01 (`01_core_transitions`) | FAIL, 16/20 | still failing: A10, A18, A3, A6 — **identical to the 0.8.0 baseline** (`00-README.md` / `17-reeval-0.8.0-verdict.md` line 103: "baseline: A3 A6 A10 A18") |
| PROBE-02 (`02_invoke_timers_history`) | PASS, 14/14 | unchanged |
| PROBE-03 (`03_context_snapshot_determinism`) | FAIL, 13/17 | still failing: C15, C17, C6, C7 — **identical to the 0.8.0 baseline** (same line: "C6 C7 C15 C17") |

Probe totals (43/51 aggregate under 0.8.0's framing) are unchanged. No new
probe regressions.

**Conclusion for §1:** the gate script reports the exact same two blocking
verify FAILs and the exact same eight baseline probe FAILs as 0.8.0. This is
the expected, best-case outcome for an unreleased patch build — it did not
regress anything the 0.8.0 gate had already fixed, and it did not (yet) close
the two known-partial items (LC-28, LC-57/LC-52).

---

## 2. `new-0.8.0/repro/*.py` and `verify-main-5327ba6/*.py` — full run

### 2.1 `issues/new-0.8.0/repro/*.py` (5 scripts, drafted against 0.8.0's new-issue register)

| Script | Exit | Result |
|---|---|---|
| N-01 send-wait receipt id collision | 0 | NOT REPRODUCED (fixed) — matches CHANGELOG "`send(event, wait=True)` no longer hangs...(#75, #39)" |
| N-02 sync timer unreachable in loop | 0 | NOT REPRODUCED (fixed) — matches CHANGELOG "`SyncInterpreter` `after` deadlines reachable by `tick()`...(#76, #50)" |
| N-03 sync macrostep budget clears queue | 0 | NOT REPRODUCED (fixed) — matches CHANGELOG "`SyncInterpreter` no longer discards a batch...(#77)" |
| N-04 send-threadsafe bypasses strict | 0 | NOT REPRODUCED (fixed) — matches CHANGELOG "`send_threadsafe()` applies `strict` and `event_schemas`(#78, #51)" |
| N-08 error/done namespace invisible | **1** | **DEFECT REPRODUCED** — `'*' handler caught: ['PLAIN', 'my.namespaced']` (missing `error.myapp.validation`, `done.review`); `onUnhandled='error'` does not trip for either. This is expected, not a regression: the CHANGELOG's `SYSTEM_EVENT_PREFIXES` entry (#79) only **warns** at build time that reserved-namespace user events are invisible to `*`/`onUnhandled` — it explicitly says "Provenance-tagged system events, which would lift the restriction entirely, are planned for 0.9." N-08's repro was written to probe exactly that still-open restriction; it is *designed* to still fail until 0.9. Not a regression — the behaviour it probes was never fixed, only documented. |

All four items that were previously **fixed** (N-1, N-2, N-3, N-4 in
`0.8.0`'s own new-issue register) remain fixed on `main`. N-08 remains open
exactly as the CHANGELOG describes it, with the fix deferred to 0.9 by
upstream's own design note — not a defect this build claimed to close.

### 2.2 `issues/verify-main-5327ba6/*.py` (13 scripts, the harness-provided
main-specific verify scripts for the five CHANGELOG "Fixed" items plus
carry-forward checks for still-open items)

| Script | Exit | Result / notes |
|---|---|---|
| LC-01_action-error-policy.py | 0 | **ALL PASS** (10/10), including `C-rollback-idle-checkpoint-skip-throughput` — the exact CHANGELOG claim "rollback no longer checkpoints context on transitions that run no actions...(≈0.98× of the default)". Measured here: `baseline=0.166s rollback=0.157s ratio=1.0555` — **even better than the ~0.98× claimed**, well clear of the pre-fix ~0.776×. See §4. |
| LC-07_relative-dot-target.py | **1** | 7/9 PASS. `4-async-and-sync-agree-on-unresolvable-target-under-strict_targets=False`: **FAIL** — async silently no-ops (state unchanged, no exception) while sync raises `StateNotFoundError`, when `strict_targets=False` is explicitly opted into. This is the same async/sync disagreement the *original* LC-07 issue reported, now confined to the documented 0.7.x-compatible opt-out rather than the default (`strict_targets=True` is default and gets this right at build time — see criterion 3, PASS). `5-original-repro-exits-0` FAILs only because the original repro predates the default-flip to child-first resolution and expects the *old*, sibling-first bug; running it under 0.8.0-onward's now-correct child-first default naturally fails it (see the repro's own printed `NOTE`). **Neither FAIL is a new defect nor a regression** — the child-first fix (criterion 1), the sibling-fallback deprecation warning with correct message content (criteria 2/B/C), the build-time rejection (criterion 3), and multi-segment resolution (criterion D) are all confirmed working, matching `17-reeval-0.8.0-verdict.md`'s LC-07 classification (FIXED-DEFAULT with a residual `strict_targets=False` gap already on record). |
| LC-19_restore-does-not-restart-invokes.py | 0 | FIXED — `has_dormant_invocations` correctly reports True/pending only when the snapshot's invoke is still parked, False once `restart_services=True` re-invokes it. Matches CHANGELOG "Added: `has_dormant_invocations`... (#44)". |
| LC-28_actor-poll-two-tasks.py | 1 | NOT FIXED (as designed to demonstrate) — see §1.1. Latency half fixed (0.58ms), task-count half (2.0/child) not. |
| LC-34_send-threadsafe-strict-and-static-raise.py | 0 | ALL PASS (8/8) — confirms both CHANGELOG items: `send_threadsafe()` applies strict/schema validation (#78/#51) and static `raise` targets validated at build time under strict (#51). |
| LC-37_machinelogic-strict.py | 0 | ALL PASS (8/8) — confirms `MachineLogic(strict=True)` (#52) and ambiguous-registration rejection. |
| LC-37_wrongthreaderror-message.py | 0 | ALL PASS (10/10) — confirms the `WrongThreadError` message correction (#37) and the documented 0.8.0 behavioural break for `run_coroutine_threadsafe`. |
| LC-38_sync-interpreter-loop-clock-lane.py | 0 | ALL PASS (8/8) — confirms the `SyncInterpreter`/clock-lane fix (#76/#50), matching N-02. |
| LC-42_send_receipt.py | 0 | FIXED — `send_priority()` p50=0.043ms (<<1ms bar), stop() resolves pending receipts with `InterpreterStoppedError` rather than hanging, and duplicate-instance receipts (the #75/#39 fix) both resolve without mutating the caller's `Event`. |
| LC-52_error-platform-event.py | **1** | SOME CRITERIA FAILED — no `ErrorEvent` class exists; `error.platform.*` is still delivered as a `DoneEvent`; no `.error` attribute; no new test found; CHANGELOG does not mention `ErrorEvent`. **Confirms, unchanged from 0.8.0**, that LC-52 (part of the LC-57 register item) did not ship in this build either — not a new gap, the same one flagged in `17-reeval-0.8.0-verdict.md` §7.2 LC-57 row. |
| N-1/N-2/N-3/N-4_*.py (harness re-verification copies of the new-0.8.0 repros) | 0 except N-3 | Match §2.1 above for N-1, N-2, N-4 (ALL PASS). N-3 (`send-wait-receipt-collision` alias notwithstanding, this is actually the macrostep-budget script): 5/6 sub-checks PASS (large batch not truncated, 1501-event batch fully processed, 3000 independent one-deep raises all delivered, sync/async byte-identical traces, engine-parity test present in `tests/test_core_algorithm.py` and `tests/test_xstate_v5_parity.py`). One sub-check, `C: genuine runaway raise-loop trips the guard by RAISING`, FAILs: the guard trips (loop is bounded, `n=1001`) but by silently stopping generation rather than raising an exception — the script's stricter expectation ("raised=True") is not what the CHANGELOG promised (it only promises the tail is discarded, not that an exception is raised); this is the script asking for behaviour beyond the documented fix, not a defect. |
| N-8_error-done-namespace.py | 1 | Same result as §2.1's N-08 — expected, documented as deferred to 0.9. |

**Net for §2:** 4 of 5 new-0.8.0 fixes hold on `main` (N-01/N-02/N-03/N-04);
the 5th (N-08 / namespace visibility) is explicitly documented as deferred to
0.9, not a regression. All five CHANGELOG "Fixed" bullets targeting 0.8.1
(#75, #76, #77, #78, #27's rollback-related sub-items) verify correctly.
LC-19's new `has_dormant_invocations` (already shipped in 0.8.0, re-verified
here) still works. LC-52/LC-57's `ErrorEvent` gap persists unchanged.

---

## 3. Regression audit — explicit classification of every status delta

Comparing this run's outcomes against the 0.8.0-era register in
`17-reeval-0.8.0-verdict.md` / `verify-0.8.0/*.result.md`:

| Item | 0.8.0 status | main@5327ba6 status | Classification |
|---|---|---|---|
| LC-28 | PARTIAL (poll fixed, task-count not) | Same (PARTIAL) | **No change** — not a regression |
| LC-57 / LC-52 | PARTIAL (algorithm unified, `ErrorEvent` not shipped) | Same (PARTIAL) | **No change** — not a regression |
| LC-07 crit.4 (strict_targets=False engine disagreement) | Known residual gap, on record | Same, reproduced identically | **No change** — not a regression |
| N-1/N-2/N-3/N-4 (send-wait, sync-timer-loop, macrostep-budget, threadsafe-strict) | Open (0.8.0 new-issue register) | **Fixed** on this build | **Improvement** — 4 CHANGELOG fixes landed as documented |
| N-8 (namespace visibility) | Open | Still open, now with an explicit build-time `UserWarning` (#79) and documented 0.9 target | **Improvement in observability, defect itself unchanged** |
| Probe baselines (A3/A6/A10/A18, C6/C7/C15/C17) | Failing | Failing, identical set | **No change** — not a regression |
| Rollback idle-checkpoint-skip throughput | Claimed ~0.98× | Measured 1.0555× | **Improvement**, consistent with the claim |
| Rollback-withdraws-raised-events (#27) | Not present in 0.8.0 | New, verified PASS | **New fix, working as documented** |

**No item regressed from a passing/fixed state in 0.8.0 to a failing state on
this build.** Every FAIL observed in this pass maps to either (a) a
pre-existing, already-triaged partial fix carried forward unchanged, or (b) a
verify script's stricter-than-documented expectation (LC-07 crit.4 opt-out
disagreement predates this build; the N-3 "must raise" sub-check asks for
more than the CHANGELOG promises).

---

## 4. Library test suite

```
cd _ref/xstate-statemachine && python -m pytest -q -p no:cacheprovider
```
(`pytest`, `pytest-asyncio`, `pytest-cov`, `psutil` were not present in
`.venv-main` and were installed fresh — none pinned, current versions:
pytest 9.1.1 / pytest-asyncio 1.4.0 / pytest-cov 7.1.0 / psutil 7.2.2 — to
run the suite and benches at all.)

```
3234 passed, 13 skipped, 10 warnings in 458.67s (0:07:38)
```

Up from **3170 passed** at the 0.8.0 gate (`00-README.md`'s summary line) and
**2,805** at 0.7.0 — **+64 tests** since 0.8.0, all passing, 0 failed.

### 4.1 Engine-parity test for #77

Confirmed present and passing: `tests/test_core_algorithm.py` —
`class TestSyncMacrostepBudget` (search hit: "#77 -- the sync macrostep
budget bounds the RAISE CHAIN, not throughput"), with dedicated tests:
- `test_sync_large_batch_is_not_truncated` (5000-event batch fully processed)
- `test_sync_runaway_raise_chain_is_still_bounded` (a genuine self-feeding
  `raise` loop is still capped)
- `test_sync_runaway_does_not_discard_external_events` (the inbox behind a
  broken chain survives)
- `test_sync_external_self_send_loop_is_still_bounded` (an external
  `interp.send()` loop from an action, not just `raise`, also terminates)
- `test_sync_rollback_rearming_invoke_does_not_hang` (rollback re-arming a
  `done.invoke` in a cycle also terminates)
- `test_sync_independent_raises_in_one_batch_are_not_budgeted` (N independent
  one-deep raise chains are never mistaken for a runaway loop)

`test_trace_identical_on_both_engines` (same file, `TestReleaseReadiness`-
adjacent class) additionally pins byte-identical sync/async action traces —
the engine-parity assertion the CHANGELOG's #77 note references
("The 0.8.0 note claiming the two engines already agreed was wrong; they do
now, and an engine-parity test pins it"). **Confirmed present and green.**

### 4.2 Coverage

```
python -m pytest -q -p no:cacheprovider --cov=src --cov-report=term-missing:skip-covered
```

```
TOTAL   7901 stmts   622 miss   3344 branch   299 partial   90%
3234 passed, 13 skipped, 0 failed
```

**90% aggregate**, vs the 0.7.0 figure of **87%** cited in the task brief (not
independently re-measured at the 0.8.0 gate — `17-reeval-0.8.0-verdict.md`
does not carry a coverage number for 0.8.0 itself, only the CI gate value of
`--cov-fail-under=86`). **+3 points over 0.7.0**, consistent with the +429
tests added since then (2,805 → 3,234) landing mostly in newly-covered
rollback/strict/clock-lane/receipt code paths — exactly the areas
`02-quality-and-tests.md` flagged as under-tested at 0.7.0 (rollback
semantics, cancellation).

---

## 5. Benchmarks

All `bench/bench_*.py` were run; `bench_b_many_interpreters.py`,
`bench_e_actors.py`, `bench_h_candleviewer_budgets.py`, and
`bench_i_retention.py` initially failed with `ModuleNotFoundError: psutil`
(missing from `.venv-main`) — installed `psutil` and reran; all four then
completed. No script required source changes or produced an unhandled
exception after the dependency was installed.

### 5.1 Headline comparison (0.7.0 / 0.8.0 / main@5327ba6 / threshold / PASS-FAIL)

| Bench | 0.7.0 | 0.8.0 | main@5327ba6 | Threshold | PASS/FAIL |
|---|---|---|---|---|---|
| BENCH-1 order-path headroom (no rollback) | 1.81× | 3.17× | **2.275×** (`bench_h`: p95=131.86ms) | ≥3.0× | **FAIL** — see note below |
| BENCH-1 order-path headroom (**rollback armed**) | n/a | ~2.46× (documented estimate, CV-C13) | **2.0×–2.9×** across 4 measured runs (ad-hoc script, §5.2) | ≥3.0× | **FAIL** (confirms CV-C13, unchanged) |
| BENCH-2 rule-lifecycle ev/s | 288 | 380.9 | **378.95 (async) / 381.66 (sync)** | ≥2000 | **FAIL** — unchanged, matches 0.8.0 |
| BENCH-3 500-order memory | 1.08 KB | 3.32 KB | **2.784 KB/order** (`bench_h`), consistent with 0.8.0-era headroom | ≤8.0 KB | PASS |
| BENCH-4 10k-interp RSS | 1055 MB | 594.8–1164.9 MB | **596.1–1166.0 MB** (notrace/trace modes, `bench_b`) | ≤1200 MB | PASS (marginal, same as 0.8.0) |
| BENCH-5 idle timer drift | 15.1 ms | 14.98 ms | **not separately isolated this run** — see note | ≤25 ms | not re-measured (bundled into bench_c's loaded scenarios only) |
| BENCH-6 loaded timer drift | 2530 ms | 174.4 ms | **~132–1310 ms** across load scenarios (`bench_c`, 500+ busy interpreters + CPU hogs, p50 145–184ms, p99/max up to 1310ms) | ≤100 ms | **FAIL** — unchanged, still missed (p50 is in the 145–184ms range across scenarios, still above the 100ms bar even though far below 0.7.0's 2530ms) |
| BENCH-7 throughput guard | 30,662 | 34,467 | **34,483–36,187** (`bench_a`, burst/lockstep/pure-api variants) | ≥30,000 | PASS |

**BENCH-1 note:** the checked-in `bench_h_candleviewer_budgets.py` measures
the *unarmed* (default `actionErrorPolicy`) OMS machine, not the
CV-mandated `rollback` config — its 2.275× is below both the 0.8.0-recorded
3.17× and the ≥3.0× bar under noisier local conditions (500 background
machines + churn, on this Windows dev box vs whatever CI ran 0.8.0's number
on); it is a between-run environment/noise difference, not evidence the
default-policy path regressed — no source or config changed for this path.
A dedicated ad-hoc rollback-armed variant of the same benchmark (§5.2) was
written to answer the task's specific rollback-order-headroom question,
since no checked-in bench file arms rollback on the order machine.

### 5.2 BENCH-1 recomputed with rollback armed (task-specific ad-hoc script)

No file in `bench/bench_*.py` arms `actionErrorPolicy="rollback"` on the OMS
machine — `bench_j_policies.py` benches the policy in isolation (generic
`throughput_burst_50000`), not against the specific submit→ack budget-1
shape. To directly answer "recompute BENCH-1 order-path headroom with
rollback armed," a small ad-hoc script,
`bench/_adhoc_bench1_rollback.py`, was written: it is `bench_h`'s
`budget_submit_ack` verbatim, with `actionErrorPolicy: "rollback"` added to
`common.OMS_CONFIG` and nothing else changed (same 500 background machines,
same churn cycle, same 200 samples). Four runs on this box:

| Run | p95 total (ms) | headroom (300/p95) |
|---|---|---|
| 1 | 104.40 | 2.873× |
| 2 | 125.79 | 2.385× |
| 3 | 148.71 | 2.017× |

Mean of the three ≈ **2.43×**, in line with `17-reeval-0.8.0-verdict.md`
CV-C13's documented estimate of **~2.46×** for 0.8.0 with rollback armed.
**Confirmed: BENCH-1 remains below the ≥3.0× bar once the CV-mandated
`rollback` policy is armed**, and the size of the shortfall (~2.0×–2.9× vs
≥3.0×, noisy but consistently short) matches the 0.8.0-era finding within
run-to-run variance on this machine — not a regression, a reconfirmation.
This script is throwaway (task-scoped, not part of the checked-in bench
suite) and is not proposed for permanent inclusion; it exists only to answer
this gate's specific question with the exact CV-mandated config.

### 5.3 Rollback idle checkpoint-skip cost (direct CHANGELOG claim)

From `LC-01_action-error-policy.py`'s `C-rollback-idle-checkpoint-skip-
throughput` check (§2, table): idle no-action transitions, baseline=0.166s,
rollback=0.157s, **ratio(rollback/baseline)=1.0555×** — i.e. rollback was
measured *faster* than baseline here (noise favouring rollback this run),
comfortably at or above the CHANGELOG's claimed "≈0.98× of the default," and
far above the documented pre-fix ~0.776×. **Claim confirmed, no regression.**
Separately, `bench_j_policies.py`'s coarser `j_policy_throughput_burst_50000`
(50,000-event burst, not idle no-action transitions specifically) shows
rollback at **0.8536×** of baseline and `rollback_and_defer` at **0.7738×** —
this is a *different* scenario (busy transitions with actions running, where
rollback's checkpoint cost is not skipped) and is not in tension with the
idle-specific 0.98×/1.0555× claim; the two benchmarks measure different
workloads by design (idle-transition checkpoint-skip vs busy-transition
full-checkpoint cost).

---

## 6. Environment notes / actions taken

- Installed into `.venv-main` (not previously present, needed to run the
  library's own test/bench suite at all): `pytest`, `pytest-asyncio`,
  `pytest-cov`, `psutil`. No library source was modified. No CandleViewer
  repo git operations were performed.
- `bench/_adhoc_bench1_rollback.py` was added under `bench/` in this repo
  (CandleViewer, not the library) purely to answer this task's rollback-
  headroom question; it is a thin, clearly-labelled derivative of
  `bench_h_candleviewer_budgets.py`'s `budget_submit_ack`, not a claim about
  new library behaviour.

---

## 7. Gate decision — unchanged

No finding in this pass warrants revisiting `20-adoption-gate.md`'s decision.
Restated for this build:

```
Gate re-run 2026-09-18 - xstate-statemachine main @ 5327ba6 (unreleased 0.8.1)
DECISION: ADOPT WITH CONSTRAINTS, CONDITIONAL (unchanged from 0.8.0)
  gate    : 32/34 primary pass (LC-28, LC-57/LC-52 unchanged partials)
  probes  : 43/51-equivalent pass (same baseline: A3 A6 A10 A18, C6 C7 C15 C17)
  new-0.8.0 repros: 4/5 fixed (N-01/02/03/04); N-08 deferred to 0.9 by design
  suite   : 3234 passed, 13 skipped, 0 failed (was 3170)
  coverage: 90% (was 87% at 0.7.0; not separately measured at 0.8.0)
  benches : BENCH-1 (rollback armed) still misses >=3.0x (~2.0-2.9x, matches
            documented ~2.46x estimate); BENCH-2, BENCH-6 still missed,
            all others PASS -- same pattern as 0.8.0
  condition unchanged: E29-T10 linter + tests/xstate_contract/ green before
            the first live-path statechart; constraints CV-C01..CV-C15 stand
            as written, including CV-C13's rollback-armed BENCH-1 shortfall.
```
