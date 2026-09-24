# -*- coding: utf-8 -*-
"""E43 QA tickets Q01-Q06."""
import json, io, os

T = []
def t(**k):
    k.setdefault("phase", "P4 Backtesting & Scripting")
    k.setdefault("milestone", "R4 Live enablement")
    T.append({kk: k[kk] for kk in ["key","kind","title","labels","component","phase","sprint",
        "priority","perspective","risk","estimate","parent","blocked_by","milestone","body"]})

t(key="E43-Q01", kind="Task",
  title="Black-box test plan for the security centre, posture checks and the Live gate",
  labels=["type/test","area/auth-rbac","priority/p0","qa","security"],
  component="web", sprint="Sprint 20", priority="P0 Critical", perspective="Test",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-D01","E43-D02"],
  body="""## Context
`docs/plan/02-definition-of-ready-done.md` section 3.2 makes QA sign-off non-skippable for every Story, and `docs/plan/03-testing-strategy.md` requires a black-box plan per feature alongside the white-box review. E43's two stories (E43-S01 Live gate, E43-S02 posture checks) are unusual QA subjects: the correct behaviour is frequently *refusal*, and the most dangerous defect is a **false pass** - a gate that opens or a check that reports "safe" when the underlying evidence is missing or stale.

This ticket writes the plan before the stories are built, so the stories are built against it.

## Scope / Deliverables
- A black-box test plan document covering, for each of US-ADMIN-010 and US-ADMIN-012:
  - Every documented state of SCR-137 (`compliant`, `findings outstanding`, `Live enablement blocked`) and SCR-128 (per-key verdicts incl. `unverifiable`, drift, overdue rotation) and SCR-136 (integrity verified / break detected).
  - Every acceptance scenario in the two user stories, restated as executable steps with preconditions, data setup, expected observable result and the audit event expected to be written.
  - **Role matrix**: every scenario repeated for Owner, Manager and Viewer, with the expected denial shape for non-Owners.
  - **False-pass hunting**: explicit cases where a check's data source is unavailable, stale, or contradicts app configuration - each must produce a non-passing verdict and must keep the gate closed.
  - **Negative gate cases**: enable attempted with each individual item outstanding, in turn; enable attempted via the API directly; attestation withdrawn while enabled; evidence going stale while enabled.
  - Emergency re-disable, including the reduce-only assertion and the 10-second push bound.
- Data-setup recipes: how to produce each precondition on staging (a key with withdrawal enabled at the exchange, an expired key age, an out-of-allowlist egress IP, a broken audit chain, a user without 2FA) - using demo credentials only.
- Traceability table mapping every plan step to the user-story scenario and to the SR it exercises, feeding `docs/plan/03-testing-strategy.md`'s SR-150 table.
- A defect-reporting template for this epic that requires: role used, exact endpoint/screen, expected vs actual, the audit event observed (or its absence), and a severity proposal using the pen-test severity language so QA findings and tester findings are comparable.

## Out of scope
- Executing the plan (executed against the build; sign-off recorded in E43-Q06).
- Exploratory testing (E43-Q02), a11y audit (E43-Q05), load (E43-Q04), automation (E43-Q03).

## Acceptance criteria
```gherkin
Scenario: Every story scenario is covered
  Given the acceptance criteria of US-ADMIN-010 and US-ADMIN-012 and of tickets E43-S01 and E43-S02
  Then each scenario maps to at least one executable plan step
  And the mapping is recorded in the traceability table

Scenario: Every state is reachable on staging
  Given the data-setup recipes
  When a tester follows them
  Then each documented screen state can be produced on staging without a developer's help and without any live credential

Scenario: False-pass cases are explicit
  Given a check whose data source is unavailable or stale
  Then the plan contains a step asserting the verdict is not pass and that the Live gate remains closed

Scenario: The plan is role-complete
  Given the three roles
  Then every scenario states the expected outcome per role, including the exact denial shape for non-Owner roles
```

## Technical notes / design
- Denial shape to assert: identical to a non-existent resource, with no existence oracle (see E43-T09) - the plan must assert response equality, not merely "an error occurred".
- Audit assertions are part of the black-box plan because the audit log is user-visible on SCR-135/SCR-136: a step is not passed unless the expected audit entry appears with the expected actor, severity and redaction.
- Staging data setup must never use a live key; a key with withdrawal enabled is created on a **demo** account specifically for the negative case and removed afterwards, with the setup/teardown recorded.

## Test plan
This ticket *is* a test plan; its own verification is a review: QA lead, the Security engineer and the owners of E43-S01/S02 confirm coverage and feasibility in comments.

## Security notes
The plan itself describes how to produce insecure states on staging; it is stored with the same access control as the security program doc. All setup uses demo credentials (SR-140/SR-144). The withdrawal-enabled negative case must be created and destroyed within the test window and recorded, since it deliberately violates the standing key policy on a demo account.

## Accessibility notes
The plan includes keyboard-only execution of every interactive step, so a11y defects surface during functional testing rather than only in the dedicated audit (E43-Q05).

## Performance notes
The plan records observed latency for the security summary load and the flag-push delay, so the <= 1% load and 10-second push budgets are checked in the functional pass rather than only under load.

## Observability
Each step names the metric or audit event that should move, making the plan double as an observability check.

## Definition of Done
- [ ] Plan document written and linked on E43-S01 and E43-S02.
- [ ] Traceability table complete and merged into `docs/plan/03-testing-strategy.md`.
- [ ] Data-setup recipes validated once on staging.
- [ ] Reviewed and approved by the QA lead and the Security engineer.
- [ ] Defect template adopted for the epic.

## Dependencies
- **E43-D01**, **E43-D02** - the plan is written against the signed-off designs so expected states are unambiguous.

## Branch
`chore/e43-qa-test-plan` (document under `docs/plan/` or the QA test-management tool, linked here).

## References
- `docs/plan/03-testing-strategy.md`; `docs/plan/02-definition-of-ready-done.md` sections 3.1, 3.2, 8.
- `docs/plan/11-user-stories.md` US-ADMIN-010, US-ADMIN-012.
- `docs/plan/14-screens-catalogue.md` SCR-137, SCR-128, SCR-136.
- `docs/plan/04-security-program.md` sections 7.2, 14.6.""")

