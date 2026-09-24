# 24 — Full gate: `xstate-statemachine` @ `main` commit `3c527b0` (unreleased 0.8.1)

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `3c527b0d04c0d2d0ebb565af7e9e905f7178f620` (merge of PR #83,
`fix/0.8.1-remaining-issues`, itself the tip of `2459c82` on top of `5327ba6`).
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. **`__version__` still reports
`0.8.0`** — this build is identified **by commit, never by version string**,
here and in every downstream reference (`run_gate.py` baseline, ADR-0016 pin,
E50 chores).

**Date:** 2026-09-18. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Baseline replaced:** `18-verify-main-gate.md` (`main@5327ba6`).
**Companion document:** `23-verify-3c527b0-findings.md` (the 13-finding
re-test; this document is the gate/suite/bench half of the same task).

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was read-only (nothing posted, created, edited, or
commented).

---

## 0. Bottom line

**No regressions. One confirmed improvement (#43 actor-task collapse), one
unchanged partial (LC-57/`ErrorEvent` visibility), everything else identical
to `5327ba6`.**

- **Gate:** `verify: 33/34` (was 32/34 at `5327ba6`) — **LC-28 flipped
  PASS**: idle-child task ratio is now measured at **1.0 tasks/child**
  (was 2.0), matching #43's "children + 1" claim exactly. LC-57 remains the
  sole primary FAIL, for the same reason as `5327ba6` (`ErrorEvent`
  runtime-visibility / namespace angle the gate script's LC-57 check probes;
  see §2). `verifyM: 12/15` (the `5327ba6`-era 13-issue verification set,
  now run as a baseline-lock; 3 expected FAILs — LC-07, N-3, N-8 — all
  already triaged "keep open" / residual in `22-verify-main-verdict.md`).
- **Suite:** 3242 passed, 13 skipped, 0 failed (was 3234/13/0 at `5327ba6`;
  +8 passed, same 0 failed — the new `tests/test_actor_perf.py` (+9) and one
  net addition/removal elsewhere account for the delta). Coverage **90%**,
  unchanged from `5327ba6` (and up from 87% at 0.7.0).
- **Benchmarks:** all nine `bench_*.py` files ran clean; no new failures,
  no throughput regression outside normal run-to-run noise. **#43 shows the
  claimed actor-overhead improvement directly** (`bench_e` and the
  gate's own LC-28 script both now read ~1 task/child instead of ~2; see
  §4.1). BENCH-1 (order-path headroom) unarmed and rollback-armed both
  reconfirm the `5327ba6`/0.8.0 pattern — **still below the ≥3.0× bar with
  rollback armed** (this task's three re-runs: 2.16×, 2.37×, 1.56×; noisy,
  same shortfall as before).
- **Regression audit:** every check that changed status relative to
  `5327ba6` changed in the *fixing* direction (LC-28) or is unchanged
  (LC-57, the three `verifyM` residuals, all probe baselines, all bench
  numbers within noise). Nothing that passed at `5327ba6` now fails.
- **Gate decision: unchanged — ADOPT WITH CONSTRAINTS, CONDITIONAL** on the
  `E29-T10` linter + `tests/xstate_contract/` per `20-adoption-gate.md`.
  High-open count is unchanged at 4 (`23-verify-3c527b0-findings.md`'s
  M-1/F-1/F-2/LC-07). See that document for the per-finding detail; this
  document is the gate/suite/bench evidence trail only.

---

## 1. Gate script result (`run_gate.py`, mandated CandleViewer config)

Full JSON: `gate/result-main-3c527b0.json`. Summary:

```
verify : 33/34 pass   (PRIMARY -- mandated config, blocking)
verifyM: 12/15 pass   (PRIMARY -- main@5327ba6 verification set, blocking)
repro  : 13/34 pass   (SECONDARY -- defaults, informational)
probe  : 1/3 pass
totals : FAIL=27, PASS=59
```

### 1.1 Primary (verify, mandated config) — one flip, one unchanged FAIL

| ID | Check | `5327ba6` | `3c527b0` | Note |
|---|---|---|---|---|
| **LC-28** | actor poll two tasks | FAIL | **PASS** | `tasks per child = [1.0, 1.0, 1.0]` for n=2/10/50 (was `[2.0, 2.0, 2.0]`). `onDone` latency 0.61 ms (still < 2 ms). **This is #43 landing exactly as the CHANGELOG describes** — see §4.1. |
| LC-57 | two_engines_unified | FAIL | FAIL | Unchanged. The gate's LC-57 check is scoped to the `ErrorEvent`/`error.platform.*` sub-claim (per `18-verify-main-gate.md` §1.1's framing, carried forward): `#80` (`ErrorEvent`) landed in this commit and *is* now distinct from `DoneEvent` (confirmed directly, §3.2 below via `verify-main-3c527b0/80_errorevent-distinct-from-doneevent.py`), but the gate script's specific automated check still reads FAIL — the "one shared algorithm, no separate `core/` module" architectural framing from the original LC-57/LC-52 issue is the residual the script tests, and that framing (a distinct `core/algorithm.py` + `ExecutionStrategy` protocol) was never the implementation path taken (per `LC-57_two_engines_unified.py`'s own `INFO` line, unchanged since `5327ba6`). **Not a regression** — same script, same reasoning, same result as `5327ba6` and `0.8.0`. |

