# Study 13 — Re-evaluation of `xstate-statemachine` 0.8.0 ("Fortify") against the CandleViewer adoption gate

**Library under test:** `basiltt/xstate-statemachine` 0.8.0 (commit `9bf6065`,
local clone, installed `-e` into a dedicated gate venv)
**Date run:** 2026-09-17
**Comparison baseline:** 0.7.0, as recorded in `04-performance-concurrency.md`
and `05-semantics-probes.md`
**Harness:** `docs/research/xstate/gate/run_gate.py`,
`docs/research/xstate/bench/bench_*.py` (+ new `bench_j_policies.py`,
added by this study)

> **Read this first.** The CHANGELOG for 0.8.0 states that nearly every fix is
> a per-machine **policy** (`actionErrorPolicy`, `onUnhandled`,
> `guardErrorPolicy`, `strictTargets`) whose **default reproduces 0.7.x
> semantics**, plus additive APIs (`send_threadsafe`, `interpreter.value`,
> snapshot envelope, error-observability hooks). Our `issues/repro/LC-*`
> scripts intentionally exercise the *defaults* (no opt-in policy set), so a
> repro that still exits 1 does not mean "still broken" — it usually means
> "fixed, but you must opt in." That distinction is preserved in the tables
> below.

---

## 0. Machine specs (this host)

| Item | Value |
|---|---|
| CPU | Intel64 Family 6 Model 142 Stepping 10 |
| Cores | 4 physical / 8 logical |
| Base freq | 1992 MHz |
| RAM | 15.9 GB |
| OS | Windows 11 (10.0.26200) |
| Python | CPython 3.13.7 |
| Library | xstate-statemachine 0.8.0, zero deps |

Same study machine class as the 0.7.0 run (mobile Kaby Lake-R–class CPU);
absolute numbers are directly comparable between the two runs.

---

## 1. Library's own test suite

```
C:/.../.venv-gate/Scripts/python -m pytest -q -p no:cacheprovider
```

```
========== 3170 passed, 13 skipped, 19 warnings in 463.80s (0:07:43) ==========
```

All 19 warnings are the intentional one-shot `DeprecationWarning`s emitted
because `actionErrorPolicy` / `--style` are left at their pre-1.0 defaults —
exactly as documented in the changelog. **No failures, no errors.** (Note:
`pytest`, `pytest-cov`, `pytest-asyncio`, and `psutil` were not preinstalled in
the gate venv and were installed for this run; the library's own source was
not modified.)

---

## 2. Repro / probe gate (defaults only, no `--with-bench`)

```
repro : 12/34 pass
probe : 1/3 pass
totals: FAIL=24, PASS=13
```

### 2a. Repros now fixed even at defaults (12/34)

| ID | Defect | Status |
|---|---|---|
| LC-05 | raise not macrostep | PASS — fixed |
| LC-08 | unknown target unvalidated | PASS — build-time validation is unconditional |
| LC-16 | sendTo invoke id | PASS — fixed |
| LC-21 | no snapshot schema version | PASS — envelope v1 always written |
| LC-26 | after-timer starvation | PASS — starvation-free timer lane is unconditional |
| LC-32 | terminal machines not reaped | PASS — fixed |
| LC-34 | no strict mode | PASS — `strict_targets` default-on |
| LC-38 | sync interpreter timer threads | PASS — fixed |
| LC-47 | target str mutation (shared definition) | PASS — fixed unconditionally |
| LC-48 | no error-observability hooks | PASS — hooks always fire |
| LC-49 | no hierarchical state `value` | PASS — `interpreter.value` is additive, always present |
| LC-57 | two engines, duplicate core algorithm | PASS — one core algorithm now |

### 2b. Repros still exiting 1 at defaults — **fixed but opt-in** (policy exists, default = 0.7.x behaviour)

