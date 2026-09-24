# -*- coding: utf-8 -*-
"""E45 engineering part 1: K01, T01-T05 (reconciliation service)."""
from _e45_common import mk, dump, MS, PH

AREA = "area/backend-platform"
T = []

T.append(mk(
    key="E45-K01", kind="Spike",
    title="Choose the fault-injection mechanism for the chaos harness",
    labels=["type/spike", AREA, "priority/p1", "qa"],
    component="infra", phase=PH, sprint="Sprint 21", priority="P1 High",
    perspective="Architecture", risk="R3 Real-time cost", estimate=2, parent="E45",
    blocked_by=["E03", "E29"], milestone=MS,
    body="""## Context
`docs/plan/03-testing-strategy.md` section 9 mandates chaos tests "automated where feasible (fixture-replay mock exchange + network-fault injection)" running as a dedicated CI job `@chaos`. It does not say *how* the network, container, clock and disk faults are injected. That choice determines whether the chaos suite is a 5-point harness or a 20-point one, so it is decided once, here, before E45-T06 starts building.

The harness must work in three places with the same scenario definitions: a developer laptop (WSL Ubuntu, docker compose), CI (ephemeral docker-compose, `docs/plan/03-testing-strategy.md` section 12 environment matrix) and a staging game-day (WSL Ubuntu / early VPS). Anything that needs a Kubernetes control plane is therefore out - CandleViewer is a docker-compose modular monolith (`docs/plan/27-adrs/ADR-0004-modular-monolith.md`).

## Scope / Deliverables
- A timeboxed **3-day** investigation producing `docs/plan/27-adrs/ADR-0016-resilience-and-chaos.md` in *proposed* status (E45-T11 moves it to *decided*) plus a throwaway proof-of-concept branch `spike/e45-fault-injection`.
- Evaluate, against the four fault layers required by the section 9 catalogue:
  1. **Exchange-response faults** (5xx, 403, `10018`, `110001`, malformed payloads, doctored `seq` gaps) - candidate: extend the existing fixture-replay mock exchange from E08 with a scriptable fault profile.
  2. **Network faults** (drop, latency, partition, half-open TCP on the public and private WS) - candidates: toxiproxy as a compose sidecar; `tc netem` inside the container; an in-process transport shim in the adapter.
  3. **Container lifecycle** (Postgres stop/start, QuestDB unavailability) - candidates: docker SDK from the test process; compose profiles; `pytest-docker`.
  4. **Host faults** (clock skew for `10002`, disk-full for the recorder) - candidates: `libfaketime`, a per-container `TZ`/offset env the adapter honours in test builds, a tmpfs volume with a fixed size for disk-full.
- For each candidate answer: can it run unprivileged in CI? Is it deterministic and repeatable? Does it require production code changes (and if so, are those changes test-only and fenced)? How is the fault *asserted* to have actually occurred?
- Decide whether clock skew is injected at the host or simulated by the adapter's server-time offset, given that `docs/plan/24-internal-schemas.md` maps `10002` and `docs/plan/20-architecture.md` section 11 F-mode requires order entry to block on drift.
- Produce the **scenario definition format** (a declarative YAML/py dataclass) that E45-T07/T08 will author scenarios in.

## Out of scope
- Writing the actual scenarios (E45-T07, E45-T08).
- Building the harness (E45-T06).
- Load and soak testing (E46).

## Acceptance criteria
```gherkin
Scenario: A recommendation exists with evidence
  Given the spike is complete
  Then ADR-0016 (proposed) names one mechanism per fault layer, with the rejected options and the reason for each

Scenario: The proof of concept actually injects a fault
  Given the PoC branch is run in CI
  Then at least one scenario per layer is demonstrated end to end - private WS dropped, Postgres stopped, clock skewed, exchange returning 10018 - and each injection is observable in the run log

Scenario: CI feasibility is proven, not assumed
  Given the PoC runs on the standard CI runner without privileged containers
  Then it passes; if any layer requires privilege, the ADR states the mitigation or the fallback to a manual game-day step

Scenario: The spike fails to find a CI-safe mechanism
  Given no candidate can inject a given fault layer in CI
  Then the ADR records that layer as manual game-day only, E45-Q02 absorbs it, and a risk-register entry is opened
```

## Technical notes / design
- Existing assets to build on: the fixture-replay mock exchange (E08), the recorded Bybit fixtures (`docs/plan/03-testing-strategy.md` section 6), the compose stack from E03.
- Scenario definition sketch:
```python
@dataclass(frozen=True)
class ChaosScenario:
    id: str                    # "ws_private_drop_mid_lifecycle"
    layers: list[FaultSpec]    # ordered injections with relative timings
    workload: str              # name of the workload fixture to run under fault
    assertions: list[str]      # named assertion functions
    expected_recovery_s: float # from 20-architecture.md section 11 (RTO <= 90 s)
```
- Any test-only hook added to production code must be behind an explicit `CV_CHAOS_ENABLED` setting that is **refused when `environment == "live"`** (E44's typed environment) - state this in the ADR.

## Test plan
Spike, so the deliverable is evidence, not coverage: the PoC must include one runnable pytest per fault layer and its CI run logs attached to the ticket. No coverage requirement.

## Security notes
The central threat is a chaos hook shipping to production and being reachable by an attacker (STRIDE: Tampering, Denial of Service). The ADR must specify the fence: test-only extras group, refused under `live`, absent from the production container image, and asserted by a CI test. Reviewed in E45-X01. Data classification: none (fixtures only).

## Accessibility notes
N/A - no UI surface.

## Performance notes
The harness must not distort the measurements it takes: record the overhead of the chosen injection mechanism on a no-fault baseline run and state it in the ADR; target <=5 % added latency on the order path when no fault is active.

## Observability
The PoC must demonstrate that each injected fault produces a `system_events` row (component `oms`, `exchange`, `db` as appropriate) so that game-day evidence is derivable from the product's own telemetry, not just the test log.

## Definition of Done
- [ ] ADR-0016 written in *proposed* status and reviewed by the Architect and DevSecOps.
- [ ] PoC branch pushed, CI run links attached, branch marked throwaway and left unmerged.
- [ ] Findings presented at Sprint Review.
- [ ] `docs/plan/32-risk-register.md` updated if a fault layer turns out to be un-automatable.
- [ ] Scenario definition format agreed by QA (E45-Q01 author) and the backend lead.

## Dependencies
- **E03** CI/CD pipeline and environments - the compose stack and CI runners the harness must live in.
- **E29** OMS core - the order path being faulted must exist to be faulted.

## Branch
`spike/e45-fault-injection` (throwaway, unmerged). PR size: N/A, ADR PR only.

## References
- `docs/plan/03-testing-strategy.md` sections 9, 9.1, 12
- `docs/plan/20-architecture.md` section 11 (failure modes F1-F9, RTO)
- `docs/plan/04-security-program.md` SR-154
- `docs/plan/27-adrs/ADR-0004-modular-monolith.md`
"""))