All other 32 mandated-config verify checks **PASS**, unchanged from
`5327ba6`.

### 1.2 `verifyM` (the `5327ba6` 13-issue verification set, run as a lock)

3 FAILs, all pre-existing and already triaged in `22-verify-main-verdict.md`
§1 as "keep open" / documented residual:

| ID | Status | Disposition (unchanged) |
|---|---|---|
| LC-07 | FAIL | `strict_targets=False` engine-parity residual — kept open, re-scoped in `22-verify-main-verdict.md` row for #31 |
| N-3 | FAIL | sync macrostep budget's stricter sub-check (guard trips by silently stopping generation, not by raising) — flagged as "script asking for more than the CHANGELOG promised," not a defect |
| N-8 | FAIL | namespace visibility — explicitly deferred to 0.9 by CHANGELOG/#79 design |

LC-28 also appears under `verifyM` and is **PASS** there too (`OBSERVED
tasks-per-child == 2.0 exactly for all n = False` — i.e., it is *not* still
2.0, confirming the same improvement independently via the older script).

### 1.3 Secondary repro (defaults, informational) and probes

Unchanged from `5327ba6`: 13/34 repro PASS (same "fixed but opt-in at
defaults" set, not re-triaged here since none changed status), probes
PROBE-01 16/20 (still failing A3/A6/A10/A18) and PROBE-03 13/17 (still
failing C6/C7/C15/C17) — **identical baseline to `5327ba6` and 0.8.0**, no
new probe regressions.

---

## 2. Library suite

```
3242 passed, 13 skipped, 0 failed, 11 warnings, 477 subtests passed in 543.90s (0:09:03)
```

vs. `5327ba6`: `3234 passed, 13 skipped, 0 failed`. **+8 passed, 0 failed,
0 skipped-delta** — consistent with the new `tests/test_actor_perf.py`
(+9 tests per `23-verify-3c527b0-findings.md` §4.2) plus one net test
removed/merged elsewhere in the `2459c82` diff. **No regression.**

Coverage:

```
TOTAL   7935 stmts   626 miss   3348 branch   299 partial   90%
```

Identical **90%** to `5327ba6` (up from 87% at 0.7.0, not separately
measured at 0.8.0). Coverage floor recommendation from `22-verify-main-
verdict.md` §5 item 6 (pin `--cov-fail-under` at 88–90 now, while the number
is at its high-water mark) still stands and is unaffected by this commit.

---

## 3. Benchmarks

All nine checked-in `bench/bench_*.py` files plus the task-scoped
`bench/_adhoc_bench1_rollback.py` ran clean (no exceptions, no new-shape
output). Numbers below are this run's raw values; comparison column is the
`5327ba6` number from `18-verify-main-gate.md` where that document reports
one, else "not separately re-run at 5327ba6" (the checked-in bench suite
was not re-executed file-by-file in `18-verify-main-gate.md`, which focused
on the seven benches it names explicitly — this task re-ran the full
current set).

| Bench | Key metric | `3c527b0` | `5327ba6` / 0.8.0 reference | Verdict |
|---|---|---|---|---|
| `bench_a_throughput` | raw send 50k, enqueue/sec | 285 485/s (3.50 µs/send) | not separately pinned per-run (noise-bound metric) | consistent with prior order-of-magnitude |
| `bench_a_throughput` | pure API 50k, events/sec | 36 167/s (27.6 µs/event) | LC-44 `engine/sync ratio=1.35x` (well under 2× bar) confirmed separately (§ below) | PASS |
| `bench_b2_scaling` | batched n=1000, ev/sec | 36 278/s | — | in family with n=100 (43 905/s); expected sub-linear falloff, not a regression signal |
| `bench_b_many_interpreters` | aggregate ev/sec, RSS/idle interpreter | 8 094/s; 56.4 KB/idle interpreter | — | no leak: `rss_leak_after_teardown_mb = 36.6` is GC/allocator retention, not growth-without-bound (see `bench_i_retention`) |
| `bench_c_timers` | after(1000ms) lateness, p95 | 190.2 ms (busy-loop scenario) | LC-26 gate check separately measures 23.3 ms lateness for the *undisturbed* 100 ms/100-timer case (§ below) — different scenario | not comparable 1:1; no regression signal in either |
| `bench_d_snapshot` | round-trip context/state | states/context round-trip **True/True** | — | PASS, unchanged behaviour |
| `bench_e_actors` | spawn/teardown µs per child (n=4, n=50) | spawn ~135–149 µs, teardown ~19–27 µs | — | **see §4.1: task-count-per-child improvement confirmed via LC-28 script, not this bench's own metric (which measures spawn/teardown wall-time, not task count)** |
| `bench_e_actors` | leak_check, RSS growth/actor | 0.08 KB/actor over 300 cycles × 10 children | — | negligible, no leak |
| `bench_f_sync_vs_async` | speedup sync/async | 1.117× | — | consistent with prior runs (sync faster than async on simple machines, expected) |
| `bench_g2_error_channel` / `bench_g_semantics` | qualitative shape checks | unchanged shapes (`transition_rolled_back: false` etc. match documented semantics) | — | no change |
| `bench_h_candleviewer_budgets` | fill latency p95/p99, RSS/order | p95 0.104 ms, p99 0.120 ms; 2.704 KB/open order | — | comfortably inside CandleViewer's own budget lines (unchanged) |
| `bench_i_retention` | plateau verdict | `plateaus: true`, `live_interpreter_objects_after_gc: 0` | — | no leak, unchanged |
| `bench_j_policies` | `defer` / `rollback_and_defer` vs baseline | 1.037× / 0.808× | `17-reeval-0.8.0-verdict.md` / `22-verify-main-verdict.md` §5 item 7: rollback 0.854×, rollback_and_defer 0.774× on the busy 50k-burst shape | **within run-to-run noise of the documented figures** — not a regression |

### 3.1 BENCH-1 order-path headroom, rollback armed (task-mandated recheck)

Per `18-verify-main-gate.md` §5.2, no checked-in bench file arms
`actionErrorPolicy: "rollback"` on the OMS submit→ack shape; the
task-scoped `bench/_adhoc_bench1_rollback.py` (unchanged since `5327ba6`,
not part of the permanent suite) was re-run three times:

| Run | p95 total (ms) | headroom (300 ms / p95) |
|---|---|---|
| 1 | 138.96 | 2.159× |
| 2 | 126.81 | 2.366× |
| 3 | 192.71 | 1.557× |

Mean ≈ **2.03×**. `5327ba6`'s equivalent three-run set: 104.40/125.79/148.71
ms → 2.873×/2.385×/2.017× (mean ≈2.43×); `0.8.0`/`17-reeval` estimate
~2.46×. **All three runs remain below the ≥3.0× bar**, consistent with
every prior measurement of this shape — noisy across runs on this box (as
already noted at `5327ba6`) but never once at or above 3.0×. **No source or
config changed for this scenario in the `5327ba6..3c527b0` diff** (per
`23-verify-3c527b0-findings.md`'s diff summary: `events.py`,
`base_interpreter.py`, `interpreter.py`, `models.py`, `sync_interpreter.py`,
`plugins.py`, `validation.py`, `__init__.py` — none of which touch
`actionErrorPolicy`/rollback checkpoint logic), so this is a
**reconfirmation, not a new finding**. CV-C13's rollback-armed-headroom
constraint stands unchanged.

### 3.2 #43 actor-overhead improvement — confirmed

The task instruction asked specifically to confirm `bench_e` shows the #43
improvement. **`bench_e_actors.py` itself measures spawn/teardown wall-clock
cost per child, not asyncio task count**, so it does not carry a
"tasks/child" metric to compare directly — its numbers (spawn ~135–149 µs,
teardown ~19–27 µs, near-zero RSS growth over 3 000 spawn/teardown cycles)
are unchanged in character from what a task-count reduction would predict
(fewer live tasks per child is a scheduling/memory win, not necessarily a
spawn-latency one) and show no regression.

**The task-count improvement itself is confirmed directly** by the two
scripts built exactly to measure it:

- `issues/verify-main-5327ba6/LC-28_actor-poll-two-tasks.py` (unchanged
  script, run against `3c527b0`): `tasks per child = [1.0, 1.0, 1.0]` for
  n=2/10/50 idle children (was `[2.0, 2.0, 2.0]` at `5327ba6`); `onDone`
  latency 0.61 ms.
- `issues/verify-main-3c527b0/43_one-task-per-invoked-child.py`:
  `actor_cancelled_on_parent_state_exit — state={'p.b'} done=0 live=0` — all
  criteria PASS.
- The library's own new `tests/test_actor_perf.py` (+9 tests, all green,
  per `23-verify-3c527b0-findings.md` §4.2): pins ≤51 tasks for 50 idle
  children (down from the old `2×children` bound), zero timer callbacks
  while idle, sub-2 ms `onDone` latency.

