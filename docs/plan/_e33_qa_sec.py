# -*- coding: utf-8 -*-
"""E33 QA tickets Q01..Q06 and security tickets X01..X03."""

from _e33_epic import REFS_COMMON, MS, PH

TICKETS = []


def add(**kw):
    TICKETS.append(kw)


QA_REFS = REFS_COMMON + """
- `docs/plan/03-testing-strategy.md` (test pyramid, coverage floors, fixture policy, chaos)
- `docs/plan/07-release-and-prr.md` (PRR gates, soak)
- `docs/plan/32-risk-register.md`"""

SEC_REFS = REFS_COMMON + """
- `docs/plan/04-security-program.md` (STRIDE per epic, SAST/DAST/SCA, abuse cases, pen-test gate)
- `docs/plan/27-adrs/ADR-0009-secrets-and-key-management.md`, `ADR-0010-auth-and-rbac.md`"""

# ---------------------------------------------------------------- Q01
add(
    key="E33-Q01",
    kind="Task",
    title="Black-box test plan for the four emulated strategies",
    labels=["type/test", "area/oms-execution", "priority/p1", "qa"],
    component="api",
    phase=PH,
    sprint="Sprint 17",
    priority="P1 High",
    perspective="Test",
    risk="R7 Data accuracy",
    estimate=3,
    parent="E33",
    blocked_by=["E33-T02"],
    milestone=MS,
    body="""## Context
`02-definition-of-ready-done.md` §3.2 requires an executed black-box test plan with a per-scenario sign-off before any Story reaches Done. The four strategies of this epic have an unusually large edge surface — US-ALGO-002, -005, -006 and -007 between them enumerate **26 Gherkin scenarios**, most of them failure or edge cases — and several are only reachable by fault injection (crash seams, duplicate WS delivery, rate-budget exhaustion, kill-switch mid-run). The plan must therefore specify not just what to verify but how to *produce* each condition.

## Scope / Deliverables
- A black-box test plan document covering every Gherkin scenario of US-ALGO-002, US-ALGO-005, US-ALGO-006, US-ALGO-007, each with: preconditions, exact steps, expected observable result (UI, API, audit log, exchange state), and the method used to induce the condition.
- **Condition-induction cookbook**: how to force each abnormal state on demo — lot-size and minimum-notional rejections (undersized slice on a high-tick instrument), insufficient margin (deliberately over-leveraged sub-account), `10018` rate limiting (saturating the account budget), `110001` amend-after-fill (amend against a marketable order), post-only crossing rejection, duplicate WS execution delivery (fixture replay), kill-switch and daily-loss lockout activation, backend restart at a chosen seam, and a flapping best price (synthetic book fixture).
- A **cross-strategy invariant matrix** checked for every strategy: no unprotected position; no duplicated child after restart; executions (not intent) drive filled quantities; the protective rate reserve is never consumed; every state transition is audited.
- Traceability table mapping every scenario to its automated test (where automated) or to a manual step (where not), satisfying §3.2's "manual step with a Task filed to automate it".
- Exit report template for the per-story sign-offs on S01–S04.

## Out of scope
E2E automation (Q02). Perf/load scripts (Q03). Chaos automation (Q04). A11y audit (Q05). UI-specific exploratory testing (Q06).

## Acceptance criteria
```gherkin
Scenario: Every story scenario is covered
  Given US-ALGO-002, 005, 006 and 007
  Then every Gherkin scenario in each story maps to a numbered plan step with preconditions,
  steps, expected result and induction method

Scenario: Abnormal conditions are reproducible
  Given the condition-induction cookbook
  When a tester follows any entry on the demo environment
  Then the intended exchange or system error is produced reliably,
  verified by each entry being executed at least once during plan authoring

Scenario: Invariants are checked per strategy (edge)
  Given the cross-strategy invariant matrix
  Then each of the five invariants is verified separately for OCO, iceberg, TWAP and chase,
  with the evidence source named (audit row, exchange query, database query)

Scenario: Gaps are visible (edge)
  Given a scenario that cannot be automated in this train
  Then it is marked manual, a follow-up automation Task is filed and linked,
  and the deviation is recorded rather than silently accepted
```

## Technical notes / design
Observable truth for a black-box check is the **exchange** (`GET /v5/order/realtime`, `/v5/position/list`) and the **audit log**, not the UI — the UI is a third assertion, never the only one. The plan states, per step, which of the three is authoritative.

Use a dedicated demo sub-account per strategy so parallel execution does not cross-contaminate position state.

## Test plan
This ticket *is* the test plan; its own quality gate is a peer review by the second QA/SDET plus the OMS tech lead confirming that each expected result is stated precisely enough to fail a wrong implementation.

## Security notes
Test steps must never use live keys; the plan states demo-only in its preamble and the induction cookbook contains no credential material. Abuse-flavoured steps (rate saturation) are coordinated with E33-X02 so they are run once, not twice.

## Accessibility notes
N/A — backend-focused plan; a11y is Q05.

## Performance notes
N/A — perf is Q03, though the plan records observed submit→ack times as context.

## Observability
Every plan step names the audit event(s) it expects, which doubles as a check that the events specified in `14-screens-catalogue.md` SCR-066..070 are actually emitted.

## Definition of Done
- [ ] Plan document merged and linked from S01–S04.
- [ ] Every cookbook entry executed at least once and confirmed reproducible.
- [ ] Peer-reviewed by the second QA/SDET and the OMS tech lead.
- [ ] Traceability table complete; automation gaps filed as Tasks.
- [ ] QA lead sign-off recorded.

## Dependencies
E33-T02 (control verbs and `GET /algos` give the plan its observation surface). E29 for the demo accounts and fixture harness.

## Branch
`chore/e33-qa-test-plan` (docs only).

## References
""" + QA_REFS,
)

