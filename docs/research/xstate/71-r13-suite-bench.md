# 71 — Round-13 suite + bench (v0.9.0)

Scope: BENCH-6 correction (500-busy-machine timer lateness, ×5+tag),
throughput/policy/actor/CandleViewer-budget benches, full suite+coverage tail,
PYTHONHASHSEED parity, PyPI availability, main-vs-tag diff.

## 0. Environment / repo state

- Clone: `_ref/xstate-statemachine`, branch `main` @ post-v0.9.0 (2 commits
  ahead of tag `v0.9.0`).
- `git diff v0.9.0..HEAD --stat`: **1 file changed** —
  `.github/workflows/publish.yml` (+14/-1). Confirmed CI-only; no library
  source differs between `main` and `v0.9.0`. Benchmarks below apply equally
  to the tag.
- `__version__` = `0.9.0`.
- **Not yet on PyPI**: `pip download xstate-statemachine --no-deps` resolves
  to `xstate_statemachine-0.8.0` (the last published release), not 0.9.0.
  Anyone `pip install`-ing today gets 0.8.0, not the round-12-fixed build.
- Venv: `.venv-main`, Python 3.13.7, Windows 11, Intel i7-class 8 logical /
  4 physical cores, 15.9 GB RAM.

## 1. BENCH-6, corrected (upstream `production_characteristics.py --quick`, §2)

Per round-12 correction: `bench_c_timers.py` in this repo does not reproduce
upstream's "N busy machines" loaded-timer scenario, so it was not the right
tool for BENCH-6. Used upstream's own script instead, 5 runs + 1 full-matrix
run, `after: 10ms` deadline, median lateness beyond deadline:

| busy machines | run1 | run2 | run3 | run4 | run5 | full-matrix run |
|---:|---:|---:|---:|---:|---:|---:|
| 0   | +0.2 | +0.2 | +0.1 | +0.2 | +0.1 | +0.2 |
| 10  | +1.8 | +1.5 | +1.3 | +1.8 | +1.3 | +2.1 |
| 100 | +13.5 | +15.4 | +14.4 | +12.9 | +14.0 | +19.5 |
| 500 | — | — | — | — | — | +91.2 |

500-busy-machines row only appears in the full (`--quick` still runs it once
as part of the standard quick set — see 6-run supplemental below):

| run | 500-busy lateness ms |
|---|---:|
| A | +124.1 |
| B | +79.9 |
| C | +97.9 |
| D | +78.1 |
| E | +77.6 |
| full-matrix | +91.2 |

**Distribution across 6 readings at 500 busy machines:** min +77.6, p50
≈ +85.6 ms (median of 78.1/91.2), p99/max +124.1, mean ≈ +91.5 ms.

**Verdict vs our ≤100 ms p99 bar:** **fails at the tail.** 4 of 6 readings
are under 100 ms, but the max (+124.1 ms) and at least one other run (+97.9,
borderline) show this is not a hard guarantee — round-12's fix improved
median cases (prior round-12 readings were +89.6/+94/+113/+110/+111 ms,
essentially the same envelope, so **round 13 shows no material regression or
improvement over round 12** at this load level; both rounds straddle the
100 ms bar). This remains an architectural characteristic (cooperative
single-loop scheduling under 500 busy machines), not a round-12 regression.
Same host caveat as before: Windows default timer resolution ~15.6 ms
inflates all these numbers vs Linux; treat as order-of-magnitude.

## 2. bench_a_throughput.py

- `burst_10000`: 22,749 ev/s (43.96 µs/event)
- `burst_50000`: 24,748 ev/s (40.41 µs/event)
- `lockstep_5000`: 12,990 ev/s; latency p50 64 µs, p95 127 µs, p99 145 µs,
  max 3.29 ms
- `raw_send_50000` (enqueue only, no drain): 172,818 sends/s, 5.79 µs/send
- `pure_api_50000`: 27,777 ev/s, 36.0 µs/event

No regression signal vs prior rounds' recorded orders of magnitude (still
20–30k ev/s class for macrostep-bound single-interpreter throughput).

## 3. bench_j_policies.py (burst 50,000, vs baseline)

| policy | ev/s | µs/event | vs baseline |
|---|---:|---:|---:|
| baseline | 34,498 | 28.99 | 1.00x |
| rollback | 26,162 | 38.22 | 0.758x |
| defer | 30,609 | 32.67 | 0.887x |
| rollback_and_defer | 23,907 | 41.83 | 0.693x |

Rollback+defer combined costs ~31% throughput vs baseline — consistent with
prior-round cost profile; `_action_tasks` bookkeeping (replacing the old
ContextVar) does not show up as an outlier here since these paths don't
depend on self-send provenance tracking.

