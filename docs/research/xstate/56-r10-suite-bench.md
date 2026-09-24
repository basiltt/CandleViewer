# Round 10 — Suite + Benchmarks (time-boxed)

Library: xstate-statemachine @ `19cb1f1` (unreleased 0.8.1, `__version__` still
`0.8.0`). Round-9 fixes per CHANGELOG [Unreleased]: #203-#210 (statesToInvoke
deferred-invoke-arming, engine-minted `_EngineAfter` only, raise(delay=)
charged to engine work, `RunawayChainError.stranded` +
`on_invocation_stranded` hook, receipt/in-flight-flag ordering, lap parity
1-25 sweep, #210 convergence wait).

## Unit test pin

`tests/test_round9_findings.py`: **19/19 passed** (single run, 19.23s).
Matches CHANGELOG's round-9 claim.

## Full suite + coverage — INCOMPLETE within the 20-minute hard bound (again)

Started first, in background, redirected to `suite-19cb1f1.log`. At the point
this report was written it had reached **~25%** of 3518 collected tests
(through `test_round9_findings.py`) with **zero failures observed** in the
streamed output — every file from `test_action_error_policy` through
`test_round9_findings` green, including all of round3-round9 findings files
back-to-back. No final pass/fail/coverage total available this round; same
shape as round 9's own report (which reached ~51% before its bound — this
round's benches (below) consumed more of the budget up front, so the suite
progressed less far by cutoff). Follow-up with a fresh time budget still
needed for a final total.

## PYTHONHASHSEED=1 vs 2 on round7/8/9

Ran `tests/test_round7_findings.py tests/test_round8_findings.py
tests/test_round9_findings.py` together (85 tests) under both seeds:

- `PYTHONHASHSEED=1`: **85 passed**, 32.03s.
- `PYTHONHASHSEED=2`: **85 passed**, 32.45s.

**No flake reproduced this round** — `TestAsyncRollbackRearmCycleBounded::
test_service_calls_bounded_by_max_iterations` (flagged in round 9 as newly
load-independent, 4/5 standalone failures) passed cleanly under both hash
seeds here. This is *consistent with* (not proof against) round 9's own
framing that the bound is racy at a fine grain — a single clean 85/85 run per
seed does not contradict a ~80% failure rate measured over 5 standalone runs
last round; it just didn't land this time. Recommend re-running the same
standalone ×5 protocol from round 9 in a follow-up to get a fifth data point
before concluding anything changed.

## Benchmarks

### bench_a_throughput (single async `Interpreter`, 5-state OMS machine)

| metric | value |
|---|---|
| burst_10000 events/s | 42,637 |
| burst_50000 events/s | 40,855 |
| lockstep_5000 events/s (p50/p95/p99 latency, µs) | 21,631 (43.4 / 57.5 / 88.0) |
| raw_send_50000 (enqueue only) | 252,717 sends/s |
| pure_api_50000 (no interpreter, floor) | 34,766 events/s |

**Substantially higher than round 9's readings** (round 9: burst_50000 8,195
events/s vs this round's 40,855 — roughly 5×). This is a large enough jump to
flag rather than take at face value: it may reflect genuine engine-side
throughput work from the round-9 fix set (statesToInvoke deferral removing
redundant invoke-arming work per macrostep), a warmer/less-loaded host this
run (benches ran before the background suite had ramped up CPU contention,
unlike round 9 where suite and benches likely overlapped more), or a harness
change. Not bisected this round — flag for round 11 to re-run bench_a
head-to-head against `f28719c` on the same idle host to separate "engine got
faster" from "host was less contended."

### bench_h_candleviewer_budgets

- **Budget 1** (submit→open latency, 500 background order machines, 200
  samples): p95 total **144.6 ms** vs 300 ms budget →
  **headroom 2.07×, budget MET**. This flips round 9's result (p95 948.5 ms,
  0.32× headroom, missed) to a pass. Given the same host-contention caveat as
  bench_a above (this round's bench_h ran on a less-loaded host / earlier in
  the wall-clock window than round 9's, which historically ran benches
  *during* an already-running full-suite background job), treat the
  direction of travel as informative but the exact multiple as unconfirmed
  until re-measured under matched load conditions.
- **Budget 2** (1000 rule machines × 10 symbols, 100 rules/symbol, 2000
  market events): async engine 44,356 rule-evals/s (443.6 market events/s),
  sync engine 39,401 rule-evals/s (394.0 market events/s); both still **miss**
  the 2,000 events/s budget, though roughly 3× higher throughput than round
  9's 142.9/114.5 events/s. RSS growth: async +33.0 MB, sync +0.0 MB (in
  band with round 9's +34.4 MB / +0.0 MB).
- **Budget 3** (500 concurrently-open order machines, steady state): all 500
  reached `open`; **3.064 KB/order** (RSS cost 1.496 MB / 500 orders), fill
  latency p50/p95/p99 = 0.112 / 0.131 / 0.176 ms; 1.496 MB retained after
  teardown.