# ---------------------------------------------------------------- Q02
add(
    key="E33-Q02",
    kind="Task",
    title="E2E suite additions for algo builders, monitor panel and full algo lifecycles",
    labels=["type/test", "area/oms-execution", "priority/p1", "qa"],
    component="web",
    phase=PH,
    sprint="Sprint 18",
    priority="P1 High",
    perspective="Test",
    risk="R11 Alert reliability",
    estimate=5,
    parent="E33",
    blocked_by=["E33-S05", "E33-S06"],
    milestone=MS,
    body="""## Context
The R3 quality gate requires Playwright E2E coverage on **web and Electron** for the train's trading surfaces (`30-release-roadmap.md` §7.4). For E33 the valuable E2E is not "the modal opens" but the **lifecycle**: configure → submit → observe progress in the monitor → intervene → verify the exchange agrees. That spans the builders (S05), the monitor (S06), the supervisor (T01) and the strategies (S01–S04), which is exactly why it belongs in one suite rather than per story.

## Scope / Deliverables
- Playwright specs under `e2e/algos/`, run against the **demo** environment in both the web and Electron targets:
  1. **TWAP lifecycle** — configure 10 slices over a short window from SCR-066, assert the schedule preview, submit, observe ≥ 2 slices fill in SCR-070 with correct progress text, pause, resume, cancel, assert no working children remain at the exchange.
  2. **Iceberg lifecycle** — configure from SCR-067, assert only one slice rests at a time (exchange assertion, not UI), let it refill once, cancel, assert the filled portion remains as a position with its protective stop.
  3. **Chase lifecycle** — configure from SCR-068 against a moving instrument, assert repricings are reflected in the monitor and that the reprice count respects the interval, hit max-chase or timeout, assert the configured end policy executed.
  4. **OCO lifecycle** — create from SCR-069 on an existing position, force the target leg to fill, assert the opposing leg is cancelled/reduced and the run completes.
  5. **Monitor bulk actions** — four runs of different kinds, cancel-all, assert the confirmation restates the count, per-item results render, and the exchange has no residual working algo children.
  6. **Orphan adoption** — create an order carrying an algo `order_link_id` whose run row is removed, assert it appears as orphaned and that adopt associates it correctly.
  7. **Degraded state** — sever the WS connection, assert the degraded banner and staleness marking appear and that unhonourable controls disable.
  8. **Guard rails** — attempt a sub-minimum-slice TWAP and an over-budget chase, asserting **no network request** was made (route interception), and attempt submission while disarmed and while kill-switched.
- Deterministic fixtures: a demo sub-account per spec, a seeded RNG override so slice jitter is reproducible, and time control for window-based specs.
- Flake controls: exchange-truth polling with explicit timeouts, no arbitrary sleeps, and a quarantine policy for any spec that flakes twice.
- Wire the suite into CI as part of the R3 E2E job with per-spec timing reported.

## Out of scope
Unit/integration tests (owned by the stories). Chaos scenarios (Q04). Load (Q03). A11y assertions beyond smoke-level axe checks (Q05).

## Acceptance criteria
```gherkin
Scenario: Every lifecycle passes on web and Electron
  Given the demo environment and the eight specs
  Then all pass in both targets in CI, with exchange-state assertions rather than UI-only ones

Scenario: Guard rails assert absence of traffic
  Given a sub-minimum-slice configuration and an over-budget chase configuration
  Then the specs assert via route interception that no order request left the client

Scenario: Deterministic despite jitter (edge)
  Given randomised slice sizes and times
  Then the seeded RNG override makes each run reproducible, and no spec depends on
  wall-clock timing beyond its declared time control

Scenario: Flake discipline (edge)
  Given a spec that fails intermittently twice
  Then it is quarantined with a Bug filed rather than retried into green,
  and the quarantine is visible in the CI report
```

## Technical notes / design
Specs assert against three sources in priority order: exchange (`GET /api/v1/orders` proxying exchange truth, or the diagnostics endpoint), audit log, then UI. The seeded-RNG override is a test-only backend config (`oms.algo.rng_seed`) that must be rejected in the live environment — coordinate with E33-X02.

Electron target reuses the existing Playwright Electron harness from E30/E31.

## Test plan
Self-testing: each spec is run 10× consecutively in a soak job during authoring to establish flake rate < 1 % before it enters the gating suite.

## Security notes
Specs run against demo credentials injected from CI secrets; no key material in the repo. The RNG-seed override and any other test hook must be proven inert outside demo — an explicit spec asserts the backend refuses the override when the environment is live.

## Accessibility notes
Each spec performs a smoke-level axe-core scan of the screen it visits so a gross a11y regression fails the E2E job; the full audit remains Q05.

## Performance notes
The suite must complete within the R3 E2E job budget; window-based specs use short durations (≤ 3 min) with time control rather than real 30-minute windows.

## Observability
Specs assert the presence of the expected audit events via `GET /api/v1/admin/audit`, making instrumentation part of the E2E contract.

## Definition of Done
- [ ] All eight specs green on web and Electron in CI.
- [ ] Flake rate < 1 % measured over the 10× soak.
- [ ] Exchange-truth assertions present in every lifecycle spec.
- [ ] Quarantine policy documented in the suite README.
- [ ] QA lead sign-off; results referenced from E33-S05/S06 DoD.

## Dependencies
E33-S05 and E33-S06 (the surfaces under test); E33-T02 (audit/list endpoints used as assertions); E33-Q01 (the plan these specs automate).

## Branch
`test/e33-e2e-algos`.

## References
""" + QA_REFS,
)