t(key="E43-Q02", kind="Task",
  title="Exploratory charters for authentication, authorisation and admin surfaces",
  labels=["type/test","area/auth-rbac","priority/p1","qa","security"],
  component="api", sprint="Sprint 20", priority="P1 High", perspective="QA",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-T03","E43-T04","E43-T09"],
  body="""## Context
Scripted tests find what we thought of; the pen-test finds what an attacker thinks of. Exploratory charters sit between the two, and they are cheap insurance immediately before a paid engagement: every defect QA finds in the week before the window is a tester-day spent on something harder.

`docs/plan/03-testing-strategy.md` includes exploratory testing as a named layer. This ticket runs time-boxed, charter-driven sessions over exactly the surfaces the tester will attack (`docs/plan/04-security-program.md` section 13.2), feeding anything found into remediation before the freeze.

## Scope / Deliverables
Six time-boxed charters (90 minutes each, session-notes recorded, defects filed with the E43-Q01 template):
1. **Authentication** - explore login, TOTP, recovery codes, lockout and unlock: attempt enumeration through timing and error differences, attempt lockout of another user, attempt TOTP replay across tabs, explore what happens when a recovery code is used concurrently in two sessions.
2. **Session lifecycle** - explore rotation boundaries: hold a request in flight across a rotation, log out in one tab while acting in another, change role mid-session, explore "remember this device" against TOTP, explore what survives a backend restart.
3. **Authorisation** - explore object references: swap ids between accounts in every payload, explore nested ids (a rule referencing another manager's account, a trade group containing a non-granted account), explore whether error bodies differ between "forbidden" and "not found", explore WS topic guessing.
4. **Admin surfaces** - explore SCR-137/SCR-128/SCR-135/SCR-136 as a Manager and as a Viewer, explore "view as" (SCR-124) for leakage, explore whether any admin mutation is reachable by a non-Owner through an indirect path (bulk endpoint, export, job polling).
5. **The gate** - explore every ordering of attestation, evidence change, enable, disable and re-enable; explore concurrent Owner sessions racing the flag; explore what the UI shows when evidence goes stale while the dialog is open.
6. **Data-handling and export** - explore audit export, journal export and error paths for secret leakage; explore oversized/malformed inputs on admin forms; explore what appears in an error message when a dependency is down.
- A consolidated findings report with severity proposals, filed defects, and a "what we could not explore" list handed to the pen-tester so their time is directed at the gaps.

## Out of scope
- The scripted plan (E43-Q01), automation (E43-Q03), the pen-test itself (E43-X02).

## Acceptance criteria
```gherkin
Scenario: Every charter is executed and recorded
  Given the six charters
  Then each has session notes recording the time box, the areas covered, the risks explored and the outcomes
  And any defect found is filed with the epic defect template

Scenario: Findings reach remediation before the freeze
  Given a defect found during exploration with a proposed severity of High or Critical
  Then it is triaged within one working day and either fixed before the code freeze or explicitly deferred with the tester informed

Scenario: Gaps are handed over, not hidden
  Given areas a charter could not cover in its time box
  Then they are listed in the handover note to the penetration tester
```

## Technical notes / design
- Sessions run against staging with demo credentials and per-role tester identities, mirroring the pen-test's rules of engagement so findings are reproducible by the tester.
- Session notes follow a fixed structure: charter, duration, setup, observations, bugs, questions, next-time. Notes are archived with the evidence pack.
- Testers must not use production credentials or touch the live environment at any point.

## Test plan
Exploratory by definition; the deliverable is the session notes plus filed defects. Any confirmed defect gains an automated regression test through its own fix ticket (SR-153 applies to internal findings too, with an `INT-` finding id per E43-T11's registry).

## Security notes
Exploration deliberately attempts privilege escalation and credential leakage on staging; it is authorised by the Owner in advance and time-boxed. Findings are treated as sensitive until fixed and are not discussed in public channels. Any accidental discovery of a real secret triggers IR-02 (rotate first).

## Accessibility notes
Charters 4 and 5 are executed keyboard-only for at least part of each session, so interaction defects that also block screen-reader users are caught early and routed to E43-Q05.

## Performance notes
N/A, except that any observed latency anomaly during exploration is noted and routed to E43-Q04's load profile.

## Observability
Each charter checks whether the actions taken produced the expected audit events and metric movements - absent telemetry is itself a finding, since the pen-test's detection questions depend on it.

## Definition of Done
- [ ] All six charters executed within Sprint 20 and session notes archived.
- [ ] Defects filed with proposed severities; High/Critical triaged within one working day.
- [ ] Handover note delivered to the penetration tester before the window opens.
- [ ] QA lead and Security engineer reviewed the consolidated report.

## Dependencies
- **E43-T03**, **E43-T04**, **E43-T09** - exploration targets the corrected implementations, not the pre-hardening ones.
- Feeds **E43-X02** (handover note) and **E43-X03** (internal findings enter the same register).

## Branch
`chore/e43-qa-exploratory` (session notes; no code).

## References
- `docs/plan/03-testing-strategy.md`; `docs/plan/04-security-program.md` sections 13.2, 13.4.
- `docs/plan/14-screens-catalogue.md` SCR-124, SCR-135, SCR-136, SCR-137.""")

