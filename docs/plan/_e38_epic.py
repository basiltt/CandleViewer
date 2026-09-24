# -*- coding: utf-8 -*-
from _e38_gen import t, body, MS, PH, AREA

EPIC_BODY = """## Context
R3 "Trading on demo" executes **everything** against Bybit demo; there is no code path that can reach live until R4 flips the gate (`docs/plan/30-release-roadmap.md` section 7). E38 is the epic that owns that statement. It is simultaneously:

1. **The environment boundary.** SCR-075 is described in `docs/plan/14-screens-catalogue.md` as "the single most safety-critical visual element in the app", and `docs/plan/04-security-program.md` SR-040a requires the environment capability matrix to be "enforced in code, not documentation". Threats **W9** (code assuming WS order entry exists on demo, leaving orders unplaced or duplicated) and **W10** (demo and live endpoints mixed within one session) are named in the security program with this epic's work as their control.
2. **The honest simulator.** `docs/plan/24-internal-schemas.md` section 12 specifies the local paper matcher (module **M16**) field by field - queue position, latency, fees, funding, margin - because a simulator that ignores those lies, and a lying simulator is worse than none: it manufactures confidence (risk **R12**).
3. **The parity evidence base.** US-PAPER-008's report is what makes R4 "a gating exercise rather than a re-architecture" (roadmap section 7.1 goal 5). The roadmap dependency graph records `E38 --> E44`: whatever this epic leaves ambiguous becomes a live-money problem in R4.

The epic sits at S18-S19, the last two sprints of R3, and depends on `E29` (OMS and order state machine) and `E26` (replay engine) per the roadmap's dependency graph.

## Scope / Deliverables
**User stories covered (all Must/Should in the PAPER domain, `docs/plan/11-user-stories.md` section 21):**
- **US-PAPER-001** Bybit demo integration (Must) - E38-S01
- **US-PAPER-002** Explicit Demo/Live switching (Must) - E38-S02 (backend), E38-S04 (UI)
- **US-PAPER-003** Demo/Live isolation gating (Must) - E38-T02 (server enforcement), E38-S04 (client guard)
- **US-PAPER-004** Local simulated fill engine (Should) - E38-S03, E38-S05
- **US-PAPER-005** Paper P&L identical to live (Must) - E38-S03 (same accounting path), E38-S05 (separate reporting and labelling)
- **US-PAPER-006** Reset paper balance (Should) - E38-S06
- **US-PAPER-007** Demo eligibility per manager (Should) - E38-S07
- **US-PAPER-008** Environment parity report (Should) - E38-K01, E38-S08, E38-T03

**Screens:** SCR-074 Environment switcher, SCR-075 Demo/Live banner and per-panel badges, SCR-079 Account detail drawer (reset section), SCR-099 Replay paper-trading results, SCR-122 Admin user detail (eligibility section), SCR-137 Admin security centre (parity + fidelity sections).

**Components:** CMP-074 EnvBanner, CMP-075 EnvBadgeLocal, CMP-139 EnvironmentAwareOrderGuard, plus composition of CMP-027, CMP-028, CMP-036, CMP-043, CMP-044, CMP-049, CMP-050, CMP-087, CMP-093, CMP-099, CMP-104, CMP-106, CMP-116, CMP-128, CMP-129, CMP-167, CMP-168, CMP-175, CMP-178; contributes a new simulated badge to the design system.

**Backend module:** **M16 Paper Matcher** (`docs/plan/20-architecture.md` section 3.7, C11) - `FillModel`, `QueueEstimator`, `FeeModel`, `PaperLedger` - plus the environment capability matrix and the isolation middleware.

**API:** `POST /session/environment` (implemented), `PUT /users/{userId}/account-access` (extended with eligibility), and new: `POST /exchange-accounts/{accountId}/paper-reset`, `GET /admin/parity` plus its verification endpoint, `GET /admin/paper-fidelity`. Environment enforcement is applied to every account-mutating trading route.

**WS:** `system` topic (environment switch phases and the resulting environment), `is_paper` on every private frame (`docs/plan/23-ws-protocol.md` section 13.1).

**DB:** `exchange_accounts.env`, `is_paper` columns across orders/positions/executions/trade groups, `user_account_access` extended with live eligibility and its acknowledgement, paper ledger and parity-observation storage.

## Out of scope
- **Live order entry.** The `live_trading` flag stays off through R3; turning it on is E44 after the E43 pen-test.
- **Android and any separate admin application** - owner decisions, permanently out of scope.
- Non-USDT-perp products (spot, options, inverse).
- Resetting a Bybit demo account's balance at the exchange - only the local paper ledger is reset.
- Auto-tuning the fill model from divergence results; tuning stays a human decision.
- Journal analytics computation (E41), replay transport (E26), fan-out (E34), the OMS itself (E29) - E38 consumes them.

## Acceptance criteria
```gherkin
Scenario: Demo and live can never mix
  Given a session in one environment
  When any account-mutating trading route is called against an account in the other environment, including by a crafted request bypassing the UI
  Then it is refused with 403, no state changes, and a high-severity audit row is written - proven across every trading route by an automated route-coverage test

Scenario: Switching to live is deliberate, gated and complete
  Given a session in demo
  When the user switches to live
  Then it requires a typed confirmation phrase, step-up authentication and the live_trading flag; no hotkey can trigger it; one-click trading is disarmed; every private subscription is torn down and rebuilt; and a half-switched state is never reachable, including across a backend restart mid-transition

Scenario: The environment is stated on every trading-capable surface
  Given any trading panel, including floated and maximised Electron windows
  When it is rendered
  Then it states DEMO or LIVE in text plus icon plus pattern, remains unambiguous in greyscale and in three colour-vision simulations, and includes the environment in its accessible name

Scenario: The simulator is honest and can never reach the exchange
  Given the paper matcher
  When orders are simulated
  Then fills respect queue position, latency, book depth, real fee rates and funding; the applied FillModelConfig is disclosed with every result set; a structural test proves the paper package imports no network client; and a nightly divergence job compares simulated against real demo fills, opening a defect above one tick p95 slippage or ten percentage points fill-rate divergence

Scenario: Paper results never contaminate live statistics
  Given a journal containing both simulated and real trades
  When analytics are computed
  Then simulated rows are excluded by default, every view labels them, and promotion of a simulated session to the journal is flagged and audited

Scenario: The parity report is generated and current
  Given the maintained parity data file plus runtime observations
  When the report is viewed
  Then every known difference is listed with its source and last-verified date, demo-only failures appear as candidate items, and items unverified for 90 days are flagged

Scenario: Eligibility is a server-side attribute with safe revocation
  Given a manager without live eligibility
  Then no live action succeeds by any path; and when live access is revoked while live positions are open, those positions remain manageable in reduce-only mode while new entries are refused
```

## Technical notes / design
- **One code path, two environments.** The only environment-aware code is the adapter's immutable capability record and key selection; an architecture test asserts the string `demo` does not appear in `cv/oms/`. This is what makes R4 a gate flip rather than a rewrite.
- **One choke point.** Environment enforcement lives in a single FastAPI dependency (E38-T02) that returns an `EnvironmentContext` handlers must accept, so omission is a type error. A route-coverage test over the OpenAPI document fails CI when a new trading route lacks it.
- **`is_paper` is orthogonal to `environment`.** A paper fill still belongs to a real environment (demo, or live when replaying live-recorded data). `docs/plan/23-ws-protocol.md` section 13.1 is explicit that collapsing them would lose information; the UI must therefore show two distinct badges.
- **The matcher rides the shared bus.** Replay re-emits recorded events with the same types onto the same bus (`docs/plan/24-internal-schemas.md` section 13), so the matcher works identically over live and recorded data, and its determinism supports R3 exit criterion 6.
- **Structural versus enforced controls.** E38-X01 classifies each control; structural controls (separate client instances, no transport import in `cv/paper/`) get import-time or compile-time tests, enforced controls get runtime tests. The distinction drives the regression pack.

## Test plan
- **Unit** - queue estimator table-driven suite (the highest-value set in the epic), book walk VWAP, latency races, fee and funding maths, liquidation tiers, environment refusal matrix, eligibility derivation, staleness boundaries. Coverage: >=90% on `cv/paper/` and the safety-critical middleware, >=85% backend elsewhere, >=80% frontend.
- **Contract** - `enum_parity_environment`, the new endpoints, error-registry entries, WS frame shapes, and the route-coverage gate.
- **Integration** - recorded demo fixtures for submit/partial-fill/amend/cancel/reject/reconnect; replay-driven matcher sessions with restart recovery; reset atomicity; revocation with open positions.
- **E2E** - nine Playwright suites across web and Electron (E38-Q02), including the crafted cross-environment request and the floating-window badge.
- **Perf** - budget #4 (submit-to-ack p95 <300 ms on demo, hard R3 gate), matcher throughput at >=20x real time, switch transition p95 <=2 s, memory budget #8 (E38-Q03).
- **Chaos** - restart mid-switch at each phase, WS disconnect mid-order, restart with open simulated state, Postgres failure mid-reset, audit-writer failure must fail closed, clock skew, WS flapping during a switch (E38-Q04).
- **Security** - STRIDE (E38-X01), abuse cases plus durable Semgrep/ZAP rules (E38-X02), review and sign-off (E38-X03).
- **A11y** - axe-core in CI per state plus NVDA manual passes (E38-Q05).

## Security notes
- STRIDE model at `docs/security/threat-models/E38-paper-trading.md` (E38-X01). Highest-rated threats: a simulated order reaching the exchange (Critical), a demo session reaching live (Critical), a manager self-granting live eligibility (High), an unaudited environment switch or reset (High), a not-permitted message disclosing other users' grants (Medium).
- Implements **SR-040a** (environment capability matrix in code), supports **SR-119** (single backend chokepoint for exchange traffic) and **SR-043** (armed state for live). Demo keys are handled identically to live keys (SR-003, SR-004); CI never holds demo credentials (SR-140).
- Every ticket touching RBAC, order placement or account-scoped state carries the `security` label per `docs/plan/02-definition-of-ready-done.md` section 8, and cannot reach Done without a Security engineer review.
- Data classification: financial transaction and simulation data; API credentials by reference only; no secret is rendered on any E38 surface.

## Accessibility notes
- WCAG 2.2 AA across all six surfaces, with no "internal tool" exception for the admin screens.
- The environment distinction must be text plus icon plus pattern, unambiguous in greyscale and in deuteranopia, protanopia and tritanopia simulations - verified in design (E38-D05) and on the built app (E38-Q05).
- The band is `role="status"` and polite; the post-switch confirmation is `role="alert"` announced once; per-panel badges are `role="img"` with static labels to prevent an announcement storm.
- Every SCR-099 chart has a keyboard-reachable table alternative; the destructive reset dialog announces the counts it will discard and does not default focus to the destructive button.
- An imperceptible environment indicator is treated as a security defect, not only an accessibility one.

## Performance notes
- Budget **#4** order submit to ack p95 <300 ms on demo is a **hard R3 exit gate**; E38-S01 owns it and E38-Q03 measures it with backend-internal and exchange-RTT components separated.
- Budget **#8** <=300 MB resident per actively-recorded symbol during matcher replay; budget **#15** replay at up to 100x without the matcher becoming the bottleneck.
- The environment switch blocks order entry for its whole duration - p95 <=2 s per SCR-074, measured per phase.
- The environment band must not remount on route change and an environment change must not re-render trading panel bodies; re-badging must not breach frame budget **#1**.

## Observability
- Metrics: `cv_capability_refusals_total`, `cv_environment_rejections_total`, `cv_environment_switch_duration_seconds`, `cv_environment_switch_failures_total`, `cv_orders_submitted_total{environment}`, `cv_order_ack_latency_seconds{environment}`, `cv_paper_fills_total`, `cv_paper_rejections_total`, `cv_paper_resets_total`, `cv_paper_divergence_*`, `cv_parity_items{status}`, `cv_live_eligible_users`.
- Audit events: `session.environment_switched`, `session.environment_switch_refused`, `trading.environment_mismatch_rejected`, `paper.balance_reset`, `paper.balance_reset_refused`, `user.live_access_granted|revoked|acknowledged`, `parity.item_verified`, `journal.simulated_import`.
- Alerts: divergence threshold breach, missed divergence run, demo private WS disconnected with open orders, audit-writer failure, clock skew beyond 1000 ms.

## Definition of Done
- [ ] Every child ticket Done (100% rollup) or explicitly descoped with a recorded disposition.
- [ ] Epic-level acceptance criteria verified end to end on staging (demo), not merely per child.
- [ ] Coverage floors held: >=90% on `cv/paper/` and the safety-critical middleware, >=85% backend, >=80% frontend; zero open P0/P1 against E38 scope.
- [ ] a11y: axe-core CI green on all six surfaces and states, manual NVDA passes recorded, colour-vision verification on the built app (E38-Q05).
- [ ] perf: budgets #1, #4, #8, #15 and the switch transition measured and recorded against `docs/plan/06-performance-and-load-standard.md` (E38-Q03).
- [ ] security: STRIDE finalised, all Critical/High findings closed or Owner-accepted with expiry, Security engineer sign-off, durable Semgrep/ZAP rules running as required checks (E38-X01..X03).
- [ ] QA: epic-level regression pack and both exploratory charters executed with recorded sign-off (E38-Q06).
- [ ] design: all design tickets Done >=2 sprints ahead of their consuming stories; design QA complete with discrepancies closed (E38-D07).
- [ ] Docs reconciled with shipped behaviour and ADR-0016 amended (E38-T04); `make contracts` green.
- [ ] R4 handover statement written: what E38 guarantees about environment separation, what it does not, and what E44 must re-verify.
- [ ] Demoed to the Owner at a Sprint Review with explicit acceptance recorded.

## Dependencies
- `blocked_by: E29` (OMS core and order state machine - the matcher and demo routing reuse it rather than reimplementing it) and `E26` (replay engine - supplies recorded book and trade events on the shared bus), per the roadmap dependency graph `E29 --> E38`, `E26 --> E38`.
- `E27` (accounts and the API-key vault) supplies per-environment accounts and encrypted demo keys; `E09` (auth, sessions, 2FA, RBAC) supplies step-up and session resolution; `E42` (admin screens) hosts SCR-122 and SCR-137 and owns the `live_trading` flag; `E41` (journal and analytics) supplies the journal data layer that must honour the simulated-exclusion rule; `E30`/`E31` supply the trading surfaces that carry the per-panel badge.
- **Downstream:** `E38 --> E44` (live-enablement gating) - E38's parity report, capability matrix and isolation middleware are E44's evidence base and enforcement layer.

## Branch
Per-ticket `feat/e38-*`, `design/e38-*`, `test/e38-*`, `spike/e38-*` and `chore/e38-*` branches as named on each child. No epic-level long-lived branch; PRs stay at or under 400 LOC and land on `main` through the merge queue.

## References
- `docs/plan/11-user-stories.md` section 21 PAPER (US-PAPER-001..008)
- `docs/plan/14-screens-catalogue.md` SCR-074, SCR-075, SCR-079, SCR-099, SCR-122, SCR-137
- `docs/plan/15-component-catalogue.md` CMP-074, CMP-075, CMP-139
- `docs/plan/18-traceability-matrix.md` (PAPER rows)
- `docs/plan/20-architecture.md` section 3.7, C11 Paper Matcher
- `docs/plan/21-database-schema.md` `exchange_env`, `is_paper`, `user_account_access`
- `docs/plan/22-api-openapi.yaml` `POST /session/environment`, `PUT /users/{userId}/account-access`
- `docs/plan/23-ws-protocol.md` section 13.1 `is_paper`, `system` topic
- `docs/plan/24-internal-schemas.md` section 12 paper matcher (normative), section 13 replay bus, section 14 adapter, section 15.2 RBAC 4-tuple
- `docs/plan/04-security-program.md` SR-040a, SR-043, SR-119, threats W9/W10
- `docs/plan/06-performance-and-load-standard.md` budgets #1, #4, #8, #13, #15
- `docs/plan/30-release-roadmap.md` section 7 R3, dependency graph `E29/E26 --> E38 --> E44`
- `docs/plan/32-risk-register.md` R12 backtest bias, R9 advice boundary

## Child dependency graph
```mermaid
graph TD
    subgraph design["Design (S16-S17)"]
        D01[D01 UX research]
        D02[D02 Hi-fi switcher + chrome]
        D03[D03 Hi-fi parity/reset/eligibility]
        D04[D04 Hi-fi simulated results]
        D05[D05 A11y design review]
        D06[D06 Handoff]
    end
    subgraph spike["Spike + security (S17)"]
        K01[K01 Demo-vs-live probe]
        X01[X01 STRIDE]
    end
    subgraph be["Backend (S18)"]
        T01[T01 Capability matrix]
        T02[T02 Isolation middleware]
        S01[S01 Demo integration]
        S02[S02 Environment switch]
        S03[S03 Paper matcher]
    end
    subgraph fe["Frontend + jobs (S19)"]
        S04[S04 Env chrome + switcher UI]
        S05[S05 Simulated results UI]
        S06[S06 Paper reset]
        S07[S07 Live eligibility]
        S08[S08 Parity report]
        T03[T03 Divergence job]
    end
    subgraph qa["QA (S18-S19)"]
        Q01[Q01 Test plan]
        Q02[Q02 E2E suites]
        Q03[Q03 Perf/load]
        Q04[Q04 Chaos]
        Q05[Q05 A11y audit]
        Q06[Q06 Regression + sign-off]
    end
    subgraph close["Close-out (S19)"]
        D07[D07 Design QA]
        X02[X02 Abuse cases]
        X03[X03 Security sign-off]
        T04[T04 Doc reconcile]
    end

    D01 --> D02
    D01 --> D03
    D01 --> D04
    D02 --> D05
    D03 --> D05
    D04 --> D05
    D05 --> D06

    K01 --> T01
    K01 --> X01
    K01 --> S08
    T01 --> T02
    T01 --> S01
    T01 --> S08
    T02 --> S02
    T02 --> S04
    T02 --> S07
    S01 --> S03
    S01 --> S06
    S01 --> T03
    S02 --> S04
    S03 --> S05
    S03 --> S06
    S03 --> T03

    D06 --> S04
    D06 --> S05
    D06 --> S06
    D06 --> S07
    D06 --> S08
    D06 --> Q01
    K01 --> Q01

    S04 --> Q02
    S05 --> Q02
    S06 --> Q02
    S07 --> Q02
    S08 --> Q02
    Q01 --> Q02
    S01 --> Q03
    S02 --> Q03
    S03 --> Q03
    S02 --> Q04
    S03 --> Q04
    D05 --> Q05
    S04 --> Q05
    S05 --> Q05
    S06 --> Q05
    S07 --> Q05
    S08 --> Q05

    Q02 --> Q06
    Q03 --> Q06
    Q04 --> Q06
    Q05 --> Q06

    S04 --> D07
    S05 --> D07
    S06 --> D07
    S07 --> D07

    X01 --> X02
    T02 --> X02
    S02 --> X02
    S03 --> X02
    S07 --> X02
    X02 --> X03
    Q06 --> X03
    S08 --> X03

    S03 --> T04
    S08 --> T04
    T03 --> T04
```
"""

t(key="E38", kind="Epic", title="Paper trading & demo/live parity",
  labels=["type/feature", AREA, "priority/p0", "security", "design", "qa", "a11y", "perf"],
  component="cross-cutting", phase=PH, sprint="Sprint 18", priority="P0 Critical",
  perspective="Architecture", risk="R9 Advice boundary", estimate=67, parent=None,
  blocked_by=["E29", "E26", "E27", "E09"], milestone=MS, body=EPIC_BODY)
