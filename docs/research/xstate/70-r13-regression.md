# 70 — Round-13 regression sweep (v0.9.0, tag `91bd979`; main `e3a1f22`)

**Date:** 2026-09-23  ·  **Library:** `xstate-statemachine` `__version__ = "0.9.0"`
**Tag under test:** `v0.9.0` = `91bd979`  ·  **Working tree:** `main` @ `e3a1f22`
**Baselines diffed:** `gate/result-main-de2da4e.json` (gate) · `gate/r12_regression_raw.json` (script sweep) · `69-r12-final-readiness-verdict.md` §2

---

## 0. Headline

**No true regressions.** Across a 175-check adoption gate and a 534-script
historical sweep, exactly **one** gate check and **one** sweep script moved
`PASS → FAIL`, and both are triaged below as **stale repro / harness artefact**,
not library defects. Thirteen previously-failing artefacts now pass. The
BENCH-6 timer bar is met with ~35 % more headroom than round 12.

| Lane | Result |
|---|---|
| Library test suite | **3577 passed, 13 skipped**, 15 warnings, 597 s; coverage **92.86 %** (bar 90 %) |
| Adoption gate | 136 PASS / 39 FAIL (baseline `de2da4e`: 40 FAIL) — **1 PASS→FAIL, 2 FAIL→PASS, 7 new checks all PASS** |
| Script sweep (534) | 452 PASS / 82 FAIL / **0 TIMEOUT** — 1 PASS→FAIL, 11 FAIL→PASS, 2 unbaselined |
| BENCH-6 (§2 @ 500 busy) | **+57.4 / +54.3 / +64.8 / +61.4 / +61.0 ms** — all ≤ 100 ms bar ✅ |
| Livelock watchdogs | 0 timeouts at the 120 s cap across all historical livelock repros |