T.append(mk(
    key="E45-T01", kind="Task",
    title="Implement the reconciliation core over orders, executions and positions",
    labels=["type/feature", AREA, "priority/p0", "security"],
    component="api", phase=PH, sprint="Sprint 21", priority="P0 Critical",
    perspective="Development", risk="R3 Real-time cost", estimate=5, parent="E45",
    blocked_by=["E29", "E32", "E45-X01"], milestone=MS,
    body="""## Context
`docs/plan/24-internal-schemas.md` section 8.5 specifies the reconciliation algorithm in executable pseudo-code; `docs/plan/27-adrs/ADR-0006-oms-state-machine.md` makes reconciliation the **only** route out of the `Unknown` state ("there is no blind resubmission"); **SR-058** (`docs/plan/04-security-program.md`) makes it a security requirement. E29 delivered the OMS state machine and a reconnect-triggered refresh; this ticket delivers the **complete algorithm as a single, idempotent, testable function** so that everything else in E45 (triggers, reports, chaos assertions) has one correct implementation to call.

This is the highest-stakes non-UI code in the product: it decides that an order the user believes exists does not, or that a position we have never seen is now ours.

## Scope / Deliverables
- `apps/backend/src/candleviewer/oms/reconciler.py` implementing `async def reconcile(account: AccountRef, gap_from: TsUs) -> ReconcileReport` exactly per `docs/plan/24-internal-schemas.md` section 8.5:
  1. Fetch authoritative snapshots via the M4 adapter: `GET /v5/order/realtime`, `GET /v5/position/list`, `GET /v5/execution/list` for `[gap_from, now]`.
  2. **Apply every execution first**, sorted by `(ts_exec, seq)`, deduped by `exec_id`.
  3. Diff open orders by `order_link_id` into four buckets: present-both (adopt exchange state), local-only (resolve from `GET /v5/order/history`, else `Unknown`, else abandon after two passes with `reject_code=UNRESOLVED_AFTER_RECONCILE`), remote-only (adopt as `untracked`), and unchanged.
  4. Positions: exchange is truth; record drift beyond `qty_step`.
  5. Re-check the native-SL invariant (ADR-0008) and call `attach_protective_sl(p, reason="reconcile_missing_sl")` for any open position without a stop.
- `ReconcileReport` dataclass with `corrected`, `resolved_from_history`, `newly_unknown`, `abandoned`, `untracked`, `position_drift`, `sl_repaired`, `gap_window`, `duration_ms`, `errors`.
- Demo-retention rule: an `order_link_id` older than 6 days on `demo` is unresolvable-by-history and is closed as `Rejected` with `reject_code=DEMO_RETENTION_EXPIRED` (`docs/plan/24-internal-schemas.md` section 8.4 rule 6).
- All REST calls issued through the `poll` token bucket (`docs/plan/20-architecture.md` section 4.3) so reconciliation can never starve the `critical` bucket.
- Error handling: `110001` (order does not exist) on a resolution lookup is treated as already-terminal; `110079` (not yet final) causes the order to stay non-terminal and be retried next pass; a `RateLimitError` aborts the pass cleanly and returns a partial report flagged `errors`.
- Unit-test fixture set of recorded Bybit responses covering each bucket.

## Out of scope
- Scheduling and triggering (E45-T02) - this ticket exposes a callable, nothing calls it yet.
- Persistence, API exposure and metrics (E45-T03).
- Wallet balances and trade-group legs (E45-T04).
- Any UI (E45-S01, E45-S02).

## Acceptance criteria
```gherkin
Scenario: A fill that arrived while disconnected resolves its order without a history lookup
  Given a local order in state Submitted whose fill occurred during the gap window
  When reconcile runs
  Then the execution is applied first, the order reaches Filled, and no GET /v5/order/history call is made for it

Scenario: An unknown order is abandoned only after two passes
  Given a local order in state Unknown that the exchange does not know in realtime or history
  When reconcile runs once
  Then the order remains Unknown with unknown_passes = 1 and appears in report.newly_unknown or is left pending
  When reconcile runs a second time
  Then the order transitions to Rejected with reject_code UNRESOLVED_AFTER_RECONCILE and appears in report.abandoned

Scenario: An exchange order we never created is adopted, not executed against
  Given the exchange reports an open order whose order_link_id has no local row
  When reconcile runs
  Then a local row is created in state untracked, it is flagged as never rule-managed, and it appears in report.untracked

Scenario: A position without a native stop is repaired
  Given the exchange reports an open position with qty > 0 and stop_loss null
  When reconcile runs
  Then attach_protective_sl is called with reason reconcile_missing_sl and the symbol appears in report.sl_repaired

Scenario: Idempotency
  Given reconcile has just completed successfully
  When reconcile runs again immediately with the same gap_from
  Then the second report is empty in every correction bucket

Scenario: Rate-limit failure mid-pass
  Given the exchange returns 10018 on the position-list call
  When reconcile runs
  Then no partial state is committed for the failed dimension, the report carries an errors entry, and the pass is retried by the caller rather than silently succeeding

Scenario: Demo retention
  Given the environment is demo and an Unknown order's order_link_id is 7 days old
  When reconcile runs
  Then the order is closed as Rejected with reject_code DEMO_RETENTION_EXPIRED
```

## Technical notes / design
- `gap_from = min(last_private_ws_message_ts, last_successful_reconcile_ts) - 5s`; the 5 s overlap is free because execution application is deduped by `exec_id`.
- The function must be **pure with respect to scheduling**: it takes `gap_from`, does its work, returns a report. No timers, no retries of itself.
- Transitions go through the existing `OrderStateMachine.apply()` from E29 so invariant S6 ("terminal states are immutable; a post-terminal exchange push raises `ReconcileAnomaly`") is honoured; a `ReconcileAnomaly` is caught, recorded in `report.errors`, audited and alerted, and does not mutate the order.
- Concurrency: one reconciliation pass per account at a time, guarded by a per-account asyncio lock; a pass must not run while a fan-out is mid-flight for that account (E34 admission control), otherwise a child order that has been sent but not acknowledged looks like a remote-only order.
- Structured logging with the correlation id of the pass and, per correction, the `order_link_id` (the universal correlation key, `docs/plan/24-internal-schemas.md` section 8.4).

## Test plan
- **Unit** (target >=95 % on this module, epic gate >=90 %): one test per bucket per scenario above; execution-dedup by `exec_id`; sort stability on equal `ts_exec`; `qty_step` boundary for drift (exactly at step = no drift, one increment above = drift); `ReconcileAnomaly` path; the demo-retention boundary at exactly 6 days.
- **Contract**: the adapter calls used are asserted against the recorded Bybit fixtures so a response-shape change breaks the test rather than production.
- **Integration**: against the fixture-replay mock exchange, a full pass over a seeded book of 50 orders, 3 positions and 200 executions across 2 accounts; assert idempotency by running twice.
- **Property test**: for a randomly generated pair of (local state, remote state), the post-conditions hold - no order is both terminal and open, no open position lacks a stop, every remote open order has a local row.
- Fixtures: `tests/fixtures/bybit/reconcile_*.json` (new), reusing the E08 recorded-fixture conventions.

## Security notes
SR-058 is implemented here. Threats (STRIDE, detailed in E45-X01): **Tampering** - a malicious or buggy exchange response adopts a fabricated position; mitigated by adopting only into `untracked` with no rule management and by auditing every adoption. **Repudiation** - corrections must be attributable, so every correction writes an audit event with before and after values (E45-T03). **Information disclosure** - reports must not carry API keys or signatures; the redaction serialiser from E04 applies. Data classification: financial, high. This ticket requires the `security` label and a Security-engineer review.

## Accessibility notes
N/A - no UI surface.

## Performance notes
A full pass for one account with 50 open orders completes in <=500 ms p95 excluding network; six accounts in <=3 s p95 in total; the pass consumes at most 3 REST calls per account per run, well inside the `poll` bucket's ~2 req/s (`docs/plan/20-architecture.md` section 4.3). Benchmark recorded in CI as a non-blocking trend.

## Observability
Emits (wired fully in E45-T03): `oms_reconcile_duration_seconds` histogram, `oms_reconcile_corrections_total{kind}` counter, `oms_unknown_orders` gauge (already defined in `docs/plan/20-architecture.md` section 12, alert >0 for 60 s), `oms_untracked_orders` gauge, `oms_position_drift_total`. Log lines carry `account_id`, `order_link_id`, `gap_window`.

## Definition of Done
- [ ] Code merged with >=90 % line coverage on the module (target 95 %).
- [ ] Unit, contract, integration and property tests green.
- [ ] Security-engineer review recorded (SR-058 traceability updated).
- [ ] `docs/plan/24-internal-schemas.md` section 8.5 confirmed to match the implementation, or a documented delta PR raised.
- [ ] Code-owner review from the backend lead plus one other approval.
- [ ] No demo required (no observable effect yet); behaviour demoed as part of E45-T02.

## Dependencies
- **E29** OMS core - `OrderStateMachine`, order/position tables, the `Unknown` state.
- **E32** brackets and native SL invariant - `attach_protective_sl`.
- **E45-X01** STRIDE model - must exist before this ticket enters Ready (epic-level security gate).

## Branch
`feat/e45-reconcile-core`. Expect ~350 LOC plus tests; split the property tests into a follow-up PR if the diff exceeds 400 LOC.

## References
- `docs/plan/24-internal-schemas.md` sections 8.3, 8.4, 8.5, 8.6
- `docs/plan/27-adrs/ADR-0006-oms-state-machine.md`, `ADR-0008-trade-group-fanout.md`
- `docs/plan/04-security-program.md` SR-058
- `docs/plan/20-architecture.md` sections 3.5, 4.3
- `docs/plan/11-user-stories.md` US-POS-008
"""))

