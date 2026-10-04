# ADR-0029 — Alert evaluation placement, subscription sharing and storm thresholds

- Status: **proposed, provisional** (owner approval pending; criterion 1 INCONCLUSIVE; AC exception required, see Limitations)
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
| A: one `Evaluator` per alert | 0.252 | 0.540 | 0.608 | 0.001 | 135.7 | 890 | 500 |
| B: notify-only, deduped by `condition_hash` | 0.334 | 0.780 | 0.953 | 0.001 | 11.4 | 142 | 80 |

| Q2 (100 alerts, 12 distinct conditions) | p99 ms | CPU s | peak KiB | subscriptions |
|---|---|---|---|---|
| A: per alert | 0.543 | 6.7 | 187 | 100 |
| A': E35 `Evaluator`, deduped by hash | 1.156 | 1.4 | 58 | 12 |
| B: notify-only, deduped | 1.338 | 1.1 | 33 | 12 |

(Absolute latencies vary run to run on the shared workstation: three runs put A's Q1 p99 at 0.47, 1.29 and 0.61 ms. Latency ranks are NOT stable; CPU, memory and subscription counts are. Raw: `E40-K01-report.json`.)

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

Criterion 1 measured (40 concurrent E35 rule `Evaluator`s on one thread, rule p99 with and without 500 alerts):
three runs on the shared workstation gave A +86% / B +42%, then A +11% / B +25%, then A -32% / B -32%
(the committed report is the last run; rule p99 alone 0.685 ms). The sign flips between runs, so
**criterion 1 is INCONCLUSIVE**: noise on a shared single-thread workstation dominates any real
interference. It neither rejects nor clears either option.

## Decision

**Provisional: Option B, with condition-hash sharing** (a separate lightweight alert evaluator calling
E35's `evaluate`, `SnapshotBuilder` and `MetricRegistry` directly, no per-alert `Evaluator`, one
subscription per distinct `alerts.condition_hash`, fan-out to member alerts).

This is NOT decided by criterion 1 (inconclusive, above). It rests on criterion 2 and criterion 3,
which are measured and stable: 80 (Q1) / 12 (Q2) subscriptions == distinct hashes with metric
computations identical to A's (criterion 2 satisfied); p99 about 1 ms vs the 1 s budget for both options
(criterion 3 satisfied); A costs ~12x the CPU and ~6x the memory at 500 alerts and drags rule
sandbox/arming/limit semantics onto notify-only objects. Per the ticket's rule, a result that cannot be
supported is recorded as such: **the latency-interference question is deferred to E40-Q02**, which must
re-run criterion 1 on an isolated host with a recorded window. If that run shows B adds >15% to rule p99
even when run in its own task/worker, this ADR is revisited. E40-T03 should therefore run the alert
evaluator in its own task/worker from the start (no new measurement is claimed for that).

Note A' (E35 `Evaluator` + dedup) is nearly as cheap in CPU; if E40-T03 prefers zero new evaluator code
it is an acceptable fallback, provided notify-only validation and per-alert limits are added.

## Q4 — `once_per_bar`

`bar_open = floor(event_ts / tf_ms) * tf_ms` (weekly anchored to Monday 00:00 UTC) derived from
exchange event time is deterministic for all of 1m..1w; a late tick inside a bar maps to the same key
(tests in `benchmarks/alerts/tests`). Key = `(alert_id, bar_open)`; a revision never opens a new key.
Late-tick revision is measured, not only the timeframe table: for each of the 12 timeframes an
arrival-order scenario (bar0 tick, bar1 tick, LATE bar0 tick, duplicate late tick, second bar1 tick)
fires exactly `[bar1, bar0]`, each once (`late_tick_report`, report key `q4_late_tick_revision`).

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
- Criterion 1 is INCONCLUSIVE (noise; see above); isolation behaviour is for Q02.
- **AC status:** AC1 and AC3 call for a recorded E16/E26/E25 window, which does not exist on `main`. They are
  NOT met; a PR note cannot waive them. The owner exception is requested on issue #884 and the ticket stays
  open for these items until the owner grants it or E40-Q02 supplies the recorded window.
- Neither option is near the 1 s budget, so no capacity escalation is needed.