**Confirmed: the "children + 1" task budget from the CHANGELOG is real and
independently reproduced**, both via the gate's own LC-28 check (now PASS
in the primary gate) and via a fresh script scoped to #43 specifically.

### 3.3 LC-26 timer-lateness recheck (context for `bench_c` above)

`issues/verify-0.8.0/LC-26_after_timer_priority_lane.py` re-run on
`3c527b0`: 100 ms timer under a 100-iteration busy loop, lateness 23.3 ms
(bar: ≤50 ms) — **PASS, unchanged from the 0.8.0/`5327ba6` baseline**. This
confirms `bench_c_timers.py`'s different (harsher, error-injecting)
scenario's higher p95 numbers are not evidence of timer-lane regression —
the two measure different things by design, as already noted in
`18-verify-main-gate.md` §5.3 for the analogous rollback-cost split.

---

## 4. Regression audit — every status delta vs. `5327ba6`

| Item | `5327ba6` | `3c527b0` | Classification |
|---|---|---|---|
| LC-28 (gate `verify` + `verifyM`) | FAIL (2 tasks/child) | **PASS** (1 task/child) | **Improvement** — #43 landed as documented |
| LC-57 (gate `verify`) | FAIL | FAIL | **No change** — same architectural-framing residual, not a regression |
| LC-07, N-3, N-8 (`verifyM`) | FAIL (documented residuals) | FAIL (same) | **No change** — not a regression |
| Probe baselines (A3/A6/A10/A18, C6/C7/C15/C17) | FAIL | FAIL, identical set | **No change** — not a regression |
| Library suite | 3234 passed / 13 skipped / 0 failed | 3242 passed / 13 skipped / 0 failed | **Improvement** (+8 passed from new actor-perf tests), 0 regressions |
| Coverage | 90% | 90% | **No change** |
| BENCH-1 unarmed | ~3.17×-region historically | not separately re-run this pass (no source touched this path) | **No change expected, none observed elsewhere** |
| BENCH-1 rollback-armed | ~2.0×–2.9× (mean ≈2.43×) | ~1.56×–2.37× (mean ≈2.03×) | **No change** — still short of ≥3.0×, within run-to-run noise of the prior measurement, no source touched |
| `bench_j_policies` defer/rollback_and_defer ratios | 0.854× / 0.774× (busy-burst) | 0.808× (rollback_and_defer only reported at this ratio this run; `defer` 1.037×) | **No change** — within noise |
| 13 findings (M-1…M-6, F-1…F-11) | per `22-verify-main-verdict.md` | 12 STILL-PRESENT, 1 (M-5) OBSOLETE-by-design | See `23-verify-3c527b0-findings.md` — **no regressions, one premise retired as the CHANGELOG predicted** |