T.append(mk(
    key="E45-T02", kind="Task",
    title="Drive reconciliation from startup, reconnect, timer and on demand; stale-account lockout",
    labels=["type/feature", AREA, "priority/p0", "security"],
    component="api", phase=PH, sprint="Sprint 21", priority="P0 Critical",
    perspective="Development", risk="R3 Real-time cost", estimate=3, parent="E45",
    blocked_by=["E45-T01"], milestone=MS,
    body="""## Context
`docs/plan/20-architecture.md` section 3.5 specifies the `Reconciler` as running **on startup, on reconnect and every 30 s**; `docs/plan/24-internal-schemas.md` section 8.5 adds **on demand from the admin screen**; US-POS-008 adds the failure branch: *"Given REST reconciliation fails repeatedly for 2 minutes, then affected accounts are marked stale and order entry for them is disabled"*. E45-T01 produced the callable; this ticket makes it actually run, and makes the system fail closed when it cannot.

The startup path also owns the RTO commitment: **<=90 s from backend restart to fully reconciled trading** (`docs/plan/20-architecture.md` section 11 F7).

## Scope / Deliverables
- A `ReconcilerService` task in the `oms` TaskGroup (`docs/plan/20-architecture.md` section 7): one driver task per configured exchange account plus one supervisor.
- Four triggers, all funnelling into the same per-account lock:
  1. **Startup** - after the key self-check, before rules are re-armed. Rules stay disarmed until the first successful pass completes for every account (F7).
  2. **Private-WS reconnect** - subscribed to the adapter's reconnect event; runs before the account resumes accepting order entry.
  3. **Timer** - every 30 s, jittered per account to avoid a thundering herd across six accounts.
  4. **On demand** - `POST /api/v1/admin/...` trigger wired in E45-T03; this ticket exposes the internal entry point and the idempotency guard.
- **Stale-account state machine**: consecutive pass failures start a 120 s window; on expiry the account is marked `stale`, order entry for it is refused with a distinct error, a `critical` `system_events` row is written and a `system` WS frame is broadcast. A single successful pass clears `stale` and re-enables entry, with both transitions audited.
- Back-pressure: if a pass is still running when the timer fires, the timer tick is skipped (never queued) and counted.
- Interaction with the kill-switch (E39): while the kill-switch is engaged, reconciliation keeps running (we still want truth) but the SL-repair step is still permitted, because it is risk-reducing - state this explicitly in code and tests.
- Interaction with fan-out (E34): a pass defers while an admission-controlled fan-out is in flight for that account, up to a 10 s cap, after which it runs anyway and treats in-flight children as expected remote-only orders.

## Out of scope
- The report persistence/API/metrics surface (E45-T03).
- The admin UI button that calls the on-demand trigger (E45-S02).
- The dead-man's-switch (E45-T05).

## Acceptance criteria
```gherkin
Scenario: Startup blocks arming until reconciled
  Given the backend restarts with two configured accounts and three open positions
  When it boots
  Then reconciliation runs for both accounts before any armed rule evaluates, and the boot-to-reconciled time is recorded and is under 90 seconds

Scenario: Reconnect triggers a pass before order entry resumes
  Given the private WS drops and reconnects
  When the reconnect event fires
  Then a reconciliation pass runs for that account and order entry for it is refused until the pass completes

Scenario: Timer cadence and jitter
  Given six accounts are configured
  Then each account is reconciled every 30 seconds plus a per-account jitter under 5 seconds, and no two accounts start a pass in the same 200 ms window

Scenario: Overlapping passes are skipped, not queued
  Given a pass for account A is still running when its timer fires
  Then the tick is skipped and oms_reconcile_skipped_total increments, and no second concurrent pass starts

Scenario: Stale-account lockout
  Given every reconciliation pass for account A has failed for 120 seconds
  Then account A is marked stale, new order entry for it is refused with a distinct error, a critical system event is written and a system WS frame is broadcast
  When one pass subsequently succeeds
  Then the stale flag clears, order entry is re-enabled and both transitions are audited

Scenario: Reconciliation continues under the kill-switch
  Given the kill-switch is engaged globally
  When the timer fires
  Then reconciliation still runs and a missing native stop is still repaired, because that action is risk-reducing
```

## Technical notes / design
- Config keys (M1 settings, `docs/plan/24-internal-schemas.md` section 16): `oms.reconcile.interval_s` (default 30), `oms.reconcile.jitter_s` (default 5), `oms.reconcile.stale_after_s` (default 120), `oms.reconcile.fanout_defer_cap_s` (default 10), `oms.reconcile.startup_timeout_s` (default 75, inside the 90 s RTO).
- Stale state lives on the account row and in memory; it is **not** persisted as a config change - it is an operational state that must not survive a restart unverified, so on boot every account starts `unknown` and becomes healthy only after its first successful pass.
- Order-entry refusal uses the existing OMS pre-trade guard chain (E29/E39) with a new reason `account_stale`, surfaced to the UI as a distinct message per SCR-063's desync/stale states.
- Startup ordering, explicitly: config load -> key self-check (E44) -> adapter connect -> reconcile all accounts -> re-arm rules -> accept order entry.

## Test plan
- **Unit**: trigger de-duplication; jitter distribution; skip-not-queue behaviour; stale timer boundaries at 119 s and 121 s; clearing on success; fan-out defer cap.
- **Integration** (fixture-replay mock exchange): restart with open positions, assert rules do not evaluate before reconciliation completes; drop the private WS and assert order entry is refused during the pass; force 120 s of failures and assert the stale transition and the WS broadcast.
- **Chaos** (consumed by E45-T07): the private-WS drop mid-lifecycle sequence of `docs/plan/03-testing-strategy.md` section 9.1 must pass end to end using this scheduler.
- **Perf**: measure boot-to-reconciled with six accounts and 200 open orders; assert <=90 s.
- Coverage target >=90 % on the service module.

## Security notes
Failing **closed** is the security property here: SR-058 plus `docs/plan/04-security-program.md` SR-154's requirement that the system "fails closed on the order path" while risk-reducing actions still work. Threats: a suppressed or silently crashed reconciler task leaves the system trading on stale truth (Denial of service / Tampering) - mitigated by a supervisor that restarts the task and alerts, and by the stale timer which is driven by *time since last success*, not by task liveness. Every stale transition is audited. Data classification: financial, high.

## Accessibility notes
N/A - no UI surface; the states it produces are rendered by E45-S02 and by SCR-063/SCR-152 (E29).

## Performance notes
Scheduler overhead <=1 % CPU at the 30 s cadence for six accounts; boot-to-reconciled <=90 s (RTO, `docs/plan/20-architecture.md` section 11); a skipped tick must be cheap (no REST calls).

## Observability
`oms_reconcile_skipped_total`, `oms_reconcile_failures_total{account}`, `oms_stale_accounts` gauge, `oms_boot_to_reconciled_seconds` on startup. Alerts: `oms_stale_accounts > 0` pages; `oms_reconcile_failures_total` rate ticket. Audit: `oms.account_stale`, `oms.account_recovered`. `system_events` rows at `critical` for stale, `info` for recovery.

## Definition of Done
- [ ] Merged with >=90 % coverage on the module; all tests green including the section 9.1 sequence.
- [ ] Boot-to-reconciled measured and recorded in the ticket.
- [ ] Runbook stub for "account marked stale" filed for E45-T11.
- [ ] Security review recorded.
- [ ] Demoed: restart the backend with open positions and show the boot sequence and the reconciled state.

## Dependencies
- **E45-T01** - the callable being scheduled.
- **E29** pre-trade guard chain; **E39** kill-switch interaction; **E34** fan-out admission control.

## Branch
`feat/e45-reconcile-triggers`. ~250 LOC plus tests.

## References
- `docs/plan/20-architecture.md` sections 3.5, 7, 11
- `docs/plan/24-internal-schemas.md` section 8.5
- `docs/plan/11-user-stories.md` US-POS-008
- `docs/plan/03-testing-strategy.md` section 9.1
- `docs/plan/14-screens-catalogue.md` SCR-063 (stale/desync states), SCR-152
"""))