t(key="E43-Q03", kind="Task",
  title="Automate the SR-152 negative-scenario E2E suite",
  labels=["type/test","area/auth-rbac","priority/p0","qa","security"],
  component="api", sprint="Sprint 20", priority="P0 Critical", perspective="Test",
  risk="None", estimate=5, parent="E43", blocked_by=["E43-T03","E43-T09","E43-T04"],
  body="""## Context
SR-152 enumerates the negative tests that MUST exist: *"CSRF absent/invalid, wrong `Origin`, expired session, unarmed live order, exceeded risk cap, missing SL, cross-account access, rule budget breach, and desynced order book"* - verified at the integration and e2e layers. Several of these are owned by other epics' implementations (risk caps by E39, native SL by E32, rule budgets by E37, book resync by the book engine), but nobody owns the **suite** that proves all nine hold simultaneously on the build that goes to the pen-test.

This ticket builds that suite, running against staging as a pre-freeze gate and thereafter as a required check.

## Scope / Deliverables
Automated scenarios, Playwright (web + Electron) and pytest integration as appropriate, one per SR-152 item:
1. **CSRF absent / invalid / cross-session** - state-changing request refused, audited, no mutation.
2. **Wrong `Origin` / `Sec-Fetch-Site`** on REST and on the **WS handshake** - refused before subscription authorisation.
3. **Expired session** (idle and absolute) and **stale session on the order path** (12 h trading-freshness) - refused with a distinguishable re-auth error, read paths behaving per spec.
4. **Unarmed live order** (SR-043: live submission requires the time-boxed armed state plus a per-request arm nonce; demo/paper does not) - refused when unarmed, accepted when armed, arm state defaulting off after login and expiring.
5. **Exceeded risk cap** - order refused server-side with an auditable reason code, reduce-only actions still available.
6. **Missing stop-loss** - an order path that would produce a position without a native exchange-side SL is refused (the fan-out safety invariant; `cv-order-without-sl` backs it statically).
7. **Cross-account access** - the IDOR matrix from E43-T09 exercised end-to-end for orders, positions, rules, journal, audit, keys and profiles.
8. **Rule budget breach** - a rule exceeding its evaluation/action budget is stopped and audited, without starving other rules.
9. **Desynced order book** - a sequence gap forces resync and the order path fails closed while the book is untrusted.
- Each scenario asserts three things: the refusal, the **audit event**, and the absence of side effects (no order at the exchange fixture, no state mutation).
- Suite runs as a required check (`e2e-web`, `e2e-electron` and `integration` already exist per `docs/plan/04-security-program.md` section 12.3); this suite is tagged so it can also be run alone pre-freeze.
- Shared fixtures are taken from / contributed to E43-T11's security fixture set to avoid duplication.

## Out of scope
- Implementing the controls themselves (owned by E32/E34/E37/E39 and E43-T03/T04/T09); this suite proves they hold together.
- Load and DoS (E43-Q04); chaos scenarios (E45).

## Acceptance criteria
```gherkin
Scenario: All nine SR-152 items are automated
  Given the SR-152 list
  Then each item has at least one automated scenario in the suite
  And the SR-150 traceability table in docs/plan/03-testing-strategy.md references it

Scenario: Each refusal is complete
  Given any negative scenario
  Then the request is refused, the expected audit event is written, and no side effect is observable at the exchange fixture or in the database

Scenario: The suite fails when a control is removed
  Given a deliberately reverted control in a scratch branch
  When the suite runs
  Then the corresponding scenario fails and names the control

Scenario: Arming behaves as specified
  Given a live-configured session that has just logged in
  Then the armed state is off
  And an order is refused until arming is performed, and is refused again after the arm window expires
```

## Technical notes / design
- Exchange interactions use recorded Bybit fixtures (`packages/fixtures/`), so "no side effect at the exchange" is assertable deterministically.
- The unarmed-order scenario runs in a live-**configured** but fixture-backed environment, never against real Bybit live: the arming control is environment-conditional (SR-043 exempts demo/paper), so the test must set the environment flag rather than use real credentials.
- Audit assertions query `audit_log` directly and assert actor, action, severity and redaction.
- Scenarios are independent and can run in parallel; each seeds its own users, accounts and grants.

## Test plan
- Meta-verification: a mutation-style check where each control is disabled in a scratch build and the suite is expected to fail exactly the corresponding scenario (recorded once, not run continuously).
- Runtime budget recorded; the suite is part of the pre-freeze gate.
- Coverage target: contributes to M14/M18 coverage; the suite's own value is measured by SR-152 completeness.

## Security notes
This suite is the automated core of the pen-test's "did you at least do the obvious things" question. It touches the order path, so it must run only against demo/fixture environments (SR-140). A failing scenario is a release blocker, not a flaky test to be retried - quarantining a scenario requires Security engineer approval recorded on the ticket.

## Accessibility notes
The web-layer scenarios execute their user journeys through accessible selectors (roles and accessible names) rather than CSS/test ids where practical, so a regression that breaks accessible naming also breaks the suite.

## Performance notes
Suite runtime must fit the pipeline duration budget in `docs/plan/06-performance-and-load-standard.md`; parallelise by scenario and keep per-scenario seeding cheap.

## Observability
Each scenario asserts its audit event, which doubles as a check that the audit catalogue (section 8.2) is actually wired for these paths.

## Definition of Done
- [ ] All nine SR-152 items automated and green on the freeze candidate.
- [ ] Suite registered in the required checks and tagged for standalone pre-freeze execution.
- [ ] SR-150 traceability table updated.
- [ ] Meta-verification recorded (each control's removal fails the right scenario).
- [ ] QA sign-off and Security engineer review comments.
- [ ] PR merged via the merge queue with 2 approvals incl. a code-owner.

## Dependencies
- **E43-T03** (CSRF/origin/session semantics), **E43-T09** (authorisation matrix), **E43-T04** (auth limits) supply the final behaviours asserted.
- Shares fixtures with **E43-T11**.

## Branch
`test/e43-negative-e2e-suite`. PR size guidance: land in three PRs grouped by layer (auth/session, authorisation, order-path invariants).

## References
- `docs/plan/04-security-program.md` SR-043, SR-152, SR-153, sections 12.3, 13.2.
- `docs/plan/03-testing-strategy.md`; `docs/plan/23-ws-protocol.md`; `docs/plan/22-api-openapi.yaml`.""")