# ---------------------------------------------------------------- Q03
add(
    key="E33-Q03",
    kind="Task",
    title="Performance and load scripts for algo request rate and scheduler fidelity",
    labels=["type/test", "area/oms-execution", "priority/p1", "qa", "perf"],
    component="api",
    phase=PH,
    sprint="Sprint 18",
    priority="P1 High",
    perspective="Test",
    risk="R3 Real-time cost",
    estimate=3,
    parent="E33",
    blocked_by=["E33-S03", "E33-S04"],
    milestone=MS,
    body="""## Context
Chase and iceberg are the highest request-rate paths in the product, and the R3 load gate is explicit: *"k6: sustained order flow at the per-UID limit across 5 accounts for 1 h with zero lost acknowledgements and correct governor back-off"* (`30-release-roadmap.md` §7.4). Separately, `06-performance-and-load-standard.md` §5.2 fixes budget #4 (submit → ack p95 < 300 ms) and the epic adds two of its own: OCO race resolution ≤ 300 ms p95 and scheduler drift < 250 ms per slice.

## Scope / Deliverables
- k6/Locust scripts under `perf/algos/`:
  1. **Chase reprice storm** — a synthetic flapping book driving N chase runs; asserts the ≥ 200 ms reprice-interval floor holds, that amends never exhaust the protective reserve, and that `10018` back-off is exponential with jitter.
  2. **Iceberg refill rate** — a 450-slice run measuring sustained request rate against the account budget and the projected-rate estimate shown pre-submit (the estimate must not understate reality by more than 10 %).
  3. **Scheduler fidelity** — 50 concurrent TWAPs totalling 5 000 planned slices; measures per-slice drift p50/p95/max and asserts < 250 ms p95.
  4. **Resume storm** — 100 non-terminal runs, hard restart; measures process-start → first-correct-action p95 against the 5 s requirement and 2 s target.
  5. **OCO race latency** — 1 000 simulated fills; measures WS-fill → cancel/amend-request issued, asserting ≤ 300 ms p95.
  6. **Monitor panel frame cost** — 100 running algos rendered in SCR-070; asserts < 3 ms scripting per frame and that updates arrive coalesced at ≤ 2 Hz.
- A results dashboard fragment and a recorded baseline committed so regressions are detectable in later trains (E46 performance hardening consumes it).
- Budget assertions wired as CI-visible pass/fail, not just reported numbers.

## Out of scope
Functional correctness (Q01/Q02). Chaos/failure injection (Q04). Ingestion or chart-engine budgets (E46/E11).

## Acceptance criteria
```gherkin
Scenario: All six scripts run and assert budgets
  Given the perf suite
  Then each script asserts its named budget and fails the job when breached,
  rather than only reporting a number

Scenario: One-hour sustained flow
  Given chase and iceberg runs across five demo accounts at the per-UID limit
  When the load runs for one hour
  Then there are zero lost acknowledgements, back-off is exponential with jitter on 10018,
  and the protective reserve is never consumed

Scenario: Estimate honesty (edge)
  Given the projected requests/min shown by the iceberg and chase builders
  Then the measured rate is within 10 percent of the estimate, or the estimate is corrected

Scenario: Baseline recorded (edge)
  Given the first green run
  Then p50/p95/max for every budget is committed as a baseline that later runs compare against
```

## Technical notes / design
Per-UID rate limits mean 5 accounts are 5 budgets (`30-release-roadmap.md` §7.2 E34) — the scripts must not aggregate them into one and must exercise the token bucket's protective reserve explicitly by interleaving a stop-loss placement during saturation.

Run against demo with dedicated sub-accounts; the synthetic flapping book is a recorded/generated fixture fed to the BookEngine, not a real market dependency, so results are repeatable.

## Test plan
Each script is validated by a negative control — deliberately breaking a budget (e.g. lowering the reprice floor) must make the assertion fail — so a green result means something.

## Security notes
Load testing is indistinguishable from abuse at the network layer: scripts run only against demo, are rate-capped to the account's own budget, and are coordinated with E33-X02 so the rate-DoS abuse case reuses these harnesses rather than inventing its own.

## Accessibility notes
The SCR-070 frame-cost script records whether live-region announcements are aggregated rather than per-row, feeding E33-Q05.

## Performance notes
Budgets asserted: submit → ack p95 < 300 ms (#4); OCO resolution ≤ 300 ms p95; scheduler drift < 250 ms p95; resume p95 < 2 s (5 s hard); SCR-070 < 3 ms scripting/frame at 100 rows; iceberg/chase rate estimates within 10 %.

## Observability
Scripts scrape `oms_algo_*`, `oms_chase_*`, `oms_oco_race_resolution_ms` and `oms_algo_scheduler_drift_ms`, which validates that those metrics exist and are correctly labelled.

## Definition of Done
- [ ] Six scripts merged, each asserting its budget, each with a negative control demonstrated.
- [ ] One-hour sustained run executed and its report attached.
- [ ] Baselines committed; dashboard fragment added.
- [ ] Results referenced from S03/S04 DoD and from the epic's exit criteria.
- [ ] QA lead + Architect sign-off.

## Dependencies
E33-S03 and E33-S04 (the strategies under load); E33-T01 (metrics and buckets); E29/E34 for the governor behaviour being asserted.

## Branch
`test/e33-perf-algos`.

## References
""" + QA_REFS,
)

