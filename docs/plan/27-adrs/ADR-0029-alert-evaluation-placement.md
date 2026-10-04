# ADR-0029 — Alert evaluation placement, subscription sharing and storm thresholds

- Status: **proposed** (owner approval pending; Q1/Q2/Q3 evidence caveats below)
- Date: 2026-10-04
- Deciders: Owner (`@basiltt`) — owner approval pending.
- Numbering note: the ticket says "ADR-0019"; that number is taken, so this is the next free number.
- Related: E40-K01 (this spike), E40-T02/T03/D01/Q02, E35-S02, ADR-0007, ADR-0026,
  `docs/plan/spikes/E40-K01.md`, `services/api/benchmarks/alerts/`.

## Context

Alerts must fire server-side with the client closed, reuse E35's metric catalogue and evaluator, and
never duplicate evaluation (US-ALRT-001/002/003). Open: degenerate rules inside E35's `Evaluator`
(option A) or a lightweight notify-only evaluator over the same bus (option B)?

## Evidence (re-derive: `python -m benchmarks.alerts.run`, seeds fixed; 20,000 ticks, 20 symbols)

Delivery workstation, Python 3.13, in-memory sqlite as the `alert_deliveries` stand-in: **relative
numbers only**, not the reference VPS and not Postgres.

Re-run after review (same harness, same seeds, 20,000 ticks / 5,000 for Q2). Latency is also observed into a
`prometheus_client` Histogram named `cv_alert_eval_latency_seconds` (the shape E40-T03 ships); the
`hist p99 <=` column is the PromQL-style bucket upper bound.

| Q1 (500 alerts) | p50 ms | p95 ms | p99 ms | hist p99 <= s | CPU s | peak KiB | subscriptions |
|---|---|---|---|---|---|---|---|
| A: one `Evaluator` per alert | 0.164 | 0.387 | 0.472 | 0.0005 | 79.6 | 890 | 500 |
| B: notify-only, deduped by `condition_hash` | 0.152 | 0.276 | 0.323 | 0.0005 | 5.3 | 142 | 80 |

| Q2 (100 alerts, 12 distinct conditions) | p99 ms | CPU s | peak KiB | subscriptions |
|---|---|---|---|---|
| A: per alert | 0.321 | 3.23 | 187 | 100 |
| A': E35 `Evaluator`, deduped by hash | 0.690 | 0.56 | 58 | 12 |
| B: notify-only, deduped | 0.330 | 0.38 | 33 | 12 |

(Absolute numbers vary run to run on the shared workstation; ratios are stable. Raw: `E40-K01-report.json`.)

- Metric computations are identical in every variant (the shared `SnapshotBuilder` memo already
  prevents duplicate metric work); the cost difference is evaluator instances and repeated evaluation.
- Both options are far below the 1 s condition-to-record budget (sub-millisecond in-process).
- Q5: the notify-only IR guard costs ~0.001 ms p50 (budget 300 ms).
- Q3 (storm) is **synthetic**; see Limitations.

### Decision criteria (stated up front, as the ticket requires)

1. Option A is rejected if running 500 alerts adds **>15% to p99 of concurrently running E35 rule
   evaluation**. Option B is rejected under the same test.
2. Reuse without duplicated computation: separate subscriptions == distinct `condition_hash` values and
   metric computations no higher than A's.
3. Capacity: condition-to-record p99 well under the 1 s budget.

Criterion 1 measured (40 concurrent E35 rule `Evaluator`s on the same builder/thread, rule-evaluation
p99 alone **0.246 ms**): with A's 500 alerts **0.458 ms (+86%)**; with B **0.350 ms (+42%)**. Both exceed
15% in this single-thread harness because alert and rule evaluation interleave on one core
(contention, not isolation). So criterion 1 is *triggered for A and, in-process, also for B*; B adds
about half of A's interference at 1/15 of A's CPU.

## Decision

**Option B, with condition-hash sharing: a separate lightweight alert evaluator that calls E35's
`evaluate` nodes, `SnapshotBuilder` and `MetricRegistry` directly (no per-alert `Evaluator`
instance), one subscription per distinct `alerts.condition_hash`, fan-out to member alerts.**

Deciding criteria: *criterion 1* (A: +86% rule p99, B: +42%, both over 15% when co-scheduled on one
thread; B is the lower-interference option) and *criterion 2* (12 subscriptions == 12 distinct hashes,
identical metric computations). A also costs ~15x the CPU and ~6x the memory at 500 alerts and drags rule
sandbox/arming/limit semantics onto notify-only objects. **Binding condition for E40-T03/Q02:** run the
alert evaluator in its own task/worker so it cannot add >15% to rule p99; E40-Q02 must verify this on a
recorded window and, if B still exceeds 15% when isolated, revisit.

Note A' (E35 `Evaluator` + dedup) is nearly as cheap; if E40-T03 prefers zero new evaluator code it is
an acceptable fallback, provided notify-only validation and per-alert (not per-rule) limits are added.

## Q4 — `once_per_bar`

`bar_open = floor(event_ts / tf_ms) * tf_ms` (weekly anchored to Monday 00:00 UTC) derived from
exchange event time is deterministic for all of 1m..1w; a late tick inside a bar maps to the same key
(tests in `benchmarks/alerts/tests`). Key = `(alert_id, bar_open)`; a revision never opens a new key.

## Q3 — storm threshold

**Not validated against real data; the AC is not claimed as met.** No recorded E25 detector-heavy window
exists on `main` (only `packages/fixtures/raw/synthetic_sample.jsonl`), and E40-D01 has no ratified
threshold value in the repo. Synthetic stream (12,000 user-minute windows, seeded): deliveries per user
per 60 s p50 1, p95 4, p99 50, max 82; bursts dominate the tail. **Provisional proposal** (to be
confirmed or corrected by E40-D01/E40-Q02 on real E25 data): storm = >20 deliveries/user/60 s,
aggregated to one digest per window. Histogram: `E40-K01-report.json` `q3_storm_synthetic`.

## Metrics (defined for E40-T03/T04)

`cv_alert_eval_latency_seconds`, `cv_alerts_armed`, `cv_alert_subscriptions`,
`cv_alert_suppressed_total{reason}`.

## Limitations (honest)

- No recorded E16/E26/E25 window exists on `main`; ticks are a seeded random walk, storm data is
  synthetic. Windows must be named when real data lands.
- Q1's 500-alert corpus uses 20 symbols x 4 thresholds, so it has only 80 distinct conditions, which
  favours B's dedup; the per-alert A column is the like-for-like latency comparison.
- Latency is in-process condition-to-commit with sqlite, not Postgres; a Prometheus Histogram (same name
  as T03's) is fed from `perf_counter` deltas; the real T03 pipeline is not yet available.
- Criterion 1 is measured single-threaded with 40 rule evaluators; isolation behaviour is for Q02.
- Neither option is near the 1 s budget, so no capacity escalation is needed.