t(key="E43-Q04", kind="Task",
  title="Rate-limit and auth denial-of-service load profiles",
  labels=["type/test","area/auth-rbac","priority/p1","qa","security","perf"],
  component="infra", sprint="Sprint 21", priority="P1 High", perspective="Test",
  risk="R3 Real-time cost", estimate=3, parent="E43", blocked_by=["E43-T04","E34"],
  body="""## Context
Pen-test scope includes **rate-limit DoS** (`docs/plan/30-release-roadmap.md` section 8.2 lists it explicitly in E43's content) and the WebSocket layer's "message flooding, slow-consumer effects" (section 13.2 item 6). The application has three distinct rate-limiting layers to prove under load (SR-044): per-session API limits (generous for reads, tight for mutations), per-Bybit-UID budgets with the critical SR-044a rule that limits are **per UID, shared across every key on that UID**, and per-rule budgets. On top sits the global per-IP ceiling (SR-044c: 600 req/5 s across all UIDs sharing the egress IP, breaching it returns 403 with a >= 10-minute lockout **that would strand open positions**).

That last consequence is why this is a security test and not merely a performance test: an attacker - or a runaway rule - who can burn the egress IP's budget can prevent the Owner from exiting a position. SR-071's reserved quota for risk-reducing actions is the control, and this ticket proves the reserve actually holds under pressure.

## Scope / Deliverables
- **k6/Locust profiles** under `infra/k6/`:
  1. **Auth flood** - sustained failed-login attempts across many usernames from one source, and against one username from many sources; assert lockout and per-source throttling behave per E43-T04, that legitimate logins for unaffected accounts still succeed, and that the auth path does not degrade the rest of the API.
  2. **Mutation flood** - authenticated bursts at order-path and admin-mutation endpoints; assert per-session limits engage, that read paths remain serviceable, and that no request is silently dropped without an error.
  3. **Per-UID budget exhaustion** - drive one UID's private-REST budget toward exhaustion and assert (a) two credentials on the same UID share one tracker object (SR-044a), (b) the SR-071 reserve is preserved so a reduce-only/cancel action still succeeds, and (c) the fan-out planner refuses or staggers a group that would breach a participating UID's reserve (SR-044b).
  4. **Global per-IP ceiling** - drive aggregate egress toward the 600 req/5 s ceiling and assert the global token bucket self-throttles from the `X-Bapi-Limit*` response headers **before** error 10006 rather than after (SR-044c).
  5. **WS flood and slow consumer** - a client that subscribes broadly and then stops reading; assert backpressure policy (`docs/plan/20-architecture.md` section 4.2) drops or conflates as designed and that one slow consumer cannot degrade others; assert WS connection-attempt limits (SR-044e).
- **Reporting**: p50/p95/p99 latency, error-code distribution, and an explicit pass/fail against the budgets in `docs/plan/06-performance-and-load-standard.md` for each profile.
- Findings routed as defects; any breach of the SR-071 reserve is a P0.

## Out of scope
- Chaos/fault injection (E45); the exchange's own limits (no load is generated against Bybit - all exchange interaction is against fixtures or the demo environment within its documented limits).
- Building the rate limiters (E34 governor, E43-T04 auth limits).

## Acceptance criteria
```gherkin
Scenario: Risk-reducing actions survive budget pressure
  Given a UID driven to the edge of its private REST budget
  When a reduce-only or cancel action is issued
  Then it succeeds within its latency budget because the SR-071 reserve was preserved

Scenario: Two credentials on one UID share one tracker
  Given two distinct credentials resolving to the same Bybit UID
  When load is applied through both
  Then the observed aggregate throughput matches a single shared budget, not two independent budgets

Scenario: Self-throttling precedes the error
  Given aggregate egress approaching the per-IP ceiling
  Then the global bucket throttles based on the X-Bapi-Limit response headers
  And no 403 access-too-frequent lockout is triggered during the profile

Scenario: A slow consumer is contained
  Given one WS client that subscribes broadly and stops reading
  Then the documented backpressure policy applies to that connection only
  And other clients' latency stays within budget

Scenario: Auth flood does not deny service to others
  Given a sustained failed-login flood across many usernames
  Then unaffected accounts continue to authenticate within their latency budget
  And the flood's source is throttled with exponential backoff
```

## Technical notes / design
- Profiles run against staging with fixture-backed exchange interaction for the UID-budget scenarios, so no real Bybit limit is consumed; the header-driven self-throttle is exercised by a fixture that returns realistic `X-Bapi-Limit`, `X-Bapi-Limit-Status` and `X-Bapi-Limit-Reset-Timestamp` values.
- The shared-tracker assertion is both a load observation and a design/contract test (SR-044a explicitly requires "a design/contract test MUST assert that two distinct credentials resolving to the same UID share one tracker object") - the contract test lives with E34; this ticket asserts the behaviour under load.
- Scheduling: must not run concurrently with E43-T08's ZAP scan, so both results remain interpretable.
- Known ceilings to encode as configuration are listed in SR-044b (order/create 10/s, cancel-all **1/s**, etc.); the profiles use those numbers rather than inventing them.

## Test plan
The profiles are the tests. Each run publishes a report with the pass/fail table; a baseline run is recorded pre-freeze and re-run after remediation (E43-X07) to prove no regression.

## Security notes
Threats: rate-limit DoS as a means of preventing position exit (the trading-specific availability threat), rule-engine resource exhaustion (SR-104 lineage), and WS flooding. The `cancel-all` 1/s ceiling is a hard constraint on the kill switch and is asserted here as well as in E39's own tests. Load is never directed at Bybit. Security review required.

## Accessibility notes
N/A - no UI surface. (Degraded-state UI copy under throttling is verified in E43-Q05.)

## Performance notes
Budgets come from `docs/plan/06-performance-and-load-standard.md`; this ticket does not invent thresholds. Results are recorded as the R4 baseline for these profiles.

## Observability
Asserts that `cv_auth_ratelimit_hits_total`, the per-UID budget gauges and the WS backpressure metrics move as expected - missing telemetry under load is itself a finding, because the Owner's alerting depends on it.

## Definition of Done
- [ ] All five profiles implemented under `infra/k6/` and runnable by a single command.
- [ ] Pass/fail table recorded against the section 06 budgets; failures filed as defects with severities.
- [ ] SR-071 reserve verified under pressure; any breach raised as P0.
- [ ] Results attached to the evidence pack input for E43-X07.
- [ ] QA sign-off and Security engineer review.
- [ ] PR merged via the merge queue.

## Dependencies
- **E43-T04** (auth limits) and **E34** (per-UID governor, fan-out planner) supply the mechanisms under test.

## Branch
`test/e43-loadprofiles-ratelimit`. PR size guidance: one PR per profile group (auth, mutation/UID, WS).

## References
- `docs/plan/04-security-program.md` SR-044, SR-044a..SR-044e, SR-071, sections 13.2 item 6, 12.1.
- `docs/plan/06-performance-and-load-standard.md`; `docs/plan/20-architecture.md` sections 4.2, 4.3.
- `docs/plan/23-ws-protocol.md` (backpressure, subscription limits).""")