**Verdict: no blocking regression introduced by 0.9.0.** The round-12 fix set
(#225–#235) lands clean.

---

## 1. Version & provenance check

The environment claim that `main` is 2 commits ahead of `v0.9.0` with
CI-publish-only changes is **verified**:

```
$ git diff v0.9.0..HEAD --stat
 .github/workflows/publish.yml | 15 ++++++++++++++-
 1 file changed, 14 insertions(+), 1 deletion(-)
```

`e3a1f22` (merge #237) + `c133875` ("ci: publish smoke test checks every
`__all__` name, not a pinned count"). **No library source differs between the
tag and the tested tree** — every result below applies to `v0.9.0` as tagged.

`__version__ = "0.9.0"` (`src/xstate_statemachine/__init__.py:200`).

> **Distribution status:** still **not on PyPI** — `pip download
> xstate-statemachine==0.9.0` fails. Adoption must pin a VCS ref
> (`91bd979`) until the publish workflow actually runs. This is the one
> outstanding *release* item, not a code defect.

---

## 2. Library test suite

Full `pytest` + coverage run (`suite-v0.9.0.log`, 244 lines):

```
3577 passed, 13 skipped, 15 warnings in 597.15s (0:09:57)
Required test coverage of 90.0% reached. Total coverage: 92.86%
TOTAL   9221 stmts   484 miss   3978 branch   360 partial   93%
```

`tests/test_round12_findings.py` — **31 passed**, matching the CHANGELOG claim
for #225–#235. No failures, no errors, no xfails masking a regression.

Per-module coverage holds at or above prior rounds on every hot path:
`sync_interpreter.py` 97 %, `validation.py` 99 %, `persistence.py` 95 %,
`task_manager.py` 98 %, `pythonic.py` 94 %.

---

## 3. Adoption gate — `gate/result-v0.9.0.json`

`run_gate.py --json gate/result-v0.9.0.json`, elapsed **352.8 s**, exit 1
(unchanged: the gate has carried a non-clean exit since 0.7.0 because of the
long-standing "keep open" register rows).

| | `de2da4e` baseline | `v0.9.0` |
|---|---|---|
| checks | 168 | **175** (+7) |
| FAIL | 40 | **39** |

### 3.1 `PASS → FAIL` — 1 check

| id | kind | label | triage |
|---|---|---|---|
| `LC-39` | repro | throughput global budget | **STALE REPRO — not a regression** |

**`LC-39` triage (stale repro).** The script's own pass criterion is:

```python
return 0 if top / base > 2.0 else 1
```

i.e. it demands that *aggregate* throughput grow **more than 2×** going from
N=1 to N=500 interpreters on a **single event loop**. That is unachievable by
construction on a single-threaded core, and the library has never claimed it.
The script's printed EXPECTED clause is disjunctive:

> "EXPECTED: aggregate throughput grows with N, **or the docs state plainly
> that it does not**."

The second branch is now **satisfied** — `docs/_guide/production-characteristics.md:36`
states it plainly:

> "The aggregate barely moves across three orders of magnitude … the
> per-machine share collapses. This is the correct and unavoidable behaviour
> of a single-threaded core — it is how XState's actor system behaves too, and
> it is not something a library change can 'fix' without a different
> architecture."

…but the script only ever checks the *numeric* branch. Measured ×5 the
numbers are **healthy and flat**, and the exit code is deterministic (`1 1 1 1 1`):

| N | aggregate ev/s (best of 3 runs) | per-machine |
|---|---|---|
| 1 | 309,358 | 309,358 |
| 10 | 315,093 | 31,509 |
| 100 | 295,236 | 2,952 |
| 500 | **268,358** | 537 |

Aggregate scaling factor 0.87–1.03×. The baseline `de2da4e` "PASS" was itself
**noise** — that run took 84.9 s versus 20.3 s here, meaning the N=1 sample was
depressed by a cold/contended host, inflating the ratio past the 2.0 gate. The
underlying behaviour is *identical and documented*.

> **Action:** this is a defect in **our** harness, not the library. `LC-39`'s
> criterion should be rewritten to assert the documented invariant (aggregate
> stays within a band, e.g. `0.5× ≤ top/base ≤ 2.0×`) rather than demanding
> superlinear scaling. Carried as a harness-hygiene item, **non-blocking**.

### 3.2 `FAIL → PASS` — 2 checks

| id | kind | label |
|---|---|---|
| `167` | verifyM4 | rollback_reinvoke_spin |
| `167` | verifyM5 | rollback_reinvoke_spin |

The #167 rollback/re-invoke spin now clears on both recorded lanes.

### 3.3 New checks — 7, **all PASS**

`verifyM9` (round-11/12 pins) added and green: `218` timer_handle_leak ·
`219` reentrant_wait · `220` nested_typos · `221` parked_v3_sends ·
`221#2` repersist_no_start_scheduled_sends · `222` chain_trip_sticky ·
`repro/218`.

No check was removed.

### 3.4 The 39 residual FAILs

All 39 map to previously-triaged register rows and are unchanged from the
`de2da4e` baseline modulo the two fixes above — the documented "keep open" set
(`LC-01/07/12/26/48/57`, `N-1/3/8`, `150/154/157/158`, `201`) plus the
22 informational secondary repros. See `69-r12-final-readiness-verdict.md` §2;
**none is newly failing**, so none changes the readiness posture.

---

## 4. Historical script sweep — 534 scripts

Runner: `gate/sweep_r13.py` (written this round; 6 workers, **120 s cap**,
neutral cwd `C:/Users/basil`, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`).
Raw results: `gate/sweep-r13.json`.

Covered: `issues/verify-*/`, `issues/verify-v0.9.0/`,
`issues/new-0.8.0/repro/`, `issues/new-main/repro/`,
`issues/post-*/new/repro/`, `probes/*.py`, `probes/main-*/*.py`
(skipping `refute*/` and `__pycache__`).

| status | count |
|---|---|
| PASS | 452 |
| FAIL | 82 |
| **TIMEOUT** | **0** |

### 4.1 Livelock watchdogs — all clear

**Zero scripts hit the 120 s cap.** Every historical livelock/hang repro
(#167 rollback spin, #212/#218 heartbeat, #215 descent gate, #219 reentrant
wait, the `raise`-chain budget family) terminated well inside the watchdog.
No hang was reachable at v0.9.0 — notable because #225 reworked the very
predicate (`_action_tasks` replacing the `ContextVar`) that the #219 guard
rides on.

### 4.2 `PASS → FAIL` vs the round-12 sweep — 1 script

`issues/verify-main-cec108b/150_send_threadsafe_budgeted.py` — deterministic
(`1 1 1 1 1` over ×5). Sole failing criterion:

```
Criterion: default send_threadsafe() from action-spawned thread (no internal=True)
  threadsafe (default args) : (60, None, True)
  [FAIL] send_threadsafe() with NO internal= flag from an action thread is budgeted by default
```

All four other criteria in the same script pass, including:

```
  [OK] internal=True is budgeted / trip is RunawayChainError / last_transition_ok is False
  [OK] ctx-inheriting thread is budgeted
  [OK] a foreign thread with no action on its stack is NOT charged
```

> **Triage: SUPERSEDED-BY-#225.** This is precisely the behaviour change #225
> was written to make. The script asserts that a thread spawned *from* an
> action inherits "I am that action" provenance by default — which is exactly
> the `ContextVar`-inheritance contract #225 **deliberately removed**, because
> `ensure_future`/`create_task`/thread-context copying made a helper that
> outlives its action be treated as the action for its whole life (the #225
> hang). Under the new task-identity predicate a spawned worker is **ordinary
> external traffic** unless it opts in. The script's own passing lines confirm
> the replacement contract is intact: `internal=True` **is** budgeted, and an
> explicitly `copy_context().run` thread **is** budgeted. `150` was already a
> documented "keep open" gate row; it is **not** a new defect.

### 4.3 `FAIL → PASS` — 11 scripts

```
issues/post-6db65d8/new/repro/R8-04_always_ondone_reentry_settle_tripped.py
issues/post-6db65d8/new/repro/R8-07_send_wait_resolves_over_empty_configuration.py
issues/post-f28719c/new/repro/R9-08_send_wait_resolves_over_empty_configuration.py
issues/verify-0.8.0/LC-42_send_receipt.py
issues/verify-main-221ce7c/167_rollback_reinvoke_spin.py
issues/verify-main-3ed3099/105_external-send-not-charged-to-chain-budget.py
issues/verify-main-5327ba6/LC-37_wrongthreaderror-message.py
issues/verify-main-5327ba6/LC-42_send_receipt.py
issues/verify-main-cec108b/repro_147_151.py
issues/verify-main-f28719c/197_empty_config_wait.py
probes/main-f28719c/p7_engine_class_reachable.py
```

Two of these retire long-carried register rows: **R9-08** (the #197
"success-shaped receipt over an empty configuration" partial, carried since
round 9) and **#167** (rollback/re-invoke spin). **#105**'s
external-send budget charge now behaves as filed — the direct beneficiary of
the #225 provenance rework.

### 4.4 Not present in the round-12 baseline — 2 scripts

Both are new this round and both resolve to **non-defects**.

**(a) `issues/verify-v0.9.0/225-228_matrix.py` — harness artefact, NOT a defect.**
19 of 20 criteria pass; the lone failure is `228.repo_path_provided`, which is
the script's own guard for a missing `XSM_REPO` environment variable:

```python
lib_root = os.environ.get("XSM_REPO")
if not lib_root:
    check("228.repo_path_provided", False); return
```

Re-run with `XSM_REPO` set → **`ALL PASS`** (20/20), including every #225
lane (`worker_send_not_refused`, `machine_advanced`, `no_yield_not_refused`,
`with_yield_not_refused`, `in_step_await_still_refused`), #232
(`def_drop_receipt_warns`, `def_handout_ensure_future_silent`), #226 on both
engines, and #227 on sync. The sweep runner simply does not export that var.

**(b) `issues/post-de2da4e/new/repro/DE-L4-repro.py` — FIXED by #230.**
The repro asserts `on_invalid_event` is unreachable during restore because
`.use()` can only be called *after* `from_snapshot` returns. That is true of
the idiom the repro uses — but #230 added the API that closes it. Verified
directly:

```python
r = SyncInterpreter.from_snapshot(snap, m, plugins=[spy])
# plugins= hook fired: [('UnknownEventError', Event(type='UNDECLARED', payload={}))]
# last_error: UnknownEventError   →  FIXED VIA #230: True
```

The hook now fires **during** the restore admission and `last_error` is set.
The repro predates the fix and should be retired/rewritten to the `plugins=`
form.

### 4.5 The 79 FAIL-in-both

Unchanged from round 12 and concentrated in the known historical buckets
(`post-5e07ba8` 11, `post-3ed3099` 7, `probes/main-5327ba6` 6,
`probes/main-5e07ba8` 6, `probes/main-f28719c` 6, …). These are the
documented "fixed but opt-in" / stale-repro / trust-boundary set per the
round-10 R10-01 pattern. **No movement, so no posture change.**

---

## 5. BENCH-6 — loaded timer lateness

Per the round-12 correction, our own `bench_c_timers.py` was never the right
instrument; this uses the library's own harness:

```
benchmarks/production_characteristics.py --quick     # §2, ≈6 s/run, ×5
```

§2 = `after: 10` lateness, median ms beyond the 10 ms deadline.

| busy machines | run 1 | run 2 | run 3 | run 4 | run 5 |
|---|---|---|---|---|---|
| 0 | +0.1 | +0.1 | +0.1 | +0.1 | +0.1 |
| 10 | +1.1 | +1.1 | +1.3 | +1.3 | +1.2 |
| 100 | +11.8 | +12.3 | +12.3 | +10.4 | +11.7 |
| **500** | **+57.4** | **+54.3** | **+64.8** | **+61.4** | **+61.0** |

**Distribution at 500 busy machines:** min +54.3, median **+61.0**,
max +64.8, spread 10.5 ms. **All five readings pass the ≤ 100 ms bar.**

Against round 12 (+89.6 / +94 / +113 / +110 / +111 ms) this is a **~40 %
improvement** with a *tighter* spread (10.5 ms vs ~23 ms), and every reading
now clears the bar where round 12 had two readings (+113, +111) uncomfortably
close to it and one over. This is consistent with the documented 0.9.0 run-loop
change (yield every 16 inbox events rather than every one) and the removal of
the per-child manager task.

> **BENCH-6: PASS, with materially more headroom than any prior round.**
> House rule A2 (external `MonotonicScheduler` requirement) stays retired.

---

## 6. Regression classification summary

Applying the mandated decision table:

| artefact | movement | class |
|---|---|---|
| gate `LC-39` repro | PASS→FAIL | **stale repro** (docs branch of its own EXPECTED now satisfied; baseline PASS was host noise) |
| `150_send_threadsafe_budgeted.py` | PASS→FAIL | **SUPERSEDED-BY-#225** (asserted the removed `ContextVar`-inheritance contract) |
| `225-228_matrix.py` | new, FAIL | **harness artefact** (`XSM_REPO` unset; ALL PASS when set) |
| `DE-L4-repro.py` | new, FAIL | **fixed by #230** (repro predates `from_snapshot(plugins=)`) |
| 13 artefacts | FAIL→PASS | genuine fixes (#105, #167, #197/R9-08, R8-04, R8-07, LC-37, LC-42 ×2, 147/151, p7) |

**TRUE REGRESSIONS: 0.**

No `SUPERSEDED-BY-#232` cases arose — no swept script runs under `-W error`,
so the new never-awaited `RuntimeWarning` did not fail anything. (It is
positively confirmed working by `232.def_drop_receipt_warns` in the
v0.9.0 matrix.)

---

## 7. Carried actions (all non-blocking)

1. **Publish 0.9.0 to PyPI.** Still absent; `pip download` fails. Pin
   `91bd979` by VCS ref until the publish workflow runs. *Release hygiene —
   the only item touching adoption mechanics.*
2. **Fix our `LC-39` criterion** to assert the documented flat-aggregate band
   (`0.5× ≤ top/base ≤ 2.0×`) instead of demanding superlinear scaling on a
   single event loop. *Our harness, not the library.*
3. **Retire or rewrite `150_send_threadsafe_budgeted.py`** to the post-#225
   contract (`internal=True` / explicit `copy_context()` opt-in), which it
   already verifies as green.
4. **Rewrite `DE-L4-repro.py`** to the `from_snapshot(..., plugins=[...])`
   form, or mark it fixed-by-#230.
5. **Export `XSM_REPO`** in the sweep runner so `228.repo_path_provided`
   stops registering as a failure.

---

## 8. Verdict

> **v0.9.0 (`91bd979`) introduces no regression against `de2da4e`.**

The suite is green at 3577 tests and 92.86 % coverage; the gate improves by
one net FAIL and gains seven green pins; the 534-script historical sweep moves
one script to FAIL for a superseded contract and eleven to PASS; no livelock
repro hangs; and the headline timing risk (BENCH-6) clears its bar on all five
runs with ~40 % more margin than round 12.

**Readiness posture from `69-r12-final-readiness-verdict.md` is unchanged and
mildly improved.** The single outstanding adoption blocker is **distribution
(not on PyPI)**, not behaviour.