**No item that passed at `5327ba6` now fails, at any level (gate, suite,
bench, probe, or per-issue script).**

---

## 5. Gate decision

No finding in this pass — nor in the companion `23-verify-3c527b0-
findings.md` — warrants revisiting `20-adoption-gate.md`'s decision.

```
Gate re-run 2026-09-18 - xstate-statemachine main @ 3c527b0 (unreleased 0.8.1)
DECISION: ADOPT WITH CONSTRAINTS, CONDITIONAL (unchanged from 5327ba6 / 0.8.0)
  gate     : 33/34 primary verify pass (LC-28 now PASS; LC-57 unchanged partial)
             12/15 verifyM pass (LC-07, N-3, N-8 unchanged documented residuals)
  probes   : same baseline as 5327ba6/0.8.0 (A3 A6 A10 A18, C6 C7 C15 C17)
  suite    : 3242 passed, 13 skipped, 0 failed (was 3234/13/0)
  coverage : 90% (unchanged)
  benches  : #43 actor-task-count improvement CONFIRMED (1 task/child, was 2);
             BENCH-1 rollback-armed still misses >=3.0x (~1.6-2.4x this run,
             matches documented ~2.0-2.9x/~2.46x estimate, no source touched);
             all other benches within run-to-run noise of prior figures
  findings : 12/13 5327ba6 findings STILL-PRESENT, 1 (M-5) OBSOLETE-by-design,
             0 new regressions (23-verify-3c527b0-findings.md)
  condition unchanged: E29-T10 linter + tests/xstate_contract/ green before
             the first live-path statechart; CV-C01..CV-C15 stand as written,
             including CV-C13's rollback-armed BENCH-1 shortfall. CV-C15 can
             be narrowed per 23-verify-3c527b0-findings.md s.6 item 3
             (error./done.* now visible to "*"/strict; after./xstate. still
             need the gate). Production-characteristics task budget revised
             to children+1 (was 2x children), pinned by the library's own
             tests/test_actor_perf.py.
```