# ---------------------------------------------------------------- Q04
add(
    key="E33-Q04",
    kind="Task",
    title="Chaos scenarios: crash seams, disconnects and risk-control halts for algos",
    labels=["type/test", "area/oms-execution", "priority/p0", "qa"],
    component="api",
    phase=PH,
    sprint="Sprint 18",
    priority="P0 Critical",
    perspective="Test",
    risk="R11 Alert reliability",
    estimate=5,
    parent="E33",
    blocked_by=["E33-S03", "E33-S04", "E33-S01"],
    milestone=MS,
    body="""## Context
The R3 chaos gate names one E33 scenario explicitly — *"backend restart mid-TWAP"* — and requires that all such scenarios "resume to a correct, reconciled state" (`30-release-roadmap.md` §7.4). The user stories go further, each naming a specific seam: OCO's "crash between fill and cancel", iceberg's "crash with a slice resting", TWAP's "backend restart mid-TWAP", chase's "chase orphan after crash". These are the scenarios where an emulated algo can produce a **real, unintended position**, so they are P0 and they are automated, not exploratory.

## Scope / Deliverables
- A chaos suite `tests/chaos/algos/` executed in CI against a containerised backend + demo adapter:
  1. **Crash seam matrix** — for each of the four strategies × four seams (before persist, after persist/before submit, after submit/before ack persist, after ack persist): SIGKILL, restart, assert no duplicated child, filled quantity recomputed from executions, correct terminal state, and first correct action within 5 s.
  2. **OCO fill/cancel seam** — kill precisely after the fill event is persisted and before the cancel is sent; assert the cancel is re-sent with the original idempotency key and the run completes within 5 s of restart.
  3. **Iceberg resting-slice adoption** — kill with a slice resting; assert adoption by `order_link_id`, not duplication.
  4. **Chase orphan adoption** — kill with a chase order resting; assert the price is read back from the exchange and chasing resumes only after confirmation; assert the one-live-order DB constraint holds throughout.
  5. **WS disconnect** — sever the private execution stream for 30 s mid-run; assert `on_disconnect="freeze"` semantics (no new children, existing children left working, native SL intact), the degraded state surfaces, and reconciliation catches up on reconnect.
  6. **Exchange 5xx and 10018 storms** — assert back-off, no runaway retries, no state corruption.
  7. **Kill-switch and daily-loss lockout mid-run** — for all four strategies; assert immediate halt, children handled per policy, terminal state "halted by risk control", audit + alert emitted, and **no automatic resumption**.
  8. **Postgres failover mid-run** — assert the run resumes with no duplicated child and no lost slice history.
  9. **Clock jump / event-loop suspension** — suspend for ≥ 2 TWAP intervals; assert no back-to-back firing and correct re-planning.
- Reusable fixtures exported for E33-D07 (to reach degraded/halted states visually) and for E33-Q06.
- A chaos report template capturing, per scenario, the observed recovery time and the exchange-vs-local reconciliation result.

## Out of scope
Load (Q03). Functional happy paths (Q01/Q02). Fan-out and multi-account chaos (E34/E45).

## Acceptance criteria
```gherkin
Scenario: Crash matrix is exhaustive and green
  Given four strategies and four seams
  Then all sixteen combinations run in CI and each asserts zero duplicated children,
  execution-derived fill quantities and a correct terminal state

Scenario: Recovery is bounded
  Given any crash scenario
  Then the time from process start to the first correct action is recorded and is under
  five seconds, with the p95 across the matrix reported

Scenario: Risk-control halt is unconditional (failure)
  Given the kill-switch fires during each of the four strategies
  Then every run halts, ends in "halted by risk control" with a reason, emits audit and alert,
  and never resumes without an explicit re-arm

Scenario: Disconnect leaves protection intact (edge)
  Given the private stream is severed mid-run
  Then no new children are issued, existing children remain working, the native stop remains
  in place at the exchange, and reconciliation on reconnect produces no duplicate or orphan

Scenario: Database failover (edge)
  Given Postgres fails over mid-run
  Then the run resumes with complete slice history and no duplicated child
```

## Technical notes / design
Seams are identified by the instrumentation points E33-T01 exposes for exactly this purpose (a test-only fault-injection hook that must be inert outside test builds — verified by E33-X02).

Exchange truth after each scenario is read from `GET /v5/order/realtime` and `/v5/position/list` through the adapter, and compared against `orders`, `algo_runs` and `algo_slices`; any discrepancy fails the scenario.

## Test plan
The suite is itself validated by negative controls: disabling adoption must make the adoption scenarios fail; disabling the idempotency key must make the OCO seam scenario fail. Both are demonstrated once during authoring.

## Security notes
Fault-injection hooks are a security surface — the suite includes an assertion that the hook is absent/refused in a production-mode build, and E33-X02 independently attempts to invoke it. Chaos runs use demo credentials only.

## Accessibility notes
Scenario 5 and 7 fixtures are reused by E33-Q05 and E33-D07 to verify the degraded and halted states are announced and rendered correctly — which is the only practical way to test those states.

## Performance notes
Recovery time is a budget, not a curiosity: 5 s hard, 2 s target at 100 concurrent runs (cross-checked with Q03's resume-storm script).

## Observability
Each scenario asserts the expected audit events and that `oms_algo_resume_seconds` is emitted with a plausible value — chaos doubles as observability verification.

## Definition of Done
- [ ] All nine scenario groups automated and green in CI; the crash matrix runs on every merge to `main`.
- [ ] Negative controls demonstrated for adoption and idempotency.
- [ ] Recovery times recorded and within budget.
- [ ] Fixtures exported and consumed by E33-Q05/Q06/D07.
- [ ] Chaos report attached to the epic; feeds the R3 PRR.
- [ ] QA lead + Architect + Security engineer sign-off (the halt scenarios are a safety gate).

## Dependencies
E33-S01/S03/S04 (strategies under test; S02 is exercised via the matrix), E33-T01 (fault-injection hooks, adoption, persistence), E39 (kill-switch and lockouts).

## Branch
`test/e33-chaos-algos`.

## References
""" + QA_REFS,
)

