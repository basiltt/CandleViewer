# Round 11 — Suite + Benchmarks (time-boxed)

Library: xstate-statemachine @ `c78ce99` (unreleased 0.8.1, `__version__` still
`0.8.0`). Round-10 fixes per CHANGELOG [Unreleased]: #212 (raise(delay=)
self-sends are timers — supersedes #206), #213 (snapshot v3
`scheduled_sends`), #214 (restore applies `strict`, upcasts v2 done/error/after
as engine-minted, records carry lane), #215 (settle-budget reset keys on
external provenance, run loop waits for initial descent to settle), #216
(unknown top-level config keys → WARNING/`InvalidConfigError` under
`strict_config`).

## Unit test pin

`tests/test_round10_findings.py`: **15/15 passed** (7.93s), matches
CHANGELOG's round-10 claim.

## PYTHONHASHSEED=1 vs 2 on round8/9/10

Ran `tests/test_round8_findings.py tests/test_round9_findings.py
tests/test_round10_findings.py` together (65 tests) under both seeds:

- `PYTHONHASHSEED=1`: **65 passed**, 52.83s.
- `PYTHONHASHSEED=2`: **65 passed**, 52.97s.

No flake reproduced this round for `TestAsyncRollbackRearmCycleBounded` or any
other test in this combined run, consistent with round 10's own clean
85/85-under-both-seeds result. Still not a fifth standalone-×5 data point
(carried forward again, out of budget this round).

## Full suite + coverage — STILL INCOMPLETE within the 20-minute hard bound
(third round running)

Started first, in background, redirected to `suite-c78ce99.log`. At the point
this report was written it had reached only **~4%** of 3535 collected tests
(through `test_examples.py`) with **zero failures observed** in the streamed
output. This round's progress is markedly *less* far than round 10's ~25% or
round 9's ~51% at cutoff — this round's time budget was spent mostly on the
seed sweep and the three benches below (bench_a, bench_h, bench_j all ran to
completion, consuming most of the wall-clock budget), leaving less time for
the suite to ramp before this report's cutoff. No final pass/fail/coverage
total available this round either; three consecutive rounds now without a
completed full-suite run. Follow-up with a dedicated, benches-deferred time
budget is needed to get a final total — recommend running the full suite
*alone* first in a round-12 pass, before any benchmarks compete for CPU.

## Benchmarks

### bench_a_throughput (single async `Interpreter`, 5-state OMS machine)

| metric | value | round-10 value |
|---|---|---|
| burst_10000 events/s | 40,674 | 42,637 |
| burst_50000 events/s | 42,306 | 40,855 |
| lockstep_5000 events/s (p50/p95/p99 latency, µs) | 21,481 (44.6/50.4/82.6) | 21,631 (43.4/57.5/88.0) |
| raw_send_50000 (enqueue only) | 245,543 sends/s | 252,717 sends/s |
| pure_api_50000 (no interpreter, floor) | 33,544 events/s | 34,766 events/s |

**Closely matches round 10's readings** (within ~5% on every metric, no ~5×
jump this time). This confirms round 10's numbers were the real, host-stable
picture and round 9's much-lower readings (burst_50000 8,195 events/s) were
the outlier — round 9 likely ran under heavier host/suite contention. The
round-10 "flag for round 11 to re-run bench_a head-to-head" item is
effectively answered: no further engine speedup materialized between
`19cb1f1` and `c78ce99` (no code-path reason to expect one — round-10's
fixes are all timer/snapshot/restore/config-validation paths, not the plain
`send()` hot path bench_a exercises), and the round-9→round-10 jump reads as
host contention, not a regression fixed.

### bench_h_candleviewer_budgets

- **Budget 1** (submit→open latency, 500 background order machines, 200
  samples): p95 total **144.5 ms** vs 300 ms budget →
  **headroom 2.08×, budget MET**. Essentially identical to round 10's 144.6 ms
  / 2.07× — corroborates round 10's flip from missed (round 9) to met as a
  real, reproducible state rather than a one-off favorable host sample.