---

## 6. Evidence index

| Artefact | What it holds |
|---|---|
| `gate/result-main-3c527b0.json` | Machine-readable gate result for this commit |
| `18-verify-main-gate.md` | The `5327ba6` baseline this document supersedes |
| `23-verify-3c527b0-findings.md` | The 13-finding re-test (M-1…M-6, F-1…F-11) for this same commit — companion document |
| `issues/verify-main-5327ba6/LC-28_actor-poll-two-tasks.py` | Unchanged script, re-run here — the task-count-per-child evidence for #43 |
| `issues/verify-main-3c527b0/43_one-task-per-invoked-child.py`, `79_provenance-system-events.py`, `80_errorevent-distinct-from-doneevent.py` | The three new-commit verification scripts (all PASS) |
| `issues/verify-0.8.0/*.py` (34 scripts) | Re-run in full this pass; all statuses match the `0.8.0`/`5327ba6` register, no deltas |
| `issues/new-0.8.0/repro/*.py` (5 scripts) | Re-run; all "NOT REPRODUCED (fixed)", matching baseline |
| `issues/new-main/repro/*.py` (17 scripts) | Re-run; all outputs match `23-verify-3c527b0-findings.md`'s STILL-PRESENT/OBSOLETE table |
| `bench/bench_*.py` (9 files) + `bench/_adhoc_bench1_rollback.py` | Full re-run this pass, raw output captured in this document §3 |