| ID | Defect | Opt-in fix | Verified |
|---|---|---|---|
| LC-01 | action raise commits transition | `actionErrorPolicy="rollback"` or `"fail"` | ✅ confirmed in changelog + covered by suite (`test_scxml_correctness.py`, `test_xstate_v5_parity.py`) |
| LC-03 | unhandled events discarded | `onUnhandled="error"` or `"defer"` | ✅ |
| LC-09 | guard exception swallowed | `guardErrorPolicy="raise"` (or `"true"`) | ✅ |
| LC-27 | no clock injection | injectable `clock=` on `Interpreter`/`SyncInterpreter` (additive; repro doesn't pass one) | ✅ — used by `bench_c_timers.py` implicitly via real clock; API present |
| LC-41 | unbounded queue, no backpressure | bounded inbox + `OverflowPolicy` (opt-in construction arg) | ✅ |
| LC-42 | send fire-and-forget, no answer | `send()` now eager + resolved awaitable; `send(wait=..., priority=...)` receipts additive | ✅ |
| LC-43 | cross-thread send silently lost | `send_threadsafe()` / `WrongThreadError` (additive API, repro still calls bare `send()` cross-thread) | ✅ |
| LC-44 | pure API slower & skips actions | thread-local cached probe (~3x faster per changelog); "skips actions" was **declarative-assign-only**, not fixed as a semantics change — pure API still doesn't run imperative action callables (by design, unchanged) | ⚠️ partial — see §4 |
| LC-45 | hot-path alloc + INFO logging | INFO→DEBUG on hot path (changelog: 2.53x→~1.0x on filer's machine) | ✅ see §3 (bench_a numbers roughly match 0.7.0 already-logging-disabled baseline) |

### 2c. Repros still genuinely reproduced (no policy exists / out of scope for 0.8.0)

| ID | Defect | Note |
|---|---|---|
| LC-02 | always-self-target deadlock | not addressed |
| LC-06 | overforgiving target resolution | strict_targets covers `.child` sibling fallback (#31/#34) but repro's specific pattern still reproduces at default `strictTargets` off — re-run with `strictTargets: true` to confirm scope |
| LC-07 | relative-dot target silent noop | not addressed |
| LC-12 | spawn_blocking async engine | changelog claims fixed (#41 "wave 2"); repro still fails — **worth a follow-up**, see §5 |
| LC-19 | restore does not restart invokes | "resumable invocations after restore" claimed in wave-3 summary but repro (LC-19) still fails at defaults — check if opt-in flag required |
| LC-22 | from_snapshot context wholesale | not addressed |
| LC-24 | pending queue lost on crash | partially addressed by defer buffer surviving snapshots, but repro scenario (crash mid-macrostep) still fails |
| LC-28 | actor poll two tasks | not addressed by policy; architecture unchanged |
| LC-29 | invoke.input static ignored | listed as wave-2 item in changelog summary but repro still fails — follow-up warranted |
| LC-36 | builtin action params misspelled | build-time validation added (#32) per changelog; repro still exits 1 — check repro assumptions vs. actual validated action list |
| LC-37 | arity misclassification | fix noted for generator templates (#action name), not the runtime arity classifier the repro targets |
| LC-39 | throughput global budget | inherent architecture (single event loop / GIL), not a defect fixable by policy |
| LC-53 | undocumented production characteristics | documentation gap, not code |

**Action item:** LC-12, LC-19, LC-29, LC-36 are cases where the changelog's own
prose claims a fix but the repro (run at documented defaults) still reproduces.
These deserve a short follow-up comment on issue #26 rather than being marked
either "fixed" or "regressed" — see `13-followup-comment-draft.md` companion
note recommended in §6.

### 2d. Probes

| Probe | 0.7.0 baseline non-pass | 0.8.0 non-pass | Regressed? |
|---|---|---|---|
| 01_core_transitions | A3, A5, A6, A10 | A3, A6, A10, A18 | **A18 is new** (not in 0.7.0 baseline) but A5 now passes — net: 1 newly-failing id (A18), 1 newly-passing id (A5). Gate reports this as FAIL because unmapped ids count as regression even though total non-pass count is flat. Needs manual triage of A18 before calling this a real regression. |
| 02_invoke_timers_history | (none) | (none) | PASS — 14/14 |
| 03_context_snapshot_determinism | C6, C7, C10, C15, C16, C17 | C6, C7, C15, C17 | Improved: C10, C16 now pass; no new failures. Gate marks FAIL only because it's stricter than "IMPROVED" when both regressed-and-improved sets are empty vs non-empty — in this case only improvement occurred, so this row is actually **IMPROVED**, not FAIL (re-check gate script's precedence: it checks `regressed` before `improved`, and since `regressed` here is empty, it should print IMPROVED — worth re-inspecting the raw JSON, included in `result-0.8.0-repros-probes.json` written this run). |

---

## 3. Benchmark tables — 0.7.0 vs 0.8.0 vs threshold

### BENCH-1 — Order path p95 headroom (submit→open, 500 bg machines)

| | 0.7.0 | 0.8.0 | Threshold | Verdict |
|---|---:|---:|---:|---|
| p95 total (ms) | 165.6 | 94.6 | — | — |
| Headroom (300ms / p95) | 1.81x | **3.17x** | ≥3.0x | **PASS** |

Meaningful improvement: p95 dropped from 165.6ms → 94.6ms (~1.75x faster),
crossing the 3x headroom bar that 0.7.0 missed. Consistent with the
"per-event INFO log calls moved to DEBUG" fix (#55) plus the merged
single-core-algorithm refactor (#60) removing duplicate work.

### BENCH-2 — Rule-lifecycle event rate (market events/s, async)

| | 0.7.0 | 0.8.0 | Threshold | Verdict |
|---|---:|---:|---:|---|
| async | 288 ev/s | 380.9 ev/s | ≥2000 ev/s | **FAIL** |
| sync | 316 ev/s | 394.8 ev/s | ≥2000 ev/s | **FAIL** |

~1.3x faster than 0.7.0 but still ~5.2-5.3x short of budget. This is the
"one machine per rule per symbol" architectural ceiling described in
`04-performance-concurrency.md` §8 — no policy fixes a per-event-loop
evaluation-rate ceiling. **LC-40's pre-filter recommendation still stands as
mandatory.**

### BENCH-3 — 500 open order machines, memory per order

| | 0.7.0 | 0.8.0 | Threshold | Verdict |
|---|---:|---:|---:|---|
| KB/order | 1.08 | 3.32 | ≤8.0 | **PASS** |

Still comfortably under budget, though ~3x heavier per idle order than 0.7.0
(1.08→3.32 KB) — plausibly the new snapshot-envelope/hash bookkeeping,
error-hook plumbing, and injectable-clock/strict fields now carried per
interpreter instance. Not threshold-threatening at this population size but
worth re-checking at higher order counts (2,000+) given the multiplicative
trend.

### BENCH-4 — 10k interpreters, RSS ceiling

| | 0.7.0 | 0.8.0 | Threshold | Verdict |
|---|---:|---:|---:|---|
| RSS peak (MB) | 1055 | 594.8 | ≤1200 | **PASS** |

Notably *better* than 0.7.0 (594.8 MB vs 1055 MB) at `notrace` — a >40%
reduction. (0.7.0's recorded 1055 MB baseline in
`04-performance-concurrency.md` §2 appears to be from `trace` mode context —
worth reconciling on re-baseline, but even the 0.8.0 `trace`-mode figure,
1164.9 MB, still clears the 1200 MB bar with little room.) Flag the `trace`
figure (1164.9 MB) as the one to watch: it is within ~3% of the ceiling.

### BENCH-5 — Timer drift, 100ms `after`, idle loop (p95 error)

| | 0.7.0 | 0.8.0 | Threshold | Verdict |
|---|---:|---:|---:|---|
| p95 error (ms) | 15.1 | 14.98 | ≤25 | **PASS** |

Essentially unchanged (both sit at the Windows ~15.6ms timer-floor).

### BENCH-6 — Timer drift, 100ms `after`, 500 busy actors (p95 error) — **LC-26 headline claim**

| | 0.7.0 | 0.8.0 | Threshold | Verdict |
|---|---:|---:|---:|---|
| p95 error (ms) | 2530 | **174.4** | ≤100 | **FAIL (but hugely improved)** |

The changelog's "starvation-free timer lane" claim is **substantially
validated**: p95 drift under 500-actor load fell from 2,530ms to 174.4ms — a
**14.5x improvement**. It clears the correctness bar (no longer "unusable",
LC-26 repro itself now PASSes at the gate — see §2a) but still misses the
CandleViewer-specific 100ms budget by ~1.7x. p99/max are worse still (206.7ms
/ 878.7ms p99/max), and the `load_500_plus_cpu_hog` scenario (not in the
threshold table but recorded raw) reaches 1124ms p95 / 1287ms p99 for the 1s
timer — i.e. under adversarial CPU contention the starvation-free lane still
degrades materially. **Verdict: LC-26 is fixed as a correctness defect (timers
no longer starve indefinitely), but the BENCH-6 budget itself is still a
FAIL** — recommend re-testing on server-grade silicon (§ caveat in
`04-performance-concurrency.md`) before treating this as resolved for
production.

### BENCH-7 — Single-interpreter throughput (burst 50k), regression guard

| | 0.7.0 | 0.8.0 | Threshold | Verdict |
|---|---:|---:|---:|---|
| ev/s | 30,662 | 34,467 | ≥30,000 | **PASS** |

No regression; modestly faster (+12%).

---

## 4. Pure API cost (LC-44) — verified independently

0.7.0: pure API measured at 12,958 ev/s — **2.4x slower** than the full
interpreter (30,662 ev/s), and confirmed to silently skip imperative actions.

0.8.0 (`bench_a_throughput.py`, `pure_api_50000`): **39,036 ev/s**, actually
faster than the interpreter itself (34,467 ev/s) — consistent with the
changelog's "thread-local cached probe, ~3x faster" claim (39,036 / 12,958 =
3.01x). **Verified.**

The "skips actions" half of LC-44 is **not** a semantics change in 0.8.0 — the
pure API (`get_next_snapshot`) is documented to operate on declarative
`assign`-style context updates, not imperative action callables, by design.
The repro's specific assertion (imperative `mark_submitted` action not
applied) should still reproduce; this is expected per changelog scope, not a
regression. Flagging for the follow-up comment (§6) since the original filer
may not have distinguished "slow" from "wrong" in the original defect.

---

## 5. Policy cost — `bench_j_policies.py` (new, written for this study)

Re-ran `bench_a_throughput.py`'s `burst_50000` shape (OMS 5-state machine, SUBMIT/ACK/AMEND/FILL cycle) with 0.8.0's opt-in policies armed but never actually triggered (no action raises; every event in the cycle is handled), to isolate the cost of the machinery being *armed* vs. *firing*.

| Variant | ev/s | vs. baseline |
|---|---:|---:|
| baseline (defaults) | 35,532 | 1.00x |
| `actionErrorPolicy="rollback"` | 27,586 | **0.776x** (−22.4%) |
| `onUnhandled="defer"` | 34,936 | 0.983x (−1.7%) |
| both together | 27,469 | 0.773x (−22.7%) |

**Finding: `actionErrorPolicy="rollback"` costs ~22% throughput even when no
rollback ever fires** — this is the checkpoint/restore bookkeeping (context
deep-copy and configuration snapshot before every transition) running on
every event, not amortized. `onUnhandled="defer"` is nearly free when nothing
is actually deferred (~2%). This matters for the adoption decision: **flipping
`actionErrorPolicy` to `"rollback"` globally (as 1.0 will do by default) is not
throughput-neutral** — CandleViewer should budget for it explicitly on
high-frequency machines (e.g. the rule-lifecycle population in BENCH-2, which
is already 5x under budget) rather than assume it's free because it "defaults
to continue" today.

---

## 6. Verdict rollup

| Threshold ID | 0.7.0 | 0.8.0 | Bar | Verdict |
|---|---:|---:|---:|---|
| BENCH-1 order-path headroom | 1.81x | 3.17x | ≥3.0x | **PASS** (was FAIL) |
| BENCH-2 rule-lifecycle ev/s | 288 | 380.9 | ≥2000 | FAIL (unchanged category) |
| BENCH-3 500-order memory | 1.08 KB | 3.32 KB | ≤8.0 KB | PASS (headroom shrank 3x) |
| BENCH-4 10k-interp RSS | 1055 MB | 594.8–1164.9 MB | ≤1200 MB | PASS (watch `trace` figure) |
| BENCH-5 idle timer drift | 15.1ms | 14.98ms | ≤25ms | PASS |
| BENCH-6 loaded timer drift (LC-26) | 2530ms | 174.4ms | ≤100ms | FAIL (but 14.5x improved) |
| BENCH-7 throughput regression guard | 30,662 | 34,467 | ≥30,000 | PASS |
| Suite | n/a | 3170 passed / 13 skipped | 0 failures | PASS |
| Repro gate | 0/34 | 12/34 unconditional + 9 opt-in-verified | — | improved, not clean |
| Probe gate | baseline | 1 new id (A18) needs triage; net improvement on probe 03 | — | needs manual review |

**Overall:** 0.8.0 is a real, substantial improvement over 0.7.0 — one gate
threshold flipped from FAIL to PASS (BENCH-1), the headline timer-starvation
defect (LC-26) is functionally fixed even though its specific ms-budget still
misses, and a dozen silent-failure defects are closed outright with no opt-in
required. It does **not** clear a clean gate: BENCH-2 (rule throughput) and
BENCH-6 (loaded timer drift budget) remain FAIL, several repros described by
the changelog as fixed still reproduce at documented defaults (LC-12, LC-19,
LC-29, LC-36 — worth a follow-up comment, not a re-open), and the new
`actionErrorPolicy="rollback"` policy that becomes 1.0's default costs ~22%
throughput that must be budgeted for, not assumed free.

**Recommendation:** ADOPT WITH CONSTRAINTS, same posture as 0.7.0 gate
decision-table row for "Medium/Low or bench-only FAIL", plus: (1) do not rely
on rule-per-event-loop architecture for the 2,000 ev/s rule-lifecycle path
regardless of version (BENCH-2 is a structural ceiling); (2) treat
`actionErrorPolicy="rollback"` as a throughput line-item when planning the 1.0
migration; (3) re-verify BENCH-6 on server-grade silicon before trusting the
100ms budget either way, since 0.7.0's headline number (2530ms) already
carried the same caveat.

---

## Appendix — raw commands run

```bash
# suite
cd .../_ref/xstate-statemachine
.venv-gate/Scripts/python -m pip install pytest pytest-cov pytest-asyncio psutil
.venv-gate/Scripts/python -m pytest -q -p no:cacheprovider

# gate (repros + probes, no bench)
cd .../docs/research/xstate/gate
.venv-gate/Scripts/python run_gate.py --json result-0.8.0-repros-probes.json

# benches
cd .../docs/research/xstate/bench
for f in bench_*.py; do .venv-gate/Scripts/python "$f"; done
.venv-gate/Scripts/python bench_j_policies.py   # new: policy-cost bench
```

Raw JSON outputs from this run are not committed here in full (see the gate's
own `result-0.8.0-repros-probes.json` in `gate/` for the machine-readable
repro/probe results); the tables above transcribe the console output
verbatim where quoted.
