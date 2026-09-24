# Round 9 — Suite + Benchmarks (time-boxed, partial)

Library: xstate-statemachine @ `f28719c` (unreleased 0.8.1, `__version__` still
`0.8.0`).

## Unit test pin

`tests/test_round8_findings.py`: **29 passed** (single run, 8.72s). Matches
CHANGELOG's round-8 claim (#192–#201, reopened #181/#186).

## Full suite + coverage — INCOMPLETE within the 20-minute hard bound

`--cov=src --cov-report=term` was started in the background; at the point
this report was written it had reached ~51% of collected tests with no new
failures observed in the streamed output (round1–round8 findings files,
wave1–wave3, xstate_v5_parity, tests_cli/* all green). It did **not**
complete before the wall-clock bound — no final pass/fail/coverage total is
available this round. Treat as a follow-up item with a fresh time budget
(round 8's own run took ~15 of its 20 minutes just for this step, consistent
with the length here).

## PYTHONHASHSEED=1 vs 2 on round6/7/8

Ran `tests/test_round6_findings.py tests/test_round7_findings.py
tests/test_round8_findings.py` together under both seeds:

- `PYTHONHASHSEED=1`: **1 failed, 83 passed** —
  `TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations`
  (kind='def'): `AssertionError: 260 != 408 : cycle must stop, not spin`.
- `PYTHONHASHSEED=2`: **2 failed, 83 passed** — same test, both kinds.

**This is a change from round 8's characterisation.** Round 8 reported this
exact test as failing only under full-suite load and passing 3/3 standalone
(non-reproducible in isolation). This round it was re-run **standalone, ×5**
(no hash-seed override, default seed):

```
1: 2 failed, 1 passed (3.55s)
2: 1 failed, 1 passed (9.72s)
3: 2 failed, 1 passed (5.01s)
4: 2 failed, 1 passed (3.71s)
5: 2 failed, 1 passed (3.67s)
```

4/5 standalone runs now fail (previously 0/3). This is **not** a round-8
regression — the round-8 fix set's own 29 tests still pass cleanly and
nothing in the CHANGELOG's round-8 entries touches the rollback/rearm cycle
counter this test pins — but the flake has become load-*independent*: it now
reproduces in a bare single-test process, which round 8 explicitly said did
not happen. This should be escalated from "flake, deprioritized" to "needs
root-cause": either the bound in `TestAsyncRollbackRearmCycleBounded` genuinely
regressed between `6db65d8` and `f28719c`, or the counter it reads is racy at
a finer grain than previously assumed. Flagging for the next findings round;
not otherwise pinned or fixed here since it predates round 8 and the
instructions bar library-source changes.

## Benchmarks

### bench_a_throughput (single async `Interpreter`, 5-state OMS machine)

| metric | value |
|---|---|
| burst_10000 events/s | 7,605 |
| burst_50000 events/s | 8,195 |
| lockstep_5000 events/s (p50/p95/p99 latency, µs) | 4,229 (179 / 378 / 496) |
| raw_send_50000 (enqueue only) | 36,026 sends/s |
| pure_api_50000 (no interpreter, floor) | 7,496 events/s |

### bench_h_candleviewer_budgets

- **Budget 1** (submit→open latency, 500 background order machines,
  200 samples): p95 total **948.5 ms** vs a 300 ms budget →
  **headroom 0.32×, budget missed** (same failure shape as prior rounds).
- **Budget 2** (1000 rule machines × 10 symbols, 100 rules/symbol,
  2000 market events): async engine 14,287 rule-evals/s (142.9 market
  events/s), sync engine 11,447 rule-evals/s (114.5 market events/s); both
  miss the 2,000 events/s budget. RSS growth: async +34.4 MB, sync +0.0 MB.
- **Budget 3** (500 concurrently-open order machines, steady state):
  all 500 reached `open`; **2.128 KB/order** (RSS cost 1.039 MB / 500
  orders), fill latency p50/p95/p99 = 0.156 / 0.331 / 0.382 ms;
  1.070 MB retained after teardown.

**On the 3.1→5.2 KB/order drift flagged since round 7:** this round measures
**2.128 KB/order**, below the round-7 floor (3.10 KB) rather than at or above
the previously-flagged high end (5.18 KB). The metric is noisy across runs
(single-sample RSS delta over a 500-machine population, ~1 MB total) and this
run does not reproduce the earlier high reading — read as "not currently
reproducing the drift," not as a confirmed fix, since no bisection across
commits was performed this round (out of time budget).

### bench_j_policies (cost of opt-in 0.8.0 policies vs bench_a's burst_50000 baseline)

| policy | events/s | vs baseline |
|---|---|---|
| baseline | 8,869 | 1.00× |
| rollback | 7,893 | 0.89× |
| defer | 11,017 | 1.24× |
| rollback_and_defer | 8,229 | 0.93× |

Per-item provenance tags on the priority lane (#192) and the private
`engine_done`/`engine_error`/`engine_after` event subclasses (#195) are not
separately isolated by this harness — bench_a/bench_j exercise the plain
event path, not the priority lane or invoke-completion path, so their
constant-factor cost is not visible in these numbers. Given bench_a's
baseline throughput (8,195–8,869 events/s) is in the same band as round 7/8's
recorded baselines, there is no evidence of a broad regression from these
additions on ordinary event dispatch; a dedicated microbench isolating
`send(priority=True)` and invoke-completion delivery would be needed to
attribute their standalone cost and was not run this round (time-boxed out).

### bench_c_timers, bench_e_actors — NOT COMPLETED

`bench_c_timers.py` (incl. `load_500` tiers) was started but did not finish
within the remaining time budget; `bench_e_actors.py` was not started.
Follow-up with a fresh time allotment.

## Not completed this round (carry forward)

- Full suite + coverage total (started, unfinished; watch for the
  `TestAsyncRollbackRearmCycleBounded` failure count in the full run for a
  fourth reference point on the load-vs-standalone question above).
- `bench_c_timers` (incl. `load_500` tiers), `bench_e_actors`.
- Bisection of the KB/order RSS metric across commits (round 7 high vs round
  9 low reading) — currently unexplained variance, not resolved.
- Dedicated priority-lane / invoke-completion microbench to isolate #192/#195
  provenance-tag cost from bench_a/bench_j's plain-event numbers.

## Verdict (partial)

No correctness regressions found in `test_round8_findings.py` (29/29) or in
the ~51% of the full suite observed streaming before the time bound. One
notable change in flake characterisation:
`TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations`
now fails standalone (4/5) where round 8 recorded 0/3 — worth a dedicated
root-cause pass, not attributable to round 8's fix set on current evidence.
Throughput and latency benchmarks are in the same band as prior rounds;
Budget 1 and Budget 2 in `bench_h` continue to miss their targets as before.
The previously-flagged KB/order drift does not reproduce at its high end this
run (2.128 KB/order measured) but was not bisected, so is not confirmed
resolved. `bench_c_timers`/`bench_e_actors` and the full coverage total are
deferred to a follow-up pass with a fresh 20-minute budget.