## 4. bench_e_actors.py

- `spawn_50_children`: spawn 150.0 µs/child mean (p99 182.2 µs); teardown
  26.6 µs/child mean (p99 40.4 µs); all 50 children registered.
- `send_to_child_10000`: 15,792 msgs/s parent→child, 63.3 µs/forwarded msg,
  100% delivered.
- `leak_check` (300 cycles × 10 children/cycle = 3,000 actor lifecycles):
  RSS 36.75 → 37.00 MB, **+0.25 MB total / 0.085 KB per actor** — no
  meaningful leak.

## 5. bench_h_candleviewer_budgets.py (300 s cap; completed in ~115 s, no
   section needed running standalone)

- `submit_to_open` (n=200): mean 121.9 ms, p50 119.2 ms, p95 139.1 ms,
  p99 158.7 ms, max 210.6 ms. Budget 300 ms → **within budget**, headroom
  2.16x at p95.
- `budget2_rules_async_1000x10`: 1000 rule machines × 10 symbols × 100
  rules/symbol, 2000 market events → 41,636 rule-evals/s but only
  **416.4 market-events/s** against a 2,000 ev/s budget target →
  **does not meet 2k ev/s** (fails budget2). RSS growth +33.0 MB.
- `budget2_rules_sync_1000x10`: SyncInterpreter variant, 396.5 ev/s, also
  **fails** the 2k ev/s budget2 target. RSS growth ~0 (-0.06 MB, noise).
- `budget3_500_open_orders`: all 500 orders reached `open`; RSS cost
  ~2.96 KB/open order (1.45 MB for 500); fill latency p50 0.066 ms, p99
  0.294 ms, max 0.544 ms; 1.46 MB retained after teardown (500-order
  bookkeeping not fully GC'd within the run — worth watching, not
  necessarily a leak since no repeated-cycle growth test was done here).

**budget2 (2k market-events/s) remains an open gap** for the
1000-machines×10-symbols×100-rules/symbol shape on both engines — this is
the known CandleViewer-relevant scaling ceiling from prior rounds, unchanged
by round 12's fixes (none of #225–#235 touch the hot per-event dispatch
path in a way expected to move this number).

## 6. Full suite + coverage (tail of `suite-v0.9.0.log`)

**Complete.** Final line:
```
3577 passed, 13 skipped, 15 warnings in 597.15s (0:09:57)
Required test coverage of 90.0% reached. Total coverage: 92.86%
```
No failures, no errors. 13 skips are the pre-existing `test_type_safety.py`
optional-typing-extra skips (`sssssss.` pattern), consistent with prior
rounds.

## 7. PYTHONHASHSEED parity (round 10/11/12 finding suites)

Ran `tests/test_round10_findings.py tests/test_round11_findings.py
tests/test_round12_findings.py` (69 tests total) under both
`PYTHONHASHSEED=1` and `PYTHONHASHSEED=2`:

- Seed 1: **69 passed** in 9.57 s
- Seed 2: **69 passed** in 9.58 s

No hash-seed-dependent flakiness across these three finding suites.

## 8. bench_c_timers_v2.py

Written at `docs/research/xstate/bench/bench_c_timers_v2.py`. Thin wrapper:
shells out to upstream `benchmarks/production_characteristics.py --quick`,
parses its §2 "busy machines / lateness ms" table across N runs, and emits
our JSON shape (`raw_ms_by_busy_level`, `summary_by_busy_level` with
p50/p99/mean, `within_bar_at_500` against our ≤100 ms bar) so
`run_gate.py` can consume BENCH-6 going forward without reimplementing the
scenario. Verified with a 1-run smoke invocation (see tool output above);
default is 5 runs.

## Bottom line

- No library-code delta between `v0.9.0` and `main` (CI-only, confirmed).
- Suite: 3577 passed / 13 skipped, 92.86% coverage — clean.
- Hash-seed parity: clean across round 10–12 suites.
- **PyPI still serves 0.8.0** — 0.9.0 fixes are not yet reachable via
  `pip install`.
- BENCH-6 (500-busy timer lateness): straddles the 100 ms p99 bar (4/6 runs
  under, max +124 ms) — same envelope as round 12, not a regression, but
  still not a clean pass; flag as a known soft ceiling for any CandleViewer
  design assuming ≤100 ms p99 under 500 concurrent busy machines.
- CandleViewer budget2 (2,000 market-events/s @ 1000×10×100 rule scale)
  still fails on both engines (~400 ev/s achieved) — unchanged architectural
  ceiling, not addressed by round 12.