# ---------------------------------------------------------------- Q05
add(
    key="E33-Q05",
    kind="Task",
    title="Accessibility audit of the algo builders and monitor panel",
    labels=["type/test", "area/oms-execution", "priority/p1", "qa", "a11y"],
    component="web",
    phase=PH,
    sprint="Sprint 18",
    priority="P1 High",
    perspective="QA",
    risk="None",
    estimate=3,
    parent="E33",
    blocked_by=["E33-S05", "E33-S06"],
    milestone=MS,
    body="""## Context
`05-accessibility-standard.md` mandates WCAG 2.2 AA with axe-core in CI plus **manual screen-reader passes**; the R3 a11y gate additionally calls out that danger/confirm patterns must be announced. E33 ships five net-new screens whose a11y requirements were specified in E33-D05 and handed off in E33-D06; this audit executes that checklist against the built software and is the epic's a11y evidence.

## Scope / Deliverables
- **Automated**: axe-core scans of SCR-066, SCR-067, SCR-068, SCR-069 and SCR-070 in every state (configured, running, paused, degraded, halted, completed, failed, orphaned, empty), light and dark, both densities — wired as a CI job, not a one-off run.
- **Manual screen-reader passes** with NVDA + Chrome and VoiceOver + Safari/Electron:
  - Every builder completed and submitted using the screen reader alone.
  - The TWAP **schedule preview** read as a table with headers.
  - The **emulation caveat** and the **OCO residual-risk note** encountered in reading order, not buried after the form.
  - Running-state refresh announcements throttled to at most one per 5 s (iceberg) and not flooding at 2 Hz (monitor).
  - The **degraded banner** announced as a status, and "halted by risk control" announced with its reason.
  - Monitor controls announcing their target and effect ("Cancel TWAP a_12 on BTCUSDT, Main").
  - Bulk cancel-all confirmation announced as an alert dialog restating the count.
- **Keyboard-only passes**: full operation of all five screens including bulk actions and orphan adopt/cancel; focus trap and restoration per modal; visible focus throughout; no keyboard trap in the 100-row virtualised table.
- **Contrast and non-colour encoding** verification for every status treatment in both themes and the three colour-vision simulations; target size ≥ 24 × 24 CSS px in both densities.
- Findings triaged by severity with WCAG success-criterion references; blockers fixed before the stories close, others filed as Bugs with priorities.
- Reuse of E33-Q04's fixtures to reach the degraded and halted states.

## Out of scope
Design intent review (E33-D07). Functional testing (Q01/Q02). Other epics' screens.

## Acceptance criteria
```gherkin
Scenario: axe-core green across all states
  Given the five screens in every enumerated state, theme and density
  Then axe-core reports no violations, and the scan runs in CI rather than manually

Scenario: Screen-reader completion
  Given a screen-reader user with no sighted assistance
  Then each builder can be completed and submitted, and the monitor's controls, statuses and
  bulk confirmations are understandable from speech alone

Scenario: Announcements are throttled (edge)
  Given a running iceberg and a monitor with 100 rows updating at 2 Hz
  Then announcements are aggregated and polite, at most one per five seconds for slice refresh,
  and the screen reader is not flooded

Scenario: Keyboard-only completeness (edge)
  Given keyboard-only operation
  Then every action including cancel-all and orphan adoption is reachable, focus is visible and
  ordered, modals trap and restore focus, and the virtualised table is escapable

Scenario: Status without colour (edge)
  Given greyscale and the three colour-vision simulations
  Then running, paused, degraded, halted, failed and orphaned remain distinguishable,
  and contrast meets AA in both themes
```

## Technical notes / design
Execute the E33-D05 acceptance checklist verbatim, item by item, recording pass/fail per item — that traceability is what makes the audit auditable.

Electron is tested as a target in its own right; screen-reader behaviour in Electron differs from the browser and the R3 gate covers both.

## Test plan
This is the test. Evidence: axe reports per state, screen-reader session recordings, a keyboard map walkthrough, contrast measurements, and the completed D05 checklist.

## Security notes
Verify that accessible names do not leak out-of-scope data: a `manager` without access to an account must not encounter that account's label in any announcement, and a `viewer`'s tree must not expose mutating controls.

## Accessibility notes
The audit is the accessibility deliverable; see Scope.

## Performance notes
Live-region churn is measured alongside frame cost (with Q03's 100-row script): aggregate announcements must not add measurable main-thread cost.

## Observability
Findings are filed with the screen and state, so recurring a11y regressions are trackable across trains.

## Definition of Done
- [ ] axe-core CI job covering all five screens and all states, green.
- [ ] Manual SR passes on NVDA and VoiceOver, web and Electron, recorded.
- [ ] Keyboard-only pass recorded; contrast and target-size measurements attached.
- [ ] D05 checklist completed item by item with pass/fail.
- [ ] Blockers fixed and re-verified; non-blockers filed with priorities.
- [ ] Accessibility lead sign-off; referenced from E33-S05/S06 DoD and the epic DoD.

## Dependencies
E33-S05, E33-S06 (built screens); E33-D05 (the checklist); E33-Q04 (fixtures for degraded/halted states).

## Branch
`test/e33-a11y-audit`.

## References
""" + QA_REFS,
)

# ---------------------------------------------------------------- Q06
add(
    key="E33-Q06",
    kind="Task",
    title="Exploratory charter, regression pack and QA sign-off for emulated algos",
    labels=["type/test", "area/oms-execution", "priority/p1", "qa"],
    component="api",
    phase=PH,
    sprint="Sprint 18",
    priority="P1 High",
    perspective="QA",
    risk="R7 Data accuracy",
    estimate=3,
    parent="E33",
    blocked_by=["E33-Q02", "E33-Q04"],
    milestone=MS,
    body="""## Context
Scripted tests only find the failures someone imagined. Emulated algos fail in combinations — a chase whose account is simultaneously being used by a TWAP while a lockout fires — and the epic's DoD requires an epic-level regression/exploratory pass beyond per-child QA (`02-definition-of-ready-done.md` §2.2). This ticket provides the charters, builds the durable regression pack, and produces the epic's QA sign-off.

## Scope / Deliverables
- **Exploratory charters** (time-boxed 90 min each, session notes recorded):
  1. *Concurrency* — multiple algos of different kinds on one account and one symbol; look for interference, double-counting of filled quantity, and rate-budget starvation.
  2. *Interference with manual trading* — manually amend, cancel or flatten while an algo owns children; look for orphans, for the algo fighting the user, and for a position closed twice.
  3. *Boundary parameters* — minimums, maximums and one-beyond for every parameter of all four strategies (slices 2 and 500, display qty at min lot and at 50 %, chase offset 0 and max, durations at 10 s and 24 h).
  4. *Environment and flags* — algo kinds disabled mid-run, environment switch attempted while an algo runs (must be blocked per SCR-073's checklist), RBAC changes mid-run.
  5. *Recovery under stress* — repeated restarts during heavy slicing; combine with Q04 fixtures beyond the scripted matrix.
  6. *Trustworthiness of the monitor* — try to create a state the monitor shows wrongly (stale rows, missing orphan, wrong progress after adoption).
- **Regression pack**: the durable subset of Q01's plan plus any exploratory finding worth re-running each train, packaged as a named suite with an execution time budget (≤ 2 h manual + the automated suites) and added to the R3 soak checklist.
- **Bug triage**: every finding filed with repro steps, severity and the missing-test-layer note required by `02-definition-of-ready-done.md` §6.1.
- **Epic QA sign-off report**: per-story pass/fail against Q01's scenarios, the invariant matrix result, chaos and perf results referenced, open-defect list with severities, and an explicit statement of any QA-capacity deviations.

## Out of scope
Writing new automation (belongs to Q02/Q03/Q04 or to follow-up Tasks filed from findings). Design QA (D07). A11y audit (Q05).

## Acceptance criteria
```gherkin
Scenario: All charters executed with notes
  Given the six charters
  Then each is executed within its time box and produces session notes listing what was tried,
  what was observed and what was filed

Scenario: Regression pack exists and is runnable
  Given the packaged regression suite
  When a QA engineer new to the epic executes it
  Then it completes within its stated budget and produces an unambiguous pass/fail per item

Scenario: Sign-off is evidence-based
  Given the sign-off report
  Then every user-story scenario has a recorded result, the five cross-strategy invariants are
  each evidenced, and no story is signed off on the basis of "no issues seen"

Scenario: Concurrency interference (edge)
  Given a TWAP and a chase on the same account and symbol while a lockout fires
  Then the observed behaviour is documented, and any interference, double-counting or
  starvation is filed as a defect with the layer that should have caught it
```

## Technical notes / design
Charters run on demo with dedicated sub-accounts; session notes follow the existing exploratory-testing template. Findings that reveal a *specification* gap are routed to E33-T03 for doc reconciliation, not only to a Bug.

## Test plan
N/A — this is the testing activity. Its own quality control is a peer review of the sign-off report by the second QA/SDET.

## Security notes
Charter 4 overlaps with E33-X02's abuse cases (RBAC changes mid-run, flags disabled mid-run); results are shared so the Security engineer's review has QA evidence to lean on rather than duplicating effort.

## Accessibility notes
Any a11y issue noticed during exploration is filed and cross-linked to Q05 rather than absorbed silently.

## Performance notes
Charter 5 records recovery times informally; anything worse than Q03's baseline is escalated as a perf defect.

## Observability
Charter 6 explicitly attacks the monitor's trustworthiness, which is the practical test of whether the WS projection and 30 s reconciliation actually hold.

## Definition of Done
- [ ] Six charters executed; session notes attached.
- [ ] Regression pack packaged, time-budgeted and added to the R3 soak checklist.
- [ ] All findings filed with severity, repro and missing-test-layer notes; P0/P1 closed before sign-off.
- [ ] Epic QA sign-off report published with per-scenario results and the invariant matrix.
- [ ] Peer-reviewed by the second QA/SDET; QA lead signs off the epic.

## Dependencies
E33-Q02 (E2E baseline), E33-Q04 (chaos fixtures and results); all stories feature-complete.

## Branch
`chore/e33-qa-signoff` (docs/notes only).

## References
""" + QA_REFS,
)

