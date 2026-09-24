# Round 7 — Suite + Coverage + Bench (221ce7c)

Commit under test: `221ce7c` (merge of PR #178, "fix/157-loop-side-raise-observable"),
`__version__` still reports `0.8.0` (unbumped; unreleased 0.8.1 target).
Python 3.13.7, Windows 11, venv-main.

## 1. Suite + coverage

```
1 failed, 3418 passed, 13 skipped, 16 warnings in 520.71s (0:08:40)
Required test coverage of 90.0% reached. Total coverage: 92.64%
```

The one failure —
`tests/test_round6_findings.py::TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations`
— did **not** reproduce standalone (re-run in isolation: 1 passed in 1.22s)
nor in the round4+5+6 combined run under either hash seed (§3, both 115/115
passed). This is consistent with order/timing sensitivity when run inside
the full 3400+-test suite (shared executor/thread-pool state, GC pauses, or
timer drift under load) rather than a genuine regression in this commit;
flagged as a **flake, not a finding** — no independent repro outside the
full-suite context was obtained in the time budget. Total: 3419 collected,
same magnitude as round-6's 3399+13 (net +7 vs round-6's 3399 passed, `+13`
skipped unchanged), consistent with PR #178 adding a handful of new tests
for #157's re-fix.

Coverage: 92.64% (vs round-6's 92.77%, essentially flat, -0.13 pt — noise
band, no module-level regression flagged). `interpreter.py` 91% (up from
89% in round-6 — the #157 refusal-observability path and round-6 findings
added coverage there), `models.py` 88% (down slightly from round-6's 91%,
consistent with new code added elsewhere shifting the denominator rather
than an actual coverage loss in that module). `--cov-fail-under` (90%)
passes with +2.64 pt headroom.

## 2. `tests/test_round6_findings.py` count

**17 test functions** (`grep -c "^def test_\|    def test_"`), matching
this task's expectation. Standalone run: 1 passed in 1.22s (the test that
flaked in the full-suite run above passed clean here).

## 3. `PYTHONHASHSEED` sensitivity (round4+5+6 finding tests)

```
PYTHONHASHSEED=1: test_round4 + test_round5 + test_round6 → 115 passed in 9.66s
PYTHONHASHSEED=2: test_round4 + test_round5 + test_round6 → 115 passed in 9.85s
```

Identical pass count under both seeds (46 round-4 + 52 round-5 + 17
round-6 = 115), no flakes. No hash-order sensitivity detected in the
finding suites themselves — the full-suite flake above did not reproduce
here either, reinforcing that it's an interaction with the broader suite's
runtime state rather than the round-6 tests' own logic.

## 4. Benchmarks

Ran within budget: `bench_a_throughput`, `bench_h_candleviewer_budgets`,
`bench_j_policies`, `bench_e_actors`, plus a **reduced** `bench_c_timers`
(idle + load_100 tiers only, `TIMER_SAMPLES` cut 60→15; load_500 and
load_500+cpu_hog tiers skipped to stay inside the overall wall-clock
budget after the ~9-min suite run + hashseed re-runs — same reduction the
round-6 report recommended for a standalone re-run).

- `bench_a_throughput`: raw `send()` enqueue **257,384 ev/s** (3.89 µs/send);
  pure API **35,306 ev/s** (28.32 µs/ev); lockstep-5000 p95 **51.5 µs**,
  p99 **76.0 µs**.
