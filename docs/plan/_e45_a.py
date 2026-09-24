# -*- coding: utf-8 -*-
from _e45_common import mk, dump, MS, PH

EPIC_BODY = """## Context
R4 adds almost no features; **its product is assurance** (`docs/plan/30-release-roadmap.md` #8). E45 proves the third R4 goal - *"prove resilience: reconnect, reconcile, fail over and roll back, under fault injection, without inventing or losing an order"* - and owns R4 exit criteria 5 (chaos suite green), 6 (rollback rehearsal) and 7 (restore drill).

Two bodies of already-specified design converge here; this epic is their **implementation and proof**:

1. **Reconciliation.** The algorithm is fully specified in `docs/plan/24-internal-schemas.md` section 8.5 (`reconcile(account, gap_from) -> ReconcileReport`), the state machine including `Unknown` in section 8.3 and `docs/plan/27-adrs/ADR-0006-oms-state-machine.md`, and the operational shape in `docs/plan/20-architecture.md` section 3.5 (`Reconciler`: startup, reconnect, every 30 s). Security requirement **SR-058** (`docs/plan/04-security-program.md`) makes it mandatory. US-POS-008 is the user-visible contract. E29 shipped the *reactive* reconnect UX (E29-S07); E45 ships the **complete, scheduled, multi-dimension reconciler** (orders, executions, positions, balances, trade groups), its persisted report, its admin surface and the manual resolution of `untracked` orders and position drift.
2. **Chaos and failover.** The scenario catalogue lives in `docs/plan/03-testing-strategy.md` section 9, with the private-WS reconnect sequence asserted step-by-step in section 9.1. **SR-154** requires chaos coverage of WS disconnect, exchange 5xx, `10006`/`10018`, clock drift, DB unavailability and disk-full, asserting the system *fails closed on the order path* while risk-reducing actions still work. `docs/plan/20-architecture.md` section 11 enumerates failure modes F1-F9 with expected detection, degradation and recovery, and an **RTO of <=90 s** from backend restart to fully reconciled trading.

The user-story domain is **OBS** (`docs/plan/11-user-stories.md` section 28): **US-OBS-006** (chaos and failure drills) is this epic's headline Must; **US-OBS-004** (alerting on reconciliation divergence) and **US-OBS-007** (support bundle as a drill artefact) are touched at their reconciliation/drill edges, their base implementation having been delivered by E04.

Why R4 and not earlier: chaos needs the *whole* order path to exist (E29 OMS, E32 native SL, E34 fan-out, E39 kill-switch) and needs the environment boundary (E44) so drills can run against a live-shaped deployment without touching real money.

Backend modules: **M4** (Bybit REST/WS adapter, rate governor) and **M14** (OMS, reconciler, kill-switch integration) per `docs/plan/20-architecture.md`.

## Goal
Make every injected fault end in a **reconciled, correct state**: no orphaned orders, no duplicate submissions, no position the system is unaware of, no position without a native stop - and prove it with an automated, repeatable suite plus a rehearsed rollback and a rehearsed restore.

## Scope / Deliverables
- **Reconciliation service (M14)** - `candleviewer.oms.reconciler`: the section 8.5 algorithm implemented in full (executions applied first, diff by `order_link_id`, resolution from order history, `Unknown` two-pass abandonment with `UNRESOLVED_AFTER_RECONCILE`, adoption of `untracked` exchange orders, position-drift detection, native-SL invariant repair), driven on **startup**, **private-WS reconnect**, a **30 s timer** and **on demand**.
- **Balance and trade-group reconciliation** - wallet snapshot diffing and trade-group leg re-binding, including legs adopted as `untracked`.
- **Persisted reports** - `ReconcileReport` rows, the `oms.reconcile` audit event, `order_events.source='reconcile'` with `kind='reconcile_diff'`, `position_snapshots.reason='rest_reconcile'`, and the `orders.last_reconciled_at` / `positions.last_reconciled_at` watermarks (tables per `docs/plan/21-database-schema.md`).
- **Stale-account lockout** - two minutes of repeated reconciliation failure marks the account stale and disables order entry for it (US-POS-008 scenario 3).
- **Dead-man's-switch policy** - `POST /v5/order/disconnected-cancel-all` integration behind an **explicit opt-in**, correctly documented as `inverse`-only on Bybit, so the local kill-switch (`POST /api/v1/trading/kill-switch`, E39) remains the operative control for USDT linear perps.
- **Chaos harness** - fault-injection framework over the fixture-replay mock exchange plus container, network, clock and disk faults, wired as the CI `@chaos` job (`docs/plan/03-testing-strategy.md` section 9) and runnable as a staging game-day.
- **Chaos scenario catalogue** - WS disconnect storms (public and private), sequence gaps, exchange 5xx and 403, `10018` floods, Postgres failover, QuestDB unavailability, disk-full, clock skew (`10002`), partial fan-out failure and Electron renderer crash mid-order.
- **Rollback rehearsal automation** and **restore drill automation** (Postgres and the Parquet cold tier), each producing a timed, archived report.
- **Admin surfaces** - reconciliation status and discrepancy resolution on **SCR-143** (system health) and **SCR-144** (incident / connectivity log), plus the untracked-order and position-drift resolution flow.
- Design (D), QA (Q) and Security (X) tickets carrying their own points.

**User stories covered:** US-OBS-006 (Must, primary), US-OBS-004 (reconciliation-divergence alerting edge), US-OBS-007 (drill/incident bundle edge), US-POS-008 (completion of the reconciliation contract begun in E29).

## Out of scope
- The observability baseline itself (metrics, logs, alert routing, dashboards, `/metrics`) - **E04**.
- The pen-test and its remediation - **E43**.
- Environment separation, the live feature flag and the live gate - **E44**.
- Kill-switch engine and risk caps - **E39** (E45 only *exercises* them).
- Performance budget enforcement and load testing - **E46**.
- Backup *scheduling* and the backups screen (SCR-146) - E42/E04; E45 adds only the **drill automation** on top.
- Any new exchange; Bybit USDT linear perpetuals only.

## Exit criteria
1. Reconciliation runs on startup, on every private-WS reconnect, every 30 s and on demand, for every configured account, within the `poll` rate bucket, and is **idempotent** (a second immediate run produces an empty report).
2. Every chaos scenario in `docs/plan/03-testing-strategy.md` section 9 passes in CI, and a full staging game-day pass is recorded and signed off by QA.
3. `oms_unknown_orders` returns to 0 after every drill; the alert (>0 for 60 s) has been test-fired and received.
4. No drill produces a duplicate order for any `order_link_id`, an unprotected open position, or a position absent from local state.
5. Rollback rehearsal executed on staging and timed; restore drill executed for Postgres and one symbol's Parquet history, with time-to-restore recorded.
6. The dead-man's-switch policy is documented, opt-in, and its `linear`-unavailability is stated in the runbook and in the UI.
7. STRIDE model complete and reviewed; a11y audit clean on the new admin surfaces; design signed off at least two sprints before the consuming FE story.

## Story list
| Key | Kind | Title | Pts |
|---|---|---|---|
| E45-K01 | Spike | Choose the fault-injection mechanism for the chaos harness | 2 |
| E45-T01 | Task | Implement the reconciliation core over orders, executions and positions | 5 |
| E45-T02 | Task | Drive reconciliation from startup, reconnect, timer and on demand; stale-account lockout | 3 |
| E45-T03 | Task | Persist, expose and instrument the reconciliation report | 3 |
| E45-T04 | Task | Reconcile wallet balances and trade-group legs | 3 |
| E45-T05 | Task | Dead-man's-switch integration with an explicit opt-in policy | 3 |
| E45-T06 | Task | Build the chaos harness and the CI @chaos job | 5 |
| E45-T07 | Task | Chaos catalogue part 1 - exchange and transport faults | 5 |
| E45-T08 | Task | Chaos catalogue part 2 - infrastructure, clock and client faults | 5 |
| E45-T09 | Task | Automate the rollback rehearsal | 3 |
| E45-T10 | Task | Automate the Postgres and Parquet restore drills | 3 |
| E45-S01 | Story | Resolve untracked orders and position drift from the admin UI | 5 |
| E45-S02 | Story | Surface reconciliation and drill state on SCR-143 and SCR-144 | 3 |
| E45-T11 | Task | Write the resilience runbooks and record ADR-0016 | 2 |
| E45-D01 | Task | Wireframe the reconciliation and drill surfaces | 3 |
| E45-D02 | Task | Hi-fi designs and handoff for the discrepancy resolution flow | 3 |
| E45-D03 | Task | Design QA and accessibility review of the shipped surfaces | 2 |
| E45-Q01 | Task | Black-box test plan for reconciliation and the drills | 3 |
| E45-Q02 | Task | Chaos game-day execution and exploratory charter | 3 |
| E45-Q03 | Task | E2E additions, regression pack and QA sign-off | 3 |
| E45-X01 | Task | STRIDE threat model for reconciliation, chaos and failover | 2 |
| E45-X02 | Task | Security review, abuse cases and detection rules | 3 |

Engineering total **48 pts** (budget 47, within +-15%); design 8, QA 9, security 5 tracked separately. Epic estimate 72 = sum of all children.

## Acceptance criteria
```gherkin
Scenario: Chaos suite is green before the R4 gate
  Given every scenario in docs/plan/03-testing-strategy.md section 9 is automated
  When the @chaos CI job runs on the release candidate
  Then every scenario passes and the run report is archived as a release artefact

Scenario: A drill leaves no uncertainty behind
  Given the private WS is dropped mid-order-lifecycle during a drill
  When reconciliation completes after reconnect
  Then oms_unknown_orders returns to 0, no order_link_id maps to two exchange orders, and every open position carries a native stop

Scenario: An unresolvable failure blocks the gate
  Given any chaos scenario ends with an orphaned order or an unprotected position
  Then the R4 gate is blocked, a risk-register entry is opened, and the epic cannot be closed
```

## Technical notes / design
- Reconciler module: `apps/backend/src/candleviewer/oms/reconciler.py`, matching the `Reconciler` component of `docs/plan/20-architecture.md` section 3.5 and running in the `oms` TaskGroup (section 7 process model) as one task per account plus one reconciler task.
- `gap_from = min(last_private_ws_message_ts, last_successful_reconcile_ts) - 5s`.
- Rate budget: all reconciliation REST calls use the `poll` bucket (20 % / about 2 req/s per UID, `docs/plan/20-architecture.md` section 4.3); reconciliation must never starve the `critical` bucket.
- Chaos harness lives in `tests/chaos/` as a pytest plugin plus a docker-compose profile; faults are injected at four layers - mock-exchange responses, network, container lifecycle and host (clock, disk).
- Error codes referenced: `10002` clock drift, `10018` rate limit, `110001` order does not exist, `110079` not yet final; internal `UNRESOLVED_AFTER_RECONCILE`, `DEMO_RETENTION_EXPIRED`, `RATE_BUDGET_EXCEEDED`.

## Test plan
Authored in E45-Q01/Q02/Q03. Epic level: the chaos catalogue is this epic's own regression pack; coverage for `oms/reconciler` and the adapter fault paths must be **>=90 %** (R4 quality gate: security-relevant modules M2/M14/M17/M18/M19 held >=90 %).

## Security notes
Threats: anything that can suppress reconciliation hides an unprotected position; adopted `untracked` orders are exchange-controlled input into our state; drills run with real credentials could cancel real orders; a support bundle produced during a drill can leak keys. Controls: SR-058, SR-083, SR-154; drills are gated by E44's typed environment; `untracked` orders are never rule-managed; every resolution action is step-up-gated and audited. Data classification: OMS state is financial data, high sensitivity.

## Accessibility notes
The new admin surfaces (SCR-143/SCR-144 additions and the discrepancy resolution flow) meet WCAG 2.2 AA: real table semantics, status conveyed as text not colour, keyboard-operable resolution actions, `role="alertdialog"` for destructive confirmations. Covered by E45-D03 and E45-Q03.

## Performance notes
A full reconciliation pass across six accounts completes in <=3 s p95 and consumes <=20 % of the `poll` budget; RTO from backend restart to fully reconciled trading <=90 s (`docs/plan/20-architecture.md` section 11); the 30 s timer adds <=1 % CPU.

## Observability
New metrics: `oms_reconcile_duration_seconds`, `oms_reconcile_corrections_total{kind}`, `oms_untracked_orders`, `oms_position_drift_total`, `oms_reconcile_failures_total{account}`, `oms_stale_accounts`, `chaos_scenario_result{scenario}`. Audit: `oms.reconcile`, `oms.untracked_adopted`, `oms.untracked_resolved`, `drill.executed`. Incidents written to `system_events` (component `oms`) and surfaced on SCR-144.

## Definition of Done
- [ ] All child tickets Done; engineering, design, QA and security sign-offs recorded.
- [ ] Chaos suite green in CI and in a staging game-day; report archived.
- [ ] Rollback and restore drills executed and timed; times recorded in the release ticket.
- [ ] ADR-0016 merged; runbooks written and read through by the on-call rotation.
- [ ] Coverage >=90 % on `oms/reconciler` and the adapter fault paths.
- [ ] Storybook entries for any changed component states; docs updated.
- [ ] Demoed to the Owner at a Sprint Review with explicit acceptance recorded.
- [ ] `docs/plan/32-risk-register.md` updated with any new failure mode discovered.

## Dependencies
- **E29** OMS core and order state machine - the state machine, `order_link_id` idempotency and the `Unknown` state this epic resolves.
- **E34** Trade-group fan-out and rate-limit governor - trade-group legs and the rate buckets reconciliation must live inside.
- **E32** brackets and the native SL invariant - the invariant reconciliation repairs.
- **E39** risk caps, lockouts and kill-switch - exercised by the chaos scenarios and by the dead-man's-switch policy.
- **E44** live-enablement gating and environment separation - drills must run against a live-shaped deployment safely.
- **E04** observability baseline - metrics, alert routing and `system_events` this epic emits into.
- **E42** admin screens - SCR-143 and SCR-144, which E45 extends.

## Branch
`feat/e45-reconciliation-chaos` umbrella; each child ships its own `feat/e45-<short>` branch, PRs <=400 LOC.

## References
- `docs/plan/30-release-roadmap.md` section 8 (R4), section 11.1 dependency graph
- `docs/plan/24-internal-schemas.md` sections 8.3-8.6
- `docs/plan/27-adrs/ADR-0006-oms-state-machine.md`, `ADR-0008-trade-group-fanout.md`
- `docs/plan/20-architecture.md` sections 3.5, 4.3, 7, 11, 12
- `docs/plan/03-testing-strategy.md` sections 9, 9.1
- `docs/plan/04-security-program.md` SR-058, SR-083, SR-154
- `docs/plan/11-user-stories.md` section 28 (OBS), US-POS-008
- `docs/plan/21-database-schema.md` sections 3.6-3.10, 8
- `docs/plan/14-screens-catalogue.md` SCR-143, SCR-144, SCR-152, SCR-063

## Children dependency graph
```mermaid
graph TD
  K01[E45-K01 Spike fault injection] --> T06[E45-T06 Chaos harness]
  X01[E45-X01 STRIDE] --> T01[E45-T01 Reconcile core]
  T01 --> T02[E45-T02 Triggers and stale lockout]
  T01 --> T03[E45-T03 Report, API, metrics]
  T01 --> T04[E45-T04 Balances and trade groups]
  T02 --> T05[E45-T05 Dead-mans-switch]
  T06 --> T07[E45-T07 Chaos part 1]
  T06 --> T08[E45-T08 Chaos part 2]
  T02 --> T07
  T04 --> T08
  T06 --> T09[E45-T09 Rollback rehearsal]
  T09 --> T10[E45-T10 Restore drills]
  T03 --> S01[E45-S01 Resolve untracked and drift]
  D02[E45-D02 Hi-fi and handoff] --> S01
  T03 --> S02[E45-S02 Health and incident surfacing]
  D02 --> S02
  D01[E45-D01 Wireframes] --> D02
  S01 --> D03[E45-D03 Design QA and a11y]
  S02 --> D03
  T05 --> T11[E45-T11 Runbooks and ADR-0016]
  T10 --> T11
  Q01[E45-Q01 Black-box plan] --> Q02[E45-Q02 Game-day and exploratory]
  T07 --> Q02
  T08 --> Q02
  S01 --> Q03[E45-Q03 E2E, regression, sign-off]
  Q02 --> Q03
  T05 --> X02[E45-X02 Security review]
  S01 --> X02
```
"""

TICKETS = [mk(
    key="E45", kind="Epic",
    title="Reconciliation, chaos & failover resilience",
    labels=["type/feature", "area/backend-platform", "priority/p0", "qa", "security", "perf", "design"],
    component="api", phase=PH, sprint="Sprint 21", priority="P0 Critical",
    perspective="Architecture", risk="R3 Real-time cost", estimate=72, parent=None,
    blocked_by=["E29", "E34", "E32", "E39", "E44", "E04", "E42"], milestone=MS, body=EPIC_BODY)]

if __name__ == "__main__":
    dump("_e45_a.json", TICKETS)