# ---------------------------------------------------------------- X01
add(
    key="E33-X01",
    kind="Task",
    title="STRIDE threat model for the emulated-algo supervisor",
    labels=["type/security", "area/oms-execution", "priority/p0", "security"],
    component="api",
    phase=PH,
    sprint="Sprint 16",
    priority="P0 Critical",
    perspective="Security",
    risk="R11 Alert reliability",
    estimate=3,
    parent="E33",
    blocked_by=["E33-D01"],
    milestone=MS,
    body="""## Context
`04-security-program.md` requires a STRIDE threat model per epic, and `02-definition-of-ready-done.md` §2.1 makes it default-on for any epic touching the OMS. E33 introduces something new to the system's risk surface: **long-lived, autonomous, order-placing processes** that outlive the user's session, hold a standing authorisation, and issue requests at the highest rate in the product. This model must be complete **before** E33-T01 implements the guards, so the guards are controls rather than afterthoughts — hence T01 is `blocked_by` this ticket.

## Scope / Deliverables
- Data-flow diagram of the algo path: client → `POST /orders` with `AlgoSpec` → validation → `AlgoSupervisor` → strategy → guards (kill-switch, lockout, token bucket, caps) → exchange adapter → Bybit; plus the feedback path WS executions → supervisor → state store → WS projection → SCR-070.
- STRIDE analysis per element and per flow, with at minimum:
  - **Spoofing** — who may start an algo on which account; session/token reuse; the standing authorisation of a run whose creator's access is later revoked.
  - **Tampering** — client-supplied `AlgoSpec` fields (slice counts, display qty, offsets) used to exceed intended exposure; parameter mutation on a running run; tampering with the test-only fault-injection and RNG-seed hooks.
  - **Repudiation** — "I never started that TWAP": audit completeness for create/pause/resume/cancel/adopt and for every child order, with actor and parameters.
  - **Information disclosure** — algo params reveal hidden size and execution intent; cross-account visibility for managers; WS projection leaking runs on accounts the subscriber cannot see.
  - **Denial of service / denial of wallet** — reprice storms and refill storms exhausting the per-UID budget and starving protective orders; unbounded duration/child counts; resume storms after a restart; using cancel-all as a griefing tool.
  - **Elevation of privilege** — a `viewer` or an out-of-scope `manager` invoking control verbs; orphan **adopt** used to take control of an order created by another user.
- For each threat: likelihood/impact rating, the control that mitigates it, and where that control lives (E33-T01 guards, E33-T02 RBAC, DB constraint, config floor, UI affordance).
- A required-controls list handed to E33-T01/T02 as acceptance criteria, and an abuse-case list handed to E33-X02.
- Explicit treatment of the **residual risk** that defines this epic: emulated algos stop when the backend stops. The model must state the accepted mitigation (native SL always present, `on_disconnect="freeze"`, degraded banner, monitor visibility) and record Owner acceptance.

## Out of scope
Executing abuse cases (X02). Final sign-off (X03). Key management (E27/ADR-0009). Fan-out threats (E34).

## Acceptance criteria
```gherkin
Scenario: Model is complete and rated
  Given the algo data-flow diagram
  Then every element and flow has a STRIDE analysis with rated threats, each mapped to a named
  control and the ticket that implements it

Scenario: Controls become acceptance criteria
  Given the required-controls list
  Then each control appears as an acceptance criterion or test on E33-T01 or E33-T02,
  verified by a cross-reference check

Scenario: Standing authorisation addressed (edge)
  Given a manager whose account access is revoked while their TWAP is running
  Then the model states the required behaviour (re-check per child, halt on revocation)
  and that behaviour is assigned to a ticket

Scenario: Residual risk accepted explicitly (edge)
  Given the backend-outage residual risk
  Then it is documented with its mitigations and carries a recorded Owner acceptance
  in 32-risk-register.md, rather than being treated as closed
```

## Technical notes / design
Use the program's STRIDE template and store the model with the other epic threat models. Rate with the program's likelihood/impact scale so E33's risks are comparable with E27/E29/E34/E35/E39/E42.

Cross-reference `24-internal-schemas.md` §8 (token buckets, protective reserve) and §10.1 (universal rules) — several needed controls already exist as design decisions and should be recorded as such rather than re-invented.

## Test plan
The model's outputs are testable artefacts: each control maps to a test in T01/T02/X02. A review session with the OMS tech lead and the Architect validates that no flow was missed.

## Security notes
This ticket is the security analysis; its own quality bar is that every Critical/High threat has a control with a named owner before E33-T01 starts, per the R3 security gate ("STRIDE for E27, E29, E34, E35, E39, E42 — all Critical/High closed"; E33 is held to the same bar as an order-placing epic).

## Accessibility notes
N/A.

## Performance notes
Several controls are performance constraints (reprice floor, token reserve); the model must state them as security controls so they cannot be "optimised away" later.

## Observability
The model specifies the minimum audit set for non-repudiation, which E33-T01/T02 implement and E33-Q01 verifies.

## Definition of Done
- [ ] Threat model document merged and linked from the epic and from `04-security-program.md`'s per-epic index.
- [ ] Every Critical/High threat has a mapped control and an owning ticket.
- [ ] Required-controls list referenced by E33-T01/T02 acceptance criteria.
- [ ] Abuse-case list handed to E33-X02.
- [ ] Residual-risk entry added to `32-risk-register.md` with Owner acceptance.
- [ ] Reviewed and signed by the Security engineer and the Architect.

## Dependencies
E33-D01 informs the UI-side transparency controls. E29/E39 supply the existing OMS and risk controls this model builds on.

## Branch
`chore/e33-threat-model` (docs only).

## References
""" + SEC_REFS,
)

