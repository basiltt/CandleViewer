# ADR-0029 — Alert evaluation placement, subscription sharing and storm thresholds

- Status: **proposed** (owner approval pending)
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

| Q1 (500 alerts) | p50 ms | p95 ms | p99 ms | CPU s | peak KiB | subscriptions | evaluations |
|---|---|---|---|---|---|---|---|
| A: one `Evaluator` per alert | 0.293 | 0.548 | 0.667 | 143.9 | 885 | 500 | 500,000 |
| B: notify-only, deduped by `condition_hash` | 0.314 | 0.649 | 0.799 | 12.0 | 140 | 80 | 80,000 |

| Q2 (100 alerts, 12 distinct conditions) | p99 ms | CPU s | subscriptions | metric computations |
|---|---|---|---|---|
| A: per alert | 0.678 | 7.55 | 100 | 3,073 |
| A': E35 `Evaluator`, deduped by hash | 0.827 | 1.09 | 12 | 3,073 |
| B: notify-only, deduped | 0.776 | 0.73 | 12 | 3,073 |

- Metric computations are identical in every variant (the shared `SnapshotBuilder` memo already
  prevents duplicate metric work); the cost difference is evaluator instances and repeated evaluation.
- Both options are far below the 1 s condition-to-record budget (sub-millisecond in-process).
- Q5: the notify-only IR guard costs ~0.001 ms p50 (budget 300 ms).
- Q3 (storm) is **synthetic**; see Limitations.

## Decision

**Option B, with condition-hash sharing: a separate lightweight alert evaluator that calls E35's
`evaluate` nodes, `SnapshotBuilder` and `MetricRegistry` directly (no per-alert `Evaluator`
instance), one subscription per distinct `alerts.condition_hash`, fan-out to member alerts.**

Deciding criterion: *criterion 2* (reuse without duplicated computation) is met: separate
subscriptions (12) == distinct condition hashes (12) and metric computations equal option A's, so the
NFR holds. *Criterion 1* (>15% p99 added to rule evaluation) could not be triggered or refuted here:
the harness does not run alerts concurrently with a loaded rule evaluator (see Limitations); the
decision instead rests on the 12x CPU and 6x memory cost of A at 500 alerts, plus the fact that A
drags rule sandbox/arming/limit semantics onto notify-only objects. Re-run E40-Q02 with concurrent
rule load; if B then adds measurable contention, revisit.

Note A' (E35 `Evaluator` + dedup) is nearly as cheap; if E40-T03 prefers zero new evaluator code it is
an acceptable fallback, provided notify-only validation and per-alert (not per-rule) limits are added.

## Q4 — `once_per_bar`

`bar_open = floor(event_ts / tf_ms) * tf_ms` (weekly anchored to Monday 00:00 UTC) derived from
exchange event time is deterministic for all of 1m..1w; a late tick inside a bar maps to the same key
(tests in `benchmarks/alerts/tests`). Key = `(alert_id, bar_open)`; a revision never opens a new key.

## Q3 — storm threshold

E40-D01's ratified value was not available in the repo, so it is **not confirmed or corrected**. On a
synthetic detector-heavy stream (12,000 user-minute windows) deliveries per user per 60 s: p50 1,
p95 4, p99 50, max 82; bursts (stacked-imbalance) dominate the tail. Proposal pending real E25 data:
storm = **>20 deliveries/user/60 s**, aggregating to one digest per window (catches the burst tail
without touching the ~95% of windows <=4).

## Metrics (defined for E40-T03/T04)

`cv_alert_eval_latency_seconds`, `cv_alerts_armed`, `cv_alert_subscriptions`,
`cv_alert_suppressed_total{reason}`.

## Limitations (honest)

- No recorded E16/E26/E25 window exists on `main`; ticks are a seeded random walk, storm data is
  synthetic. Windows must be named when real data lands.
- Q1's 500-alert corpus uses 20 symbols x 4 thresholds, so it has only 80 distinct conditions, which
  favours B's dedup; the per-alert A column is the like-for-like latency comparison.
- Latency is in-process condition-to-commit with sqlite, not Postgres; Prometheus histograms are not
  yet available (E40-T03), so `time.perf_counter` was used.
- No rule-evaluator interference measured (criterion 1).
- Neither option is near the 1 s budget, so no capacity escalation is needed.