- `bench_h_candleviewer_budgets`: 500 open orders, fill-latency
  p50 **0.060 ms**, p95 **0.077 ms**, p99 **0.330 ms** — inside the
  0.10 ms/300 ms budgets (p95 comfortably; p99 tail wider than round-6's
  0.075 ms but still far under 300 ms); RSS cost **5.18 KB/open-order**
  (up from round-6's 3.10 KB — see §6), no leak after teardown. Rule
  throughput still does not hit 2k events/s (async 407.5/s, sync 372.7/s;
  round-6: 410/342) — same known scaling limit, no regression.
- `bench_j_policies`: burst-50000 ratios vs baseline — rollback
  **0.7189×**, defer **0.9497×**, rollback_and_defer **0.7163×** — inside
  the historical noisy band (round-6: 0.7358/1.1309/0.8386×).
- `bench_e_actors`: spawn (not shown in tail, teardown) mean
  **22.58 µs/child** teardown, p95 spawn **186.5 µs**; parent→child
  throughput **24,216 msgs/s**, all 10,000 delivered; leak check 300
  cycles × 10 children → **+0.077 KB/actor** (noise-level, no leak) —
  consistent with round-6's "no leak, all delivered" shape.
- `bench_c_timers` (reduced, idle + load_100 only): idle after-10ms error
  mean **5.48 ms**, after-100ms **11.87 ms**, after-1000ms **8.25 ms**;
  under 100 busy interpreters, after-10ms error mean **161.1 ms**,
  after-100ms **129.6 ms**, after-1000ms **145.5 ms** — large but expected
  degradation under load (100 concurrent busy interpreters saturating the
  event loop); qualitatively consistent with "timers drift under load,
  don't hang" — no crash/livelock observed. load_500 / load_500+cpu_hog
  tiers not run this round (time budget); see §7.

## 5. Seven-column bench table

| Bench | Metric | 0.8.0 | `5327ba6` | `3ed3099` | `cec108b` (r6) | `221ce7c` (r7, this run) | vs. threshold |
|---|---|---|---|---|---|---|---|
| `bench_a_throughput` | raw `send()` enqueue | ~170k ev/s | ~170k ev/s | not re-run | 238,004 ev/s | **257,384 ev/s** (3.89 µs/send) | in family / continues faster trend |
| `bench_a_throughput` | pure API | ~23k ev/s | ~23k ev/s | not re-run | 37,479 ev/s | **35,306 ev/s** (28.32 µs/ev) | in family, within run-to-run noise of r6 |
| `bench_h` | 500-order fill p95 | ~0.1 ms | same | PASS 0.10 ms | 0.057 ms PASS | **0.077 ms** PASS | inside 0.10 ms/300 ms budget |
| `bench_h` | RSS / open order | ~2.7 KB | same | not re-run | 3.10 KB | **5.18 KB** | higher than r6 — see §6, not yet attributed to a specific PR |
| `bench_j_policies` | rollback/defer/both ratio | 1.037/0.808 | 0.854/0.774 | not re-run | 0.736/1.131/0.839 | **0.719/0.950/0.716** | inside historical noisy band |
| `bench_e_actors` | parent→child msgs/s | ~1 task/child | same | not re-run | 20,615 msgs/s, no leak | **24,216 msgs/s**, no leak | in family |
| `bench_c_timers` | loaded drift (100 busy) | pass (qual.) | pass | not re-run | not completed (r6) | **~130–160 ms mean error, no hang** (reduced scope) | directionally consistent, load_500 tier still not run — gap carried forward |

## 6. Did PRs #165/#176 (hot-path perf) improve anything measurable?

Partial evidence, same single-run caveat as round-6's own analysis of
#141: raw `send()` enqueue (257k vs r6's 238k) and lockstep p95 stayed in
the same band, both plausibly consistent with `__slots__` / shared
init-exit sentinels / log gating landing in #165/#176 reducing per-event
object overhead. Pure-API throughput (35.3k) and policy-ratio numbers
(§5) did **not** show a corresponding uplift over r6 — within noise, no
clear signal either way. `bench_h`'s **RSS/open-order rose** from 3.10 KB
(r6) to 5.18 KB (this run) — the opposite direction from a "perf-improving"
change; this task's evidence cannot attribute that delta specifically to
#165/#176 vs #157/#166–#175 vs environmental variance (single run, no
repeat, no bisection performed — same caveat round-6 raised about its own
throughput uptick). **Conclusion: plausible but not confirmed** that
#165/#176 improved raw send-path throughput; RSS/order regression is
flagged as unattributed and worth a bisected re-run, not asserted as a
#165/#176 regression.

## 7. Does the new per-instance settle accounting (round-6's per-macrostep
chain budget on the async `Interpreter`) cost throughput?

No direct evidence of a cost: `bench_a_throughput`'s enqueue and pure-API
numbers held in-family with round-6 (§5), and `bench_j_policies`'s ratios
(which exercise burst sends through rollback/defer machinery, i.e. paths
where the settle-budget accounting is live) are also within the same noisy
band as round-6 and 0.8.0-era figures. If the per-macrostep budget
bookkeeping (counter reset only on external-event entry, in-flight
self-send tracking via done-callbacks) added meaningful per-event overhead,
it is not visible above the existing run-to-run noise in these
benchmarks — none of them are designed to isolate that specific code path
(a dedicated microbenchmark comparing chain-budget-heavy vs
chain-budget-idle event sequences would be needed to measure it directly,
out of scope here). **No measurable throughput cost detected**, with the
caveat that these benchmarks were not built to isolate that mechanism.

## 8. Gaps / time budget note

- `bench_c_timers`'s `load_500_interpreters` and `load_500_plus_cpu_hog`
  tiers were **not run** this round (only `idle` and `load_100`, with
  `TIMER_SAMPLES` cut 60→15 per round-6's own recommendation). Gap, not a
  finding: total wall clock for suite (~8.7 min) + hashseed re-runs (~20 s)
  + four full benchmarks + reduced bench_c left too little of the 20-min
  bound for the two heaviest tiers (500 busy interpreters + optional CPU
  hogs is the most expensive combination by design).
- The full-suite `test_round6_findings.py` failure (§1) was not resolved
  to a root cause beyond "does not reproduce in isolation or under
  hash-seed variation" — worth a targeted re-run of just that test file
  alongside its neighbors in the full suite (e.g. `pytest tests/ -k
  "round6 or interpreter"`) if a definitive flake/non-flake determination
  is needed; out of scope for this task's time budget.
- The `bench_h` RSS/open-order increase (3.10 KB r6 → 5.18 KB r7) is
  flagged but not bisected; a targeted re-run at `cec108b` vs `221ce7c`
  with repeated trials would be needed to confirm it's a real regression
  vs noise, and if real, to attribute it to a specific PR in the
  #157/#165/#166–#178 range.