- **Budget 2** (1000 rule machines × 10 symbols, 100 rules/symbol, 2000
  market events): async engine 40,836 rule-evals/s (408.4 market events/s),
  sync engine 33,663 rule-evals/s (336.6 market events/s); both still **miss**
  the 2,000 events/s budget by roughly 5×, comparable to round 10's
  44,356/39,401 rule-evals/s (443.6/394.0 market events/s) within normal
  run-to-run variance. RSS growth: async +32.95 MB, sync +0.0 MB (in band
  with round 10's +33.0 MB / +0.0 MB).
- **Budget 3** (500 concurrently-open order machines, steady state): all 500
  reached `open`; **5.512 KB/order** (RSS cost 2.691 MB / 500 orders), fill
  latency p50/p95/p99 = 0.050 / 0.071 / 0.086 ms; 2.691 MB retained after
  teardown.

**On the KB/order metric**: round 7 flagged 3.10-5.18 KB/order as a drift
range; round 9 measured 2.128 KB/order (below that floor); round 10 measured
3.064 KB/order (back inside round 7's range); this round measures **5.512
KB/order** — now *above* round 7's originally-flagged ceiling, the highest
reading across all four rounds measured so far (round 7, 9, 10, 11). This
continues to look like single-sample RSS-delta noise over a 500-machine
population (~1.5-2.7 MB total signal each round) rather than a directional
trend, but the spread is widening (2.1 → 3.1 → 5.5 KB/order across the last
three rounds) rather than narrowing — worth a multi-sample (n>1) re-measure
in round 12 rather than continuing to treat each round's single reading as
independently informative.

### bench_j_policies (cost of opt-in 0.8.0 policies vs bench_a's burst_50000 baseline)

| policy | events/s | vs baseline | round-10 vs baseline |
|---|---|---|---|
| baseline | 42,834 | 1.00× | 1.00× |
| rollback | 30,863 | 0.721× | 0.767× |
| defer | 41,341 | 0.965× | 1.030× |
| rollback_and_defer | 22,952 | 0.536× | 0.754× |

Baseline throughput matches bench_a's this round (~42-43k events/s, same
host-load regime). Relative ratios are broadly consistent with round 9/10's
range for `rollback` (~0.72-0.77×) but `rollback_and_defer` reads noticeably
lower this round (0.536× vs round 10's 0.754×, round 9's 0.75-0.93× band) —
worth flagging as the one policy-cost number that moved outside its prior
band rather than just tracking baseline movement; not bisected, could be
combined-policy overhead scaling worse under this run's specific contention
or a genuine (if small) regression in the rollback+defer path. Recommend a
repeat run in round 12 before treating it as either.

## bench_c_timers, bench_e_actors — NOT ATTEMPTED this round (time budget)

Given the 20-minute whole-task hard bound and the time already consumed by
the round8-10 hash-seed sweep (~53s × 2) and the three completed benches
above (bench_a, bench_h, bench_j together ran close to their per-script caps),
there was no remaining budget to run `bench_c_timers`'s two heavy tiers
(`load_500`/`load_500_plus_cpu_hog`) even at a reduced 300s-per-tier cap
without breaching the overall bound, so it was skipped rather than run
partially and risk a truncated/misleading result. This is the third
consecutive round `bench_c_timers` has not completed (round 9: deferred;
round 10: 115s timeout, zero output; round 11: not attempted). Recommend
round 12 dedicate its *first* time slice to `bench_c_timers` alone (per-tier,
with the 300s cap the instructions specify) before any other suite/bench
work competes for the budget — BENCH-6 loaded-timer-drift remains
unmeasured across four rounds now. `bench_e_actors` likewise not attempted.

## Cost of scheduled_sends bookkeeping and the descent-settle wait in start()

No dedicated microbench was run to isolate these two round-10 costs (out of
time budget). Indirect evidence: bench_a's plain-event throughput (a scenario
with no delayed self-sends, no snapshot restore, and a single `start()` call)
is unchanged from round 10 within noise, consistent with `scheduled_sends`
bookkeeping being restore/snapshot-path-only overhead with no measurable
per-event tax on the hot send path, and with the descent-settle wait in
`start()` being a one-time cost per interpreter start not visible in a
steady-state throughput loop. Budget 1 (500 `start()` calls, one per
background order machine) is exactly the scenario where a per-`start()`
descent-settle wait *would* show up, and its p95 (144.5 ms) is unchanged from
round 10 — no regression signal there either. Neither observation
constitutes a dedicated before/after commit-pinned measurement; a
`c78ce99` vs pre-#213/#215 commit A/B on `start()` call latency specifically
is the right follow-up if this needs to be pinned down precisely.

## Not completed this round (carry forward)

- Full suite + coverage total (reached ~4% this round vs ~25% round 10, ~51%
  round 9 — three rounds now with no final pass/fail/coverage number).
  Recommend running the suite *alone*, first, with benches deferred, in
  round 12.
- `bench_c_timers` (not attempted, third consecutive round without
  completion) and `bench_e_actors` (not attempted) — needs a dedicated
  time slice at the *start* of the round-12 budget.
- Fifth PYTHONHASHSEED data point for `TestAsyncRollbackRearmCycleBounded`
  standalone ×5 protocol (still not run; this round's 65/65-under-both-seeds
  batched run is consistent with round 10's clean run but neither
  contradicts nor confirms round 9's 4/5 standalone failure rate).
- Re-measure `rollback_and_defer` policy cost (0.536× this round vs
  0.754-0.93× prior rounds) to confirm whether it is host noise or a real
  regression outside its established band.
- Multi-sample (n>1) re-measure of the KB/order metric — spread has widened
  (2.1 → 3.1 → 5.5 KB/order across rounds 9-11) rather than narrowed on
  repeated single-sample readings.
- Dedicated microbench for `scheduled_sends` bookkeeping cost and the
  descent-settle wait in `start()` (carried from this round's instructions,
  not directly isolated — see indirect-evidence section above).
- Dedicated priority-lane / invoke-completion microbench to isolate
  #192/#195 provenance-tag cost (carried from round 9 and round 10, not
  attempted again this round).

## Verdict (partial)

No correctness regressions found: `test_round10_findings.py` 15/15, round
8/9/10 combined 65/65 under both `PYTHONHASHSEED=1` and `=2`, and the ~4% of
the full suite observed streaming before the time bound (zero failures in
that slice, though it is a much smaller sample than round 10's ~25% or round
9's ~51%, so this round's suite evidence is the weakest of the three).
Benchmarks are largely stable and corroborate round 10 rather than
extending it: bench_a matches round 10 within ~5% on every metric
(confirming round 10's numbers, not round 9's, were the representative
reading), Budget 1 stays met at 2.08× headroom (matching round 10's flip
from missed), Budget 2 still misses its 2k events/s target by ~5× on both
engines, and bench_j's `rollback`/`defer` ratios track round 10 while
`rollback_and_defer` reads lower and should be re-checked. The KB/order
metric continues to look noisy but its spread is widening round over round,
warranting a multi-sample follow-up rather than continued single-sample
readings. `bench_c_timers` remains uncompleted for a third consecutive
round and should be the first item budgeted in round 12, alongside getting
a first-ever complete full-suite + coverage total.