T.append(mk(
    key="E45-T03", kind="Task",
    title="Persist, expose and instrument the reconciliation report",
    labels=["type/feature", AREA, "priority/p0", "perf"],
    component="api", phase=PH, sprint="Sprint 21", priority="P0 Critical",
    perspective="Development", risk="R3 Real-time cost", estimate=3, parent="E45",
    blocked_by=["E45-T01", "E04"], milestone=MS,
    body="""## Context
`docs/plan/24-internal-schemas.md` section 8.5 ends with: *"Every report is persisted and shown on the admin System health -> OMS screen."* A reconciliation that corrects state without leaving a record is indistinguishable from a bug, and US-POS-008 requires that *"the divergence is audited with both values"*. This ticket turns the in-memory `ReconcileReport` of E45-T01 into durable, queryable, alertable evidence and gives the UI (E45-S01, E45-S02) something to read.

## Scope / Deliverables
- **Persistence** (Postgres, per `docs/plan/21-database-schema.md`):
  - A `reconcile_reports` table (migration): `id`, `exchange_account_id`, `trigger` (`startup|reconnect|timer|manual`), `started_at`, `finished_at`, `duration_ms`, `gap_from`, `gap_to`, counts per bucket, `ok` boolean, `error` jsonb, `detail` jsonb (the full report).
  - Per-correction rows into the existing `order_events` with `source='reconcile'` and `kind='reconcile_diff'`, carrying before/after values.
  - `position_snapshots` rows with `reason='rest_reconcile'`.
  - Watermark updates: `orders.last_reconciled_at`, `positions.last_reconciled_at`.
  - Audit event `oms.reconcile` with the report summary (append-only audit log, hash-chained, `docs/plan/21-database-schema.md` section 3.10).
  - `system_events` rows (component `oms`) at `warning` for any correction, `critical` for position drift beyond `qty_step` or an abandoned order - these feed `GET /api/v1/admin/incidents` and SCR-144.
- **API**: extend the existing `GET /api/v1/admin/health` `HealthReport` OMS component detail (today `"0 unreconciled orders"`) with structured reconciliation fields - last pass time per account, untracked count, drift count, stale accounts - and add the on-demand trigger and report history under the admin surface, returning `202` with a `job_id` pollable via the existing `GET /api/v1/admin/jobs/{jobId}` (`kind: reconciliation` is already an allowed job kind in `docs/plan/22-api-openapi.yaml`). OpenAPI delta merged **before** the consuming FE stories, per the interface-first rule in `docs/plan/02-definition-of-ready-done.md`.
- **WS**: reconciliation state changes broadcast on the auto-subscribed `system` topic (`docs/plan/23-ws-protocol.md` section on `system`) as an `exchange_state`-shaped notice so every client learns about stale accounts and in-progress reconciliation without polling.
- **Metrics** (Prometheus, via the E04 facade): `oms_reconcile_duration_seconds`, `oms_reconcile_corrections_total{kind}`, `oms_untracked_orders`, `oms_position_drift_total`, `oms_reconcile_failures_total{account}`, `oms_stale_accounts`, and the already-specified `oms_unknown_orders` (alert >0 for 60 s, `docs/plan/20-architecture.md` section 12).
- **Alert rules** as version-controlled configuration (US-OBS-004 NFR): unknown orders >0 for 60 s (page), stale account >0 (page), position drift (page), correction rate elevated (ticket) - each with a runbook link.
- Retention: `reconcile_reports` kept 90 days, then summarised; stated in `docs/plan/21-database-schema.md`'s retention table via a docs PR.

## Out of scope
- The UI that renders any of this (E45-S01, E45-S02).
- Alert *delivery* channels (E04/E40).
- The chaos harness (E45-T06).

## Acceptance criteria
```gherkin
Scenario: Every pass leaves a record
  Given a reconciliation pass completes with two corrections
  Then a reconcile_reports row exists with the correct trigger, gap window and bucket counts, two order_events rows exist with source reconcile and kind reconcile_diff carrying before and after values, and one oms.reconcile audit entry is written

Scenario: A clean pass is cheap
  Given a reconciliation pass completes with no corrections
  Then a reconcile_reports row is written with zero counts, no order_events rows are created, and no system_events row is created

Scenario: Position drift raises a critical incident
  Given reconciliation finds a position quantity differing from the exchange by more than qty_step
  Then a critical system_events row is written, it appears in GET /api/v1/admin/incidents, and the position-drift alert fires

Scenario: On-demand trigger is idempotent and observable
  When an owner triggers reconciliation on demand for an account that is already mid-pass
  Then the API returns the in-flight job id rather than starting a second pass, and the job is pollable at GET /api/v1/admin/jobs/{jobId}

Scenario: Clients learn about stale accounts without polling
  Given an account transitions to stale
  Then a system WS frame is broadcast within 2 seconds to every connected session, including sessions with no admin permission, with content filtered by role

Scenario: No secrets in the record
  Given a report contains an exchange error payload
  Then the persisted detail and the audit entry contain no API key, signature or token, verified by the serialiser allow-list test
```

## Technical notes / design
- Migration is additive and backward-compatible (the rollback rehearsal in E45-T09 will assert this): new table plus new nullable columns only, no destructive change, so the previous release can run against the new schema.
- Report `detail` jsonb is capped (e.g. 256 KB); beyond the cap the buckets are truncated with an explicit `truncated: true` marker rather than silently dropped - the same rule the support bundle uses in US-OBS-007.
- Metric cardinality is bounded per `docs/plan/20-architecture.md` section 12: label by `account` (<=6 values) and `kind` (a fixed enum), never by symbol or `order_link_id`.
- Audit entries go through the existing hash-chained audit writer (`docs/plan/21-database-schema.md` section 3.10) so the chain verification in `GET /api/v1/admin/audit/verify` still passes.

## Test plan
- **Unit**: report-to-row mapping for each bucket; truncation at the cap; cardinality guard; redaction of an error payload containing a fake key.
- **Contract**: the OpenAPI delta validated against `docs/plan/22-api-openapi.yaml` in the existing contract-test job; the WS frame validated against the `system` schema in `docs/plan/23-ws-protocol.md`.
- **Integration**: run a pass with seeded divergences and assert every row, metric and audit entry; run a clean pass and assert the cheap path; verify the audit hash chain still verifies afterwards.
- **Migration test**: up and down on a seeded database; assert the previous application version boots against the migrated schema.
- Coverage >=90 % on the new code.

## Security notes
Threats: **Information disclosure** - reports carry exchange payloads which may contain identifiers; enforce the E04 redaction serialiser and an explicit allow-list test. **Repudiation** - corrections must be non-repudiable, hence the hash-chained audit entry. **Elevation of privilege** - the on-demand trigger and report history are `admin:read`/`admin:write` gated with the admin step-up freshness rule (SCR-149, 15 minutes). Data classification: financial, high; the `security` label applies (it touches OMS state).

## Accessibility notes
N/A for this ticket (API and storage only); the consuming screens carry the a11y contract.

## Performance notes
Persisting a clean report costs one insert and <=5 ms; a report with 100 corrections costs <=50 ms and must not be on the critical path of order entry (write asynchronously off the reconciliation task, bounded queue, drop-to-log if the queue is full rather than blocking). `GET /api/v1/admin/health` must stay under its screen budget (SCR-143: tiles resolve independently, page under 2 ms scripting per frame).

## Observability
This ticket *is* the observability of E45; additionally it must emit `oms_reconcile_report_write_failures_total` so a failure to record is itself visible.

## Definition of Done
- [ ] Migration merged and applied in staging; rollback verified.
- [ ] OpenAPI and WS protocol deltas merged and contract tests green.
- [ ] Alert rules merged as configuration with runbook links; one rule test-fired and received (US-OBS-004).
- [ ] Coverage >=90 %; audit-chain verification green after the change.
- [ ] `docs/plan/21-database-schema.md` retention table updated.
- [ ] Demoed on the admin health endpoint output.

## Dependencies
- **E45-T01** - the report being persisted.
- **E04** observability baseline - metrics facade, alert routing, `system_events` writer, redaction serialiser.
- **E42** - owns `GET /api/v1/admin/health` and `/admin/incidents`, which this ticket extends.

## Branch
`feat/e45-reconcile-report`. Migration plus API delta plus metrics; split the alert-rule configuration into a second PR if the diff exceeds 400 LOC.

## References
- `docs/plan/24-internal-schemas.md` section 8.5
- `docs/plan/21-database-schema.md` sections 3.6-3.10, retention table
- `docs/plan/22-api-openapi.yaml` `/admin/health`, `/admin/incidents`, `/admin/jobs/{jobId}`
- `docs/plan/23-ws-protocol.md` `system` topic
- `docs/plan/20-architecture.md` section 12
- `docs/plan/11-user-stories.md` US-OBS-001, US-OBS-004, US-POS-008
"""))