# ---------------------------------------------------------------- X02
add(
    key="E33-X02",
    kind="Task",
    title="Abuse cases, SAST/DAST rules and permission checks for emulated algos",
    labels=["type/security", "area/oms-execution", "priority/p0", "security"],
    component="api",
    phase=PH,
    sprint="Sprint 18",
    priority="P0 Critical",
    perspective="Security",
    risk="R3 Real-time cost",
    estimate=3,
    parent="E33",
    blocked_by=["E33-X01", "E33-S04", "E33-S06"],
    milestone=MS,
    body="""## Context
E33-X01 produces the threat model; this ticket proves the controls actually hold by attacking them, and then encodes what it learns into automated rules so the next change cannot silently reopen the hole. `02-definition-of-ready-done.md` §3.2 requires a manual abuse-case check for anything touching the OMS, and the R3 security gate requires a targeted abuse-case review before the train closes.

## Scope / Deliverables
- **Executed abuse cases**, each with evidence (request/response, audit rows, exchange state):
  1. *Denial of wallet* — configure a chase at the interval floor against a synthetic flapping book and attempt to exhaust the account's order budget; assert the protective reserve survives and a stop-loss placement still succeeds throughout.
  2. *Unbounded exposure* — craft `AlgoSpec` payloads exceeding instrument filters and profile caps (slices > 500, display qty < min lot, `max_chase_ticks` absurd, duration > cap) directly against the API, bypassing the UI; assert server-side refusal every time.
  3. *Privilege escalation* — as a `viewer` and as a `manager` scoped to a different account, attempt create, pause, resume, cancel, cancel-all, adopt; assert 403, **no state change**, and an audit row for every attempt.
  4. *Standing authorisation* — revoke a manager's access to an account while their TWAP runs; assert the run halts (or is prevented from issuing further children) per the X01-required behaviour.
  5. *Orphan hijack* — attempt to adopt an order belonging to another user's run or to an account the caller cannot access; assert refusal.
  6. *Test-hook exposure* — attempt to set the RNG seed override and to invoke the fault-injection hook against a production-mode build; assert both are absent or refused.
  7. *Replay* — re-send control requests with a reused `Idempotency-Key` and with a stale one; assert idempotent behaviour and no duplicate exchange action.
  8. *Griefing* — as one manager, attempt `POST /algos/cancel-all` unscoped in a way that would touch another manager's accounts; assert scoping.
  9. *Flag bypass* — with `algo.chase` disabled, attempt to create a chase directly via the API; assert `algo_flag_disabled` refusal before any exchange call.
- **Automated rules**:
  - Semgrep/Bandit rules asserting that no code path outside `packages/oms/algo` creates `intent='algo_child'` orders, that `AlgoSpec` params are never trusted without server-side validation, and that test hooks are guarded by an environment check.
  - A ZAP/DAST profile covering the new `/algos*` routes (authz matrix, injection on filter parameters, mass-assignment on the control body).
  - Extension of the existing RBAC matrix test (every route × every role → 403 + no state change + audit row) to the new routes, satisfying R3 exit criterion 10.
- Findings triaged; Critical/High fixed before the train closes, others accepted with Owner sign-off.

## Out of scope
The threat model itself (X01). Final sign-off (X03). Pen-test (E43, R4). Key management (E27).

## Acceptance criteria
```gherkin
Scenario: Every abuse case executed with evidence
  Given the nine abuse cases
  Then each is executed against the demo environment and its outcome recorded with
  request/response, audit rows and exchange state

Scenario: Protective reserve survives a budget attack
  Given a chase configured to saturate the account's order budget
  When a stop-loss placement is attempted during saturation
  Then it succeeds, proving the protective reserve was never consumed

Scenario: RBAC matrix extended and green (failure)
  Given every new /algos route and every role
  Then disallowed combinations return 403 with no state change and an audit row,
  asserted automatically rather than manually

Scenario: Test hooks inert in production mode (edge)
  Given a production-mode build
  When the RNG-seed override and the fault-injection hook are invoked
  Then both are absent or refused, and the attempt is logged

Scenario: Direct-API bypass blocked (edge)
  Given payloads that the UI would never send
  Then server-side validation refuses every one, demonstrating the client is not the authority
```

## Technical notes / design
Abuse cases run against demo with dedicated sub-accounts, reusing E33-Q03's load harness for case 1 and E33-Q04's fixtures for cases 4 and 6 so the same conditions are not built twice.

Semgrep rules live with the existing ruleset and run in the standard SAST job; the DAST profile joins the existing ZAP pipeline.

## Test plan
Each automated rule is validated with a negative control: a deliberate violating commit must trip it. RBAC matrix additions are asserted to fail if a route's authz decorator is removed.

## Security notes
This ticket is the security testing; the notes are its scope. Data classification: financial; demo credentials only; no findings written into public artefacts before triage.

## Accessibility notes
N/A.

## Performance notes
Case 1 is inherently a load test and must be run in a window agreed with QA so it does not distort Q03's baselines.

## Observability
Every abuse attempt must produce an audit row — the absence of one is itself a finding (non-repudiation failure), independent of whether the attack succeeded.

## Definition of Done
- [ ] All nine abuse cases executed with evidence attached.
- [ ] Semgrep/Bandit rules merged and passing, each with a demonstrated negative control.
- [ ] DAST profile covering `/algos*` merged into the ZAP pipeline.
- [ ] RBAC matrix test extended to every new route and green.
- [ ] Critical/High findings fixed and re-verified; others accepted with Owner sign-off.
- [ ] Security engineer review comment on the affected stories.

## Dependencies
E33-X01 (the abuse-case list), E33-S04 and E33-S06 (the last surfaces to attack), E33-T02 (the routes), E33-Q03/Q04 (harnesses reused).

## Branch
`chore/e33-abuse-cases` + `test/e33-sast-dast-rules`.

## References
""" + SEC_REFS,
)