t(key="E43-Q05", kind="Task",
  title="Accessibility audit of the security centre, key health and audit detail screens",
  labels=["type/test","area/auth-rbac","priority/p1","qa","a11y"],
  component="web", sprint="Sprint 21", priority="P1 High", perspective="QA",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-S01","E43-S02","E43-D03"],
  body="""## Context
`docs/plan/02-definition-of-ready-done.md` section 8 is explicit: a11y is default-on for any ticket that ships or changes a UI surface, *"including owner/admin screens - there is no 'internal tool, a11y doesn't matter' exception, since owner/admin screens are inside the same web app and RBAC-gated, not absent of users with accessibility needs."* E43 ships SCR-137 and changes SCR-128 and SCR-136, and those screens carry an unusual accessibility burden: their entire content is **status information conveyed under time pressure**, where a colour-only severity cue or an unlabelled disabled control is not a cosmetic defect but an information failure on a safety screen.

The manual screen-reader scripts and the keyboard walkthroughs were authored in E43-D03; this ticket executes them against the built screens, plus the automated axe-core pass.

## Scope / Deliverables
- **Automated**: axe-core run (the `a11y-axe` required check, `docs/plan/04-security-program.md` section 12.1) across SCR-137, SCR-128, SCR-136 in every state produced by E43-Q01's data-setup recipes - including the failing, stale and `unverifiable` states, which are frequently missed because they are hard to reach.
- **Manual screen-reader passes** with NVDA and VoiceOver using the E43-D03 scripts: verdict badges announce the verdict word; the disabled Live-enablement control announces *why* (its `aria-describedby` target); the integrity-break banner is announced without stealing focus; the re-scan progress is announced; the enable dialog is labelled, traps focus and restores it.
- **Keyboard-only walkthroughs**: complete every journey - read posture, dismiss a finding with a reason, attest an item, enable Live with step-up and typed confirmation, re-disable, mark a key compromised - without a pointer, verifying focus order, visible focus and no keyboard traps.
- **Contrast verification** against the shipped build (not the design file) for every verdict/severity style in both themes, and a greyscale review confirming no information is colour-only.
- **Reduced-motion** verification: no verdict change animates when `prefers-reduced-motion` is set.
- **Degraded-state copy check**: throttled/rate-limited and re-auth-required states are announced and readable, not silent.
- Findings filed as Bugs with priority labels and linked to E43-D03 (design QA) or to the implementing story as appropriate; a written audit report against `docs/plan/05-accessibility-standard.md`.

## Out of scope
- Non-E43 screens; fixing the defects (routed to the owning story); the design-stage review (E43-D03).

## Acceptance criteria
```gherkin
Scenario: axe-core is green in every state
  Given each documented state of SCR-137, SCR-128 and SCR-136 including failing, stale and unverifiable states
  When the axe-core check runs
  Then there are zero violations at serious or critical impact
  And any moderate finding has a recorded disposition

Scenario: The disabled gate control explains itself to a screen reader
  Given the Live enablement control is disabled because items are outstanding
  When a screen-reader user focuses it
  Then the outstanding-items reason is announced with the control

Scenario: Every journey is completable without a pointer
  Given keyboard-only operation
  When each of the six journeys is executed
  Then each completes, focus order is logical, focus is always visible, and no keyboard trap occurs

Scenario: No information is colour-only
  Given a greyscale rendering of every verdict and severity state
  Then the verdict and severity remain readable as text

Scenario: Reduced motion is honoured
  Given prefers-reduced-motion is set
  When verdicts change and the re-scan runs
  Then no animation plays and status is still conveyed
```

## Technical notes / design
- axe-core runs inside the Playwright suite so the hard-to-reach states can be seeded programmatically rather than clicked into.
- Screen-reader passes are recorded (audio or transcript) and attached, so a disputed finding can be re-heard rather than re-argued.
- Contrast is measured from the rendered build's computed styles, catching the case where a token was overridden locally.

## Test plan
The audit is the test; its output is the report plus filed Bugs. Any fix is re-verified by re-running the specific automated check and the affected manual step.

## Security notes
Accessible names must not disclose information the design withholds - for example, a denied resource's accessible name must not reveal that the resource exists (see E43-T09's no-existence-oracle rule). The audit explicitly checks this on the admin screens as a joint a11y/security assertion.

## Accessibility notes
This ticket *is* the accessibility work: WCAG 2.2 AA per `docs/plan/05-accessibility-standard.md`, covering perceivable (contrast, text alternatives), operable (keyboard, focus, no traps, target size), understandable (consistent identification, error identification and suggestion) and robust (name/role/value) across all three screens.

## Performance notes
The axe-core run adds to the E2E suite duration; keep within the pipeline budget by seeding states directly rather than navigating through them.

## Observability
N/A, except that the audit verifies the re-scan progress state is driven by real status rather than an optimistic spinner.

## Definition of Done
- [ ] axe-core green (zero serious/critical) across all states; moderates dispositioned.
- [ ] NVDA and VoiceOver passes executed with recordings attached.
- [ ] Keyboard-only walkthroughs completed for all six journeys.
- [ ] Contrast table for the shipped build recorded; greyscale review passed.
- [ ] Reduced-motion verified.
- [ ] Defects filed with priorities and linked; blockers fixed before R4 sign-off.
- [ ] Report reviewed by the accessibility specialist and the QA lead.

## Dependencies
- **E43-S01**, **E43-S02** supply the built screens; **E43-D03** supplies the scripts and the expected behaviours.

## Branch
`test/e43-a11y-audit`. PR size guidance: automation additions small; the report is an artefact.

## References
- `docs/plan/05-accessibility-standard.md`; `docs/plan/02-definition-of-ready-done.md` section 8.
- `docs/plan/14-screens-catalogue.md` SCR-137, SCR-128, SCR-136 (a11y notes).
- `docs/plan/04-security-program.md` section 12.1 (axe-core gate).""")

