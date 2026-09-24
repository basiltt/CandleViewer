# ADR-0014 — Observability stack: Prometheus, Grafana, structured logs, targeted tracing

- Status: **decided**
- Date: 2026-09-14
- Deciders: DevSecOps, Architect, Backend lead
- Consulted: planning brief "SDLC requirements" (observability), `docs/research/11-backend-tech.md` (event-loop lag threshold), `docs/research/22-architecture-options.md` §10
- Related: `docs/plan/20-architecture.md` §12, `docs/plan/06-performance-and-load-standard.md`, ADR-0004

## Context and problem statement

The system runs unattended while holding real positions. Failures are mostly silent-by-default: a stale topic still renders a chart, a slow event loop still serves requests, an order stuck in `Unknown` looks like nothing at all. We need to know — quickly and specifically — when the system is lying to its user. The deployment is a single box for one operator, so the observability stack must be genuinely self-hostable and cheap to run alongside the workload it observes.

## Decision drivers

- The critical signals are numeric and continuous (lag, staleness, queue depth, latency percentiles, rate budget) — a metrics problem, not a log-search problem.
- Two conditions warrant waking the operator: an unprotected position and an order in an unknown state. Everything else can wait.
- Tracing every market-data event would distort the very loop it measures.
- No SaaS: the project is self-hosted and network-isolated by design.
- One operator means alert fatigue is fatal — a noisy alert set will be muted, and then the real one will be missed.

## Considered options

1. **Prometheus + Grafana + Alertmanager, structured JSON logs to stdout, OpenTelemetry tracing on two specific paths.**
2. **A full OpenTelemetry stack** (collector + Tempo + Loki + Mimir).
3. **SaaS observability** (Datadog/Grafana Cloud).
4. **Logs only.**

## Decision outcome

**Chosen: option 1.**

1. **Metrics** — the backend exposes `/metrics`; Prometheus scrapes every 10 s with 15-day retention. The metric catalogue is specified in `20-architecture.md` §12.1 and is part of the definition of done for every module: a module without metrics is not finished. Every metric carries an `env` label so demo and live never blur together.
2. **Frontend telemetry** — the web app pushes frame time, dropped frames, WS decode time and estimated GPU memory to a backend endpoint at a low rate (once per 10 s, aggregated). Field performance regressions in the chart engine are otherwise invisible until a user complains.
3. **Dashboards** — six provisioned dashboards (system health, market data, trading, rules, storage, frontend), stored as JSON in `infra/grafana` and code-reviewed like any other artefact. No click-ops dashboards: if it is not in the repository, it does not exist.
4. **Logging** — `structlog` JSON to stdout with mandatory correlation fields (`request_id`/`conn_id`, `user_id`, `account_id`, `symbol`, `order_link_id`, `trade_group_id`). A redaction processor strips keys, signatures, cookies and TOTP codes at the formatter, and a unit test asserts a known secret never reaches the output. Collected by the compose logging driver with rotation; **Loki is deliberately deferred** until log volume or an incident shows grep-over-files is insufficient.
5. **Tracing** — OpenTelemetry spans on exactly two paths: the **order path** (`http.request → oms.validate → oms.fanout → exchange.place_order → private_ws.fill`) and **replay session start**. Market-data hot loops are covered by metrics only; sampling them would distort the loop and produce data we would not act on.
6. **Alerting** — Alertmanager with two severities and nothing else:
   - **Page** (immediate): `naked_position_alerts_total > 0`; `oms_unknown_orders > 0` for 60 s; Postgres down; clock drift blocking trading; disk > 95 %.
   - **Ticket** (next working session): public WS down > 60 s; high book-resync rate; event-loop lag > 100 ms for 5 min; disk > 80 %; rule auto-disarm; demo/live mismatch attempts; certificate/credential expiry approaching.
   Every alert links to a runbook section in `07-release-and-prr.md`. An alert without a runbook is not allowed to be created.
7. **Health** — `/healthz` (liveness) and `/readyz` (readiness, including migrations-at-head and storage reachability) plus an aggregated module health report surfaced in the Admin health console, which is the operator's first stop.
8. **SLOs** — the budgets in `06-performance-and-load-standard.md` are encoded as recording rules so dashboards show burn rate rather than raw numbers, making "is this getting worse?" answerable at a glance.

### Consequences

Positive:
- Prometheus + Grafana is boring, well understood, self-hosted, and cheap enough to run beside the workload on one box.
- Restricting tracing to two paths keeps overhead negligible while covering the only flows where causality across modules is genuinely hard to reconstruct.
- A two-severity alert policy with mandatory runbooks is the only shape that survives a single-operator reality.

Negative / risks:
- No centralised log search until Loki is added; correlating an incident means `docker compose logs` plus `jq`. Accepted at this scale, and the correlation fields make it workable. Loki is a documented, non-breaking addition.
- Prometheus is not a long-term store; 15 days is short for slow trends. Mitigated by nightly Grafana snapshot exports for load-test and release comparisons.
- Frontend telemetry is a (small) new endpoint with a new data flow. Mitigated by authentication, aggressive aggregation, strict schema validation, and no PII.

### Why not the alternatives

- **Full OTel stack (Tempo/Loki/Mimir)**: three more stateful services on a box that also runs QuestDB and Postgres; the operational cost dwarfs the benefit for one operator and a handful of users. Deferred, not rejected forever.
- **SaaS**: contradicts the self-hosted, network-isolated, no-third-party posture, and would ship trading telemetry off-box.
- **Logs only**: cannot express percentiles, burn rates or continuous gauges like staleness and queue depth, which are precisely the signals that matter here.

## Validation

- Every alert is fired deliberately at least once (in staging with the synthetic feed) and its runbook walked, before Live enablement (R4) — a PRR checklist item.
- Load tests assert that the metric endpoints themselves stay under 50 ms scrape time with the full label set.
- Dashboard JSON is reviewed in PRs like code; a dashboard change without a review is a merge blocker.