T.append(mk(
    key="E45-T04", kind="Task",
    title="Reconcile wallet balances and trade-group legs",
    labels=["type/feature", AREA, "priority/p1"],
    component="api", phase=PH, sprint="Sprint 21", priority="P1 High",
    perspective="Development", risk="R3 Real-time cost", estimate=3, parent="E45",
    blocked_by=["E45-T01", "E34"], milestone=MS,
    body="""## Context
The roadmap scopes E45's reconciliation service as covering *"orders, positions, balances, trade groups"* (`docs/plan/30-release-roadmap.md` section 8.2). E45-T01 implements the `docs/plan/24-internal-schemas.md` section 8.5 algorithm, which covers orders, executions and positions. This ticket adds the two remaining dimensions.

They matter for different reasons. **Balances** are what risk caps and sizing rules are computed against (E28 profiles, E39 risk caps): a wallet figure that has drifted means position sizing is wrong in a way no order-level check would catch. **Trade-group legs** are the fan-out abstraction (E34, `docs/plan/27-adrs/ADR-0008-trade-group-fanout.md`): a leg whose child order was adopted as `untracked`, or whose account failed mid-fan-out, leaves the group record claiming something untrue, which is exactly what the R4 exit criterion "no position the system is unaware of" forbids.

## Scope / Deliverables
- **Wallet reconciliation**: fetch the account's wallet balance through the M4 adapter, diff against the local balance cache (equity, available balance, unrealised PnL, margin used), and record drift beyond a configured tolerance. Exchange is truth; local is corrected. Drift beyond `oms.reconcile.balance_tolerance_pct` (default 0.5 %) raises a `warning` system event, beyond 2 % a `critical` one - because at that point risk caps are being evaluated against a fiction.
- **Trade-group leg re-binding**: for every non-terminal trade group (`trade_groups` and its legs, `docs/plan/21-database-schema.md`), re-derive each leg's true state from the reconciled orders by `order_link_id` (the id encodes `{group_id}-{account_short}-{seq}`, `docs/plan/27-adrs/ADR-0006-oms-state-machine.md`), and:
  - Re-attach a leg whose child order was resolved from history or adopted during this pass.
  - Mark a leg `failed` whose child order was abandoned as `UNRESOLVED_AFTER_RECONCILE`.
  - Recompute the group's aggregate state (`pending|partial|complete|failed|unwinding`) from its legs rather than trusting the stored value.
  - Detect an **orphan leg**: a group leg with no order row at all; adopt or fail it explicitly, never leave it ambiguous.
- An `untracked` order whose `order_link_id` parses as a trade-group id is **linked for display** to that group but still marked untracked and never rule-managed; `orders.trade_group_leg_id` stays NULL for adopted orders per `docs/plan/21-database-schema.md` ("NULL for orders adopted during reconciliation").
- Extension of `ReconcileReport` with `balance_drift` and `group_corrections` buckets, flowing into the E45-T03 persistence automatically.
- Interaction with the E34 compensating unwind: if a group is `unwinding`, reconciliation reports but does not re-drive it; the unwind plan remains the owner of that group's transitions.

## Out of scope
- Changing how fan-out itself works (E34).
- The trade-group UI (E34-S04/S05); this ticket only corrects the data those screens read.
- Fee/funding reconciliation and closed-PnL accuracy (E41 journal).

## Acceptance criteria
```gherkin
Scenario: Balance drift is corrected and graded
  Given the exchange reports an available balance 1 percent below the local cache
  When reconciliation runs
  Then the local cache is corrected to the exchange value, a balance_drift entry appears in the report and a warning system event is written
  Given the difference is 3 percent
  Then a critical system event is written instead and the alert fires

Scenario: A leg resolved from history is re-attached
  Given a trade-group leg whose child order was in Unknown and is found Filled in order history
  When reconciliation runs
  Then the leg is marked filled, the group aggregate is recomputed, and the correction appears in report.group_corrections

Scenario: An abandoned child fails its leg
  Given a trade-group leg whose child order is abandoned with reject_code UNRESOLVED_AFTER_RECONCILE
  When reconciliation runs
  Then the leg is marked failed, the group aggregate becomes partial or failed accordingly, and the change is audited

Scenario: An orphan leg is never left ambiguous
  Given a trade-group leg with no corresponding order row
  When reconciliation runs
  Then the leg is explicitly resolved as failed with reason orphan_leg and a critical system event is written

Scenario: An adopted untracked order does not silently join a group
  Given the exchange reports an unknown open order whose order_link_id encodes an existing group id
  When reconciliation runs
  Then the order is adopted as untracked with trade_group_leg_id NULL, it is shown against the group for context only, and it is never rule-managed

Scenario: An unwinding group is observed, not driven
  Given a trade group is in state unwinding
  When reconciliation runs
  Then divergences are reported but no leg transition is forced, and the unwind plan remains authoritative
```

## Technical notes / design
- `order_link_id` parsing must be defensive: an id that does not match `{group_id}-{account_short}-{seq}` is simply not a group leg, never an error - the exchange may hold orders created outside CandleViewer.
- Group aggregate recomputation is a pure function `aggregate(legs) -> GroupState`, unit-testable in isolation and reused by E34's own code path so the two can never disagree.
- Balance comparison uses the instrument's quote precision; comparing floats directly is a defect - use `Decimal` throughout, consistent with the rest of the OMS.
- Wallet fetch is one extra REST call per account per pass, inside the `poll` bucket; to stay well within budget, balances are reconciled on **every other** timer tick (60 s) plus always on startup, reconnect and on demand. This cadence is configurable (`oms.reconcile.balance_every_n_ticks`, default 2).

## Test plan
- **Unit**: `aggregate(legs)` truth table over every leg-state combination; `order_link_id` parser including malformed and foreign ids; Decimal tolerance boundaries at exactly 0.5 % and 2 %.
- **Integration** (fixture-replay mock exchange): a three-account fan-out where account 2's child is lost in transport and account 3's child is rejected; assert the group ends `partial` with the right per-leg states after reconciliation; a scenario where the exchange reports an extra order with a group-shaped link id.
- **Contract**: wallet response shape asserted against the recorded Bybit fixture.
- **Chaos**: consumed by E45-T08's partial-fan-out-failure scenario.
- Coverage >=90 % on the new code.

## Security notes
Threats: **Tampering** - a fabricated exchange order with a crafted group-shaped `order_link_id` could otherwise be made to look like our own leg; mitigated by keeping `trade_group_leg_id` NULL for adopted orders and by never rule-managing untracked orders. **Information disclosure** - balances are financial data; they appear in reports and must be role-filtered on the WS `system` topic. Data classification: financial, high. Security label applies (touches OMS state and the fan-out safety invariant).

## Accessibility notes
N/A - no UI surface.

## Performance notes
Adds at most one REST call per account per 60 s; total reconciliation pass budget unchanged at <=3 s p95 for six accounts. Group recomputation is O(legs) with <=6 legs per group, negligible.

## Observability
`oms_balance_drift_pct{account}` gauge, `oms_group_corrections_total{kind}` counter, `oms_orphan_legs_total`. Audit: `oms.group_leg_corrected`, `oms.balance_corrected`. Incidents on SCR-144 for critical drift and orphan legs.

## Definition of Done
- [ ] Merged with >=90 % coverage; all tests green.
- [ ] `aggregate()` shared with E34 (no duplicated logic) and covered by the shared truth-table test.
- [ ] Security review recorded (fan-out safety invariant is in scope, so the `security` label is mandatory per `docs/plan/02-definition-of-ready-done.md` section 8).
- [ ] Runbook stub for "balance drift" and "orphan leg" filed for E45-T11.
- [ ] Demoed with a seeded partial fan-out.

## Dependencies
- **E45-T01** - the pass this extends.
- **E34** - trade groups, legs, the unwind plan and the `order_link_id` convention.
- **E28** - per-account profiles whose sizing consumes the balances being corrected.

## Branch
`feat/e45-reconcile-balances-groups`. ~250 LOC plus tests.

## References
- `docs/plan/30-release-roadmap.md` section 8.2 (E45 scope line)
- `docs/plan/27-adrs/ADR-0006-oms-state-machine.md`, `ADR-0008-trade-group-fanout.md`
- `docs/plan/21-database-schema.md` `trade_groups`, `orders.trade_group_leg_id`
- `docs/plan/24-internal-schemas.md` sections 8.4, 8.5
- `docs/plan/11-user-stories.md` US-POS-008, US-PROF-006
"""))