# ---------------------------------------------------------------- X03
add(
    key="E33-X03",
    kind="Task",
    title="Security review and sign-off of the shipped emulated-algo surfaces",
    labels=["type/security", "area/oms-execution", "priority/p0", "security"],
    component="api",
    phase=PH,
    sprint="Sprint 18",
    priority="P0 Critical",
    perspective="Security",
    risk="R11 Alert reliability",
    estimate=2,
    parent="E33",
    blocked_by=["E33-X02", "E33-Q04"],
    milestone=MS,
    body="""## Context
`02-definition-of-ready-done.md` §2.2 and §8 require a Security engineer sign-off before an OMS-touching epic can be Done, and the R3 security gate requires all Critical/High findings closed before the train closes. This ticket is the white-box review that complements X02's black-box attacking, and it produces the epic's security sign-off.

## Scope / Deliverables
- **White-box code review** of `packages/oms/algo/` and the `/algos*` routes with security intent: guard placement (are kill-switch, lockout, RBAC and budget checks on **every** path to a child submission, including resume-on-boot?), validation completeness against instrument filters and profile caps, idempotency-key derivation, secret/PII absence in logs (algo params are sensitive; log them at the right level and redact where needed), and error handling that cannot leave exposure open.
- **Control-coverage matrix**: every Critical/High threat from E33-X01 → its control → the test or code location proving it → status.
- **Verification of the safety invariant on the algo path**: confirm with the E32/M17 owners that the "no position-opening order without a native exchange-side SL" enforcement covers every algo-initiated entry, including a resumed run's first child after a restart, and that the R3 exit-criterion-2 suite enumerates the algo path.
- **Finding triage closure**: confirm X02's findings and Q04's safety-relevant chaos results are closed or accepted with Owner sign-off recorded.
- **SAST/SCA/secrets scan** review for the epic's diff: clean or triaged.
- **Sign-off comment** on the epic and on each `security`-labelled story, plus an input note to the R3 PRR and to E43's pen-test scope (the algo surface must appear in the pen-test brief).

## Out of scope
Fixing findings (they become Bugs or story work). Pen-testing (E43). Fan-out and rule-engine reviews (E34/E35).

## Acceptance criteria
```gherkin
Scenario: Every control is evidenced
  Given the control-coverage matrix
  Then every Critical and High threat from the STRIDE model has a control with a named test or
  code location and a status of implemented-and-verified

Scenario: Guards cover the resume path
  Given a run resumed after a restart
  Then the review confirms kill-switch, lockout, RBAC and budget checks execute before the
  first child submission of the resumed run, not only on the original create path

Scenario: Native-SL coverage confirmed (edge)
  Given algo-initiated position-opening entries including a resumed run's first child
  Then the M17 invariant enforcement is confirmed to cover them and the exit-criterion-2 suite
  enumerates the algo path explicitly

Scenario: Open findings dispositioned (failure)
  Given any remaining finding at review time
  Then it is either fixed and re-verified, or accepted with a recorded Owner sign-off and a
  follow-up ticket — never left undecided
```

## Technical notes / design
Review against the merged code, not PR diffs alone, so cross-cutting gaps (a guard missing on one of five call sites) are visible. Use the control-coverage matrix as the review checklist rather than reading linearly.

## Test plan
No new tests authored here; the review verifies that existing tests actually prove the controls — a control whose "test" does not fail when the control is removed is recorded as unverified and a test gap is filed.

## Security notes
This is the sign-off gate. Sensitive findings are handled per the program's disclosure rules and are not written into public tickets before remediation.

## Accessibility notes
Confirms that the safety-transparency affordances (emulation caveat, native-SL notice, degraded banner) are present as designed — they are security controls, and D07's audit result is accepted as evidence.

## Performance notes
Confirms the performance-shaped controls (reprice floor, protective reserve, child caps) are enforced in code and configuration, not merely documented, and that no config path can lower them below the floor at runtime.

## Observability
Confirms the non-repudiation audit set from X01 is complete in the shipped code, spot-checked against the audit log for each verb.

## Definition of Done
- [ ] White-box review complete with notes attached.
- [ ] Control-coverage matrix complete; every Critical/High implemented-and-verified.
- [ ] Native-SL coverage on the algo path confirmed with the E32 owners.
- [ ] SAST/SCA/secrets scans clean or triaged.
- [ ] All findings fixed or accepted with Owner sign-off and follow-ups filed.
- [ ] Sign-off comments posted on the epic and every `security`-labelled story.
- [ ] Algo surface added to the E43 pen-test scope and to the R3 PRR input.

## Dependencies
E33-X02 (abuse-case results), E33-Q04 (chaos safety results), E33-D07 (transparency-affordance audit), E32 (native-SL invariant owners).

## Branch
N/A (review activity); fixes land on `fix/e33-sec-*`.

## References
""" + SEC_REFS,
)