t(key="E43-Q06", kind="Task",
  title="Execute the R4 security regression pack and record QA sign-off",
  labels=["type/test","area/auth-rbac","priority/p0","qa","security"],
  component="api", sprint="Sprint 22", priority="P0 Critical", perspective="QA",
  risk="None", estimate=3, parent="E43",
  blocked_by=["E43-Q01","E43-Q03","E43-Q04","E43-Q05","E43-T11"],
  body="""## Context
`docs/plan/02-definition-of-ready-done.md` section 2.2 requires an **epic-level** regression/exploratory pass, not merely per-child QA, and section 8 forbids a silent skip of QA sign-off. R4's gate additionally requires QA-lead sign-off at the PRR (`docs/plan/30-release-roadmap.md` section 8.4).

This ticket is the final QA act of the epic: run everything against the **retest tag** (post-remediation), confirm nothing regressed while findings were being fixed, and produce the signed record that the PRR consumes.

## Scope / Deliverables
- Assemble the **R4 security regression pack**: E43-Q01's black-box plan, E43-Q03's SR-152 negative suite, E43-T11's finding-specific regression pack, E43-Q04's load profiles (re-run for comparison against the pre-freeze baseline), E43-Q05's a11y checks, plus a smoke pass over adjacent functionality most likely to have been disturbed by hardening: login and TOTP, session behaviour across a restart, order placement on demo with brackets and native SL, fan-out to two sub-accounts, kill-switch activation and release, audit search and export, and chart rendering (the CSP/Electron changes are the plausible regression source here).
- Execute the pack against the retest tag; record pass/fail per scenario with evidence.
- **Comparison report**: pre-freeze baseline vs post-remediation results for latency, load profiles and scan alert counts, so "we fixed things without breaking others" is evidenced rather than asserted.
- **Defect triage**: anything found is triaged with the Security engineer; Critical/High block R4, Medium/Low are dispositioned per the exception process.
- **QA sign-off record**: a structured sign-off naming the QA lead, the tag tested, the environment, the pack version, the pass/fail summary, open defects with dispositions, and any capacity deviations recorded explicitly.

## Out of scope
- The pen-test and its retest (E43-X02, E43-X07 - this pack is an input to the latter).
- Chaos/failover regression (E45 owns its own pack).

## Acceptance criteria
```gherkin
Scenario: The pack runs against the retest tag
  Given the post-remediation retest tag
  When the full R4 security regression pack is executed
  Then every scenario has a recorded pass or fail with evidence
  And the tag hash is recorded in the sign-off

Scenario: No regression from remediation
  Given the pre-freeze baseline results
  When the post-remediation results are compared
  Then no previously passing scenario fails
  And latency and load metrics are within the agreed tolerance of the baseline

Scenario: Adjacent functionality still works
  Given the hardening changes to CSP, the Electron shell, sessions and rate limits
  When the adjacent smoke pass runs
  Then login, order placement with native SL, fan-out, kill switch, audit search and chart rendering all behave correctly

Scenario: Sign-off is complete and honest
  Given the completed execution
  Then the sign-off record names the QA lead, tag, environment, pass/fail summary, open defects with dispositions and any capacity deviation
  And no scenario is marked passed without evidence
```

## Technical notes / design
- Execution runs on staging in prod-shape configuration; no live credentials are used (SR-140/SR-144). The kill-switch element of the smoke pass is the staging drill; the prod-shape re-pass is a separate R4 exit item (`30-release-roadmap.md` section 8.3 item 3) coordinated with E44/E45.
- Tolerance for latency comparison is agreed with the Architect before execution so the comparison cannot be argued after the fact.
- Evidence: logs, screenshots, report artefacts and audit-log extracts attached per scenario.

## Test plan
This ticket executes tests rather than defining new ones; its own quality gate is completeness - every scenario in the constituent packs appears in the execution record exactly once.

## Security notes
The sign-off is a PRR input and a non-repudiation artefact: it must state what was *not* tested as clearly as what was. Any deviation (QA capacity, environment limitation, scenario deferred) is recorded explicitly per `docs/plan/02-definition-of-ready-done.md` section 8. Findings remain confidential until fixed.

## Accessibility notes
The a11y portion re-runs E43-Q05's automated checks on the retest tag; a full manual re-pass is required only for screens changed during remediation, and that decision is recorded.

## Performance notes
Load profiles are re-run and compared against the pre-freeze baseline; any regression beyond the agreed tolerance is a defect, not a footnote.

## Observability
The execution verifies that the metrics and audit events named across the epic's tickets are present on the retest tag - telemetry that disappeared during remediation is a defect.

## Definition of Done
- [ ] Full pack executed against the retest tag with evidence per scenario.
- [ ] Comparison report (baseline vs post-remediation) produced and reviewed.
- [ ] All defects triaged with the Security engineer; no open Critical/High.
- [ ] QA sign-off record posted, naming tag, environment, results and deviations.
- [ ] Sign-off handed to the PRR and referenced by E43-X07's evidence pack.

## Dependencies
- **E43-Q01**, **E43-Q03**, **E43-Q04**, **E43-Q05**, **E43-T11** supply the pack's constituents.
- Feeds **E43-X07** and the R4 PRR.

## Branch
`test/e43-r4-regression-pack` (execution records and any pack glue).

## References
- `docs/plan/02-definition-of-ready-done.md` sections 2.2, 3.2, 8.
- `docs/plan/30-release-roadmap.md` sections 8.3, 8.4.
- `docs/plan/03-testing-strategy.md`; `docs/plan/07-release-and-prr.md`.""")

json.dump(T, io.open(os.path.join(os.path.dirname(__file__), "_e43_part6.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("part6", len(T))