T.append(mk(
    key="E45-T05", kind="Task",
    title="Integrate the Bybit dead-man's-switch behind an explicit opt-in policy",
    labels=["type/feature", AREA, "priority/p1", "security"],
    component="api", phase=PH, sprint="Sprint 22", priority="P1 High",
    perspective="Development", risk="R3 Real-time cost", estimate=3, parent="E45",
    blocked_by=["E45-T02", "E39"], milestone=MS,
    body="""## Context
The roadmap scopes E45 to include *"Bybit dead-man's-switch (`/v5/order/disconnected-cancel-all`) integration with an explicit opt-in policy"* (`docs/plan/30-release-roadmap.md` section 8.2).

There is a documented constraint that shapes this entire ticket: `docs/plan/22-api-openapi.yaml` states that the dead-man's-switch *"is armed separately by the OMS for `inverse` only - it is not available for `linear`, so the local kill-switch is the operative control here."* CandleViewer v1 trades **USDT linear perpetuals only** (planning brief, locked decisions). Therefore the honest deliverable is: implement the integration correctly, make it opt-in, **and make its inapplicability to our v1 instrument set explicit in the UI, the config and the runbook**, rather than shipping a comfort feature that silently protects nothing.

`docs/plan/20-architecture.md` section 11 F7 also names "opt-in disconnect-flatten" among the mitigations for "emulated algos misbehave while the process is down", so the *policy* question - what should happen to open orders when our process dies - must be answered here regardless of the exchange's capability.

## Scope / Deliverables
- **Adapter capability flag** on the M4 exchange adapter: `supports_disconnect_cancel_all(category)` returning False for `linear`, True for `inverse`, derived from the adapter's capability table rather than an `if` at the call site (the ADR-0006 rule: transport and capability are capability decisions, not conditionals).
- **Integration**: when the capability is present and the policy is enabled, arm `POST /v5/order/disconnected-cancel-all` with the configured window on private-WS connect, re-arm on reconnect, and disarm on a clean shutdown.
- **Explicit opt-in policy** as typed configuration (M1): `oms.dead_mans_switch.enabled` (default **false**), `oms.dead_mans_switch.window_s`, and a per-account override. Enabling it is an audited, step-up-gated owner action.
- **Honest unavailability**: when the policy is enabled but the account trades only `linear`, the system must (a) log and audit that the switch was requested but is unavailable for the instrument category, (b) surface it on the admin health surface as a named, explained state - *"Exchange dead-man's-switch: not available for USDT perpetuals. Your protection is the native stop-loss on every position plus the local kill-switch."* - and (c) never report itself as armed.
- **The local compensating control**, which is what actually protects us: document and test that on backend death, open positions remain protected by the native exchange-side SL (the ADR-0008 invariant, `docs/plan/20-architecture.md` section 11 F7 "positions remain protected by native exchange SL"), and that emulated algos (TWAP/iceberg/chase) pause and are resumed or cancelled per algo policy on restart.
- **Startup policy check**: on boot, if the dead-man's-switch was armed before death and the window has expired, reconciliation (E45-T02) must find and explain whatever the exchange cancelled - the restart path must not be surprised by its own dead-man's-switch.

## Out of scope
- The kill-switch engine itself (E39) - this ticket only integrates with it.
- Changing the native-SL invariant (E32/ADR-0008).
- Adding `inverse` instrument support (out of scope for v1 entirely).

## Acceptance criteria
```gherkin
Scenario: Disabled by default
  Given a fresh deployment
  Then oms.dead_mans_switch.enabled is false, nothing is armed, and the admin health surface says the switch is off

Scenario: Enabling is a deliberate, audited act
  When the owner enables the dead-man's-switch policy
  Then step-up authentication is required, a high-severity audit entry records before and after, and the change propagates over the system WS topic within 2 seconds

Scenario: Honest unavailability for linear
  Given the policy is enabled and every configured account trades USDT linear perpetuals only
  When the private WS connects
  Then no arming call is made, the state is reported as "not available for this instrument category" with the explanation of what does protect the account, and the system never reports itself as armed

Scenario: Armed where supported
  Given the policy is enabled and the adapter capability reports the category as supported
  When the private WS connects
  Then the switch is armed with the configured window, re-armed on every reconnect, and disarmed on a clean shutdown

Scenario: Restart after an expired window
  Given the backend died while the switch was armed and the exchange cancelled orders
  When the backend restarts
  Then reconciliation finds the cancelled orders, attributes them to the dead-man's-switch in the report, and surfaces a single explained incident rather than a list of mysterious cancellations

Scenario: The real protection is proven
  Given the backend process is killed while a position is open
  Then the position retains its native exchange-side stop, and after restart reconciliation confirms the invariant holds
```

## Technical notes / design
- Config keys and their defaults live with the rest of the typed settings (`docs/plan/24-internal-schemas.md` section 16); enabling in `live` requires the environment to be `live` *and* the live flag on (E44), so a demo experiment cannot leave a live account armed.
- Arming is idempotent and cheap; it uses the `critical` rate bucket because it is a safety action, not a poll.
- The "not available" state is a first-class enum value, not a null - `DeadMansSwitchState = off | armed | unavailable_for_category | error`.
- Failure to arm when it *is* supported is a `critical` system event and blocks nothing (we degrade to the native-SL floor) but must alert.

## Test plan
- **Unit**: capability table for `linear` vs `inverse`; state enum transitions; idempotent arming; config gating under `demo` and `live`.
- **Integration** (fixture-replay mock exchange): arm/re-arm/disarm across a reconnect cycle; arming failure path; the restart-after-expiry attribution path.
- **Chaos** (E45-T08 consumes): kill the backend with an open position and assert the native SL survives and reconciliation confirms it - this is the assertion that matters more than the switch itself.
- **Contract**: the `/v5/order/disconnected-cancel-all` request shape asserted against a recorded fixture.
- Coverage >=90 % on the module.

## Security notes
This ticket touches the order path and a safety control, so the `security` label is mandatory (`docs/plan/02-definition-of-ready-done.md` section 8) and SR-083's kill-switch properties (idempotent, safe to press repeatedly, retries with backoff) are the model for arming behaviour. Threats: **Spoofing/Tampering** - a false "armed" report creates unwarranted confidence, which is precisely why `unavailable_for_category` must never be rendered as armed; **Denial of service** - an over-eager window could cancel live protective orders, so the window is bounded and the policy is off by default; **Elevation of privilege** - only the owner may change the policy, with step-up. Data classification: financial, high.

## Accessibility notes
The state it publishes is rendered by E45-S02 on SCR-143. Requirement inherited: the state must be conveyed as **text with an explanation**, never as a colour dot alone (SCR-143 a11y contract: "each subsystem is a labelled row with a text status").

## Performance notes
One extra REST call per private-WS connect; no steady-state cost. Must not delay connect readiness by more than 200 ms - arm asynchronously after the connection is usable.

## Observability
`oms_dead_mans_switch_state{account}` gauge over the four-value enum, `oms_dead_mans_switch_arm_failures_total`. Audit: `oms.dms_policy_changed`, `oms.dms_armed`, `oms.dms_disarmed`. Incident on arming failure.

## Definition of Done
- [ ] Merged with >=90 % coverage; all tests green.
- [ ] The `linear` unavailability documented in the runbook (E45-T11), in the admin UI copy (E45-S02) and in the config comment - three places, because this is the kind of fact a future reader will assume away.
- [ ] Security-engineer review recorded.
- [ ] Demoed: enable the policy, show the honest unavailable state, kill the backend and show the native SL still protecting the position.

## Dependencies
- **E45-T02** - reconnect events and the startup sequence this hooks into.
- **E39** - the local kill-switch that is the operative control for linear.
- **E32/ADR-0008** - the native-SL invariant that is the actual protection.

## Branch
`feat/e45-dead-mans-switch`. ~200 LOC plus tests.

## References
- `docs/plan/30-release-roadmap.md` section 8.2
- `docs/plan/22-api-openapi.yaml` `/trading/kill-switch` description (dead-man's-switch note)
- `docs/plan/20-architecture.md` section 11 (F7)
- `docs/plan/04-security-program.md` SR-083
- `docs/plan/27-adrs/ADR-0006-oms-state-machine.md`, `ADR-0008-trade-group-fanout.md`
"""))

if __name__ == "__main__":
    dump("_e45_b.json", T)