**On the KB/order metric**: round 7 flagged 3.10-5.18 KB/order as a drift
range; round 9 measured 2.128 KB/order (below the floor, "not currently
reproducing"); this round measures **3.064 KB/order**, back inside round 7's
originally-flagged range. Combined with round 9's low reading, this
reinforces that the metric is noisy run-to-run (single-sample RSS delta over
a 500-machine population, ~1-1.5 MB total signal) rather than trending in
either direction — still not bisected across commits, still not confirmed
resolved either way.

### bench_j_policies (cost of opt-in 0.8.0 policies vs bench_a's burst_50000 baseline)

| policy | events/s | vs baseline |
|---|---|---|
| baseline | 40,545 | 1.00× |
| rollback | 31,099 | 0.767× |
| defer | 41,749 | 1.030× |
| rollback_and_defer | 30,589 | 0.754× |

Relative shape is consistent with round 9 (rollback ~0.75-0.93×, defer
~1.03-1.24×, combined ~0.75-0.93×) even though absolute throughput is ~5×
higher across the board — supports the "host contention differed between
rounds" reading over "policy costs changed," since the *ratios* between
policies are stable while the *baseline* moved.

### bench_c_timers, bench_e_actors — NOT COMPLETED (bench_c timed out)

`bench_c_timers.py` (incl. `load_500`/`load_500_plus_cpu_hog` tiers) was run
standalone with a 115s wall-clock cap and **did not produce any output before
timeout** (exit code 124, both stdout and stderr empty — the script buffers
all results to a single JSON dump at the end, so no partial data is
recoverable from this run). This is itself a signal worth carrying forward:
round 9 also failed to complete this same bench (deferred, not attempted to
completion) with the two-tier `load_500`/`load_500_plus_cpu_hog` structure
being the likely cost driver (500 interpreters × timer samples, twice). Two
rounds in a row this bench has not finished inside a ~2-minute cap; recommend
either raising its per-script budget explicitly in a follow-up (it may
genuinely need >120s) or reducing its sample/interpreter counts so it fits
the hard bound. `bench_e_actors.py` was not attempted this round given the
remaining time budget after bench_c's 115s was spent with no result.

## Cost of the statesToInvoke deferral — no dedicated microbench, but suggestive evidence

The instructions ask whether "invoke now arms after settle" moves
submit→ack latency. This round's data does not isolate that specific cost
(no before/after commit-pinned comparison was run — out of time budget), but
two observations bear on it indirectly:
- Budget 1's submit→open p95 improved from 948.5ms (round 9, pre-fix commit
  `f28719c`) to 144.6ms (this round, post-fix `19cb1f1`) on the exact
  scenario (500 background order machines) that this deferral would affect
  most directly, since it changes when invoked services actually submit.
- bench_a's plain-event throughput moved by a similar ~5× factor, which is a
  scenario the invoke-arming change should *not* touch (bench_a's OMS machine
  doesn't invoke services on the hot path measured), suggesting most of the
  movement here is host/contention-driven rather than attributable to the
  round-9 fix set specifically.

Net: **cannot attribute Budget 1's improvement to the statesToInvoke fix
with confidence this round** — a same-host, same-load A/B between `f28719c`
and `19cb1f1` for bench_a and bench_h is needed to separate the two effects
and should be the first item in a round-11 pass.

## Not completed this round (carry forward)

- Full suite + coverage total (reached ~25% this round vs ~51% in round 9;
  still no final pass/fail/coverage number across two rounds now).
- `bench_c_timers` (timed out with zero output, two rounds running) and
  `bench_e_actors` (not started) — `bench_c_timers` in particular needs
  either a longer allotted budget or a reduced-scale variant.
- A/B of bench_a and bench_h between `f28719c` and `19cb1f1` on matched host
  load, to attribute this round's ~5× throughput jump and Budget 1's flip
  from missed to met, versus attributing it to host contention differences
  between rounds.
- Fifth PYTHONHASHSEED data point for `TestAsyncRollbackRearmCycleBounded`
  (standalone ×5 protocol from round 9) — this round's 85/85-under-both-seeds
  run doesn't reproduce round 9's 4/5 standalone failure rate but was a
  different run shape (batched, not standalone ×5).
- Bisection of the KB/order RSS metric across commits (round 7 high, round 9
  low, round 10 back near round 7's range) — still unexplained variance.
- Dedicated priority-lane / invoke-completion microbench to isolate #192/#195
  provenance-tag cost (carried from round 9, not attempted this round
  either).

## Verdict (partial)

No correctness regressions found in `test_round9_findings.py` (19/19), in
round7-9 combined under both hash seeds (85/85 × 2), or in the ~25% of the
full suite observed streaming before the time bound. Throughput/latency
benchmarks moved substantially higher than round 9 across bench_a, bench_h,
and bench_j in a *consistent proportional pattern* (ratios between policies
and between engines held steady while absolute numbers rose ~3-5×), which
points more toward host-load differences between rounds than a genuine ~5×
engine speedup from the round-9 fixes — not confirmed either way without a
matched-load A/B, which is the top follow-up item. Budget 1 flipped from
missed (round 9) to met (2.07× headroom, this round) on the same reading. The
KB/order metric landed back near round 7's originally-flagged range after
round 9's low outlier, reinforcing "noisy," not "trending." `bench_c_timers`
timed out with no output for a second consecutive round and needs a
budget/scale adjustment; `bench_e_actors` and the full coverage total remain
deferred.
