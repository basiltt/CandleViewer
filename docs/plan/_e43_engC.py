# -*- coding: utf-8 -*-
"""E43 engineering part C: S01, S02, T11, T12."""
import json, io, os

T = []
def t(**k):
    k.setdefault("phase", "P4 Backtesting & Scripting")
    k.setdefault("milestone", "R4 Live enablement")
    T.append({kk: k[kk] for kk in ["key","kind","title","labels","component","phase","sprint",
        "priority","perspective","risk","estimate","parent","blocked_by","milestone","body"]})

DOD_UI = """## Definition of Done
- [ ] All Gherkin acceptance criteria pass, each referenced by an automated test or an executed QA step.
- [ ] Coverage: >= 80% frontend, >= 90% on M18/M19 backend paths touched.
- [ ] Docs: `docs/plan/22-api-openapi.yaml`, `docs/plan/14-screens-catalogue.md` and `docs/plan/04-security-program.md` updated to shipped behaviour.
- [ ] a11y: axe-core CI green on the touched screens; manual screen-reader spot-check; keyboard-only path verified; focus order and visible focus checked against `docs/plan/05-accessibility-standard.md`.
- [ ] design-qa: built screen compared against the E43-D01/D02 spec by a designer; discrepancies fixed or filed as Bugs with priority labels.
- [ ] security: SAST/SCA/secrets clean or triaged; Security engineer review comment; manual abuse-case check performed (attempt to enable the gate while an item is outstanding; attempt privilege escalation on the endpoint).
- [ ] QA sign-off: black-box test plan executed with pass/fail per scenario.
- [ ] Demoed at Sprint Review with the Owner present.
- [ ] Feature-flag state recorded.
- [ ] PR(s) merged via the merge queue with 2 approvals incl. a code-owner.
"""

t(key="E43-S01", kind="Story",
  title="Enforce and surface the Live-trading enablement gate on the security centre",
  labels=["type/feature","area/auth-rbac","priority/p0","security","a11y","qa","design-qa"],
  component="web", sprint="Sprint 20", priority="P0 Critical", perspective="Development",
  risk="None", estimate=8, parent="E43",
  blocked_by=["E43-D01","E43-S02","E42","E09"],
  body="""## Context
**US-ADMIN-012 Live-trading enablement gate (Must)**, `docs/plan/11-user-stories.md` section 26:

> As the **owner**, I want Live trading to be disabled until readiness criteria are met, so that we cannot go live prematurely.

Its NFR is the design constraint: *"criteria are machine-checked where possible and explicitly attested where not, with the attester and date recorded."* The gate is not a checkbox the Owner ticks - it is a computed verdict over the four Live-enablement gate items in `docs/plan/07-release-and-prr.md` section 6 (pen-test, key-permission audit, kill-switch test, written Owner sign-off), plus the machine-checkable posture signals produced by E43-S02.

This is the control that makes the whole R4 train meaningful: `docs/plan/30-release-roadmap.md` section 8.3 exit criterion 10 requires the Owner to sign off in writing having reviewed the pen-test summary and the key audit, and section 8.1 goal 2 requires the live/demo boundary to be structural. E43 owns the **criteria evaluation, the blocking and the evidence**; E44 owns the **environment separation mechanics** the flag then controls.

Screens: SCR-137 Admin: security centre (primary), with gate-blocked states on SCR-010 App shell and SCR-074 Environment switcher.

## Scope / Deliverables
- **Gate evaluation service** (backend, M18/M21 boundary): computes gate status from (a) machine-checked signals - pen-test finding counts by severity from the findings register, key-permission verification verdicts, kill-switch drill record, audit-chain verification status, posture checks from E43-S02 - and (b) attested items, each carrying attester identity, date and a free-text evidence reference. Returns per-item status plus an overall verdict.
- **Enforcement**: the live-trading feature flag (`feature_flags` / `feature_flag_overrides`) **cannot be set to enabled** while any gate item is outstanding - enforced server-side on the flag-mutation endpoint, not in the UI. Attempting it returns a distinguishable error listing the outstanding items and is audited.
- **Enablement flow**: step-up re-authentication (SR-025) plus typed confirmation; the enablement is audited at **high severity** (`flag.changed`, per SCR-148/SCR-137 audit notes).
- **Emergency re-disable**: disabling Live stops acceptance of new live orders while existing positions remain manageable in **reduce-only** mode; the transition is audited and takes effect within the flag-push bound (US-ADMIN-007 NFR: within 10 seconds, server-side with client push).
- **UI on SCR-137**: the gate block per the E43-D01 spec - each item as a row with status, evidence, attester/date where attested, last-evaluated timestamp where machine-checked; the disabled enable-control with its reason programmatically associated; the enable dialog (CMP-043 Dialog, CMP-093 AuditActionTrigger); the re-disable path.
- **Host-surface states**: SCR-010 app-shell environment badge and SCR-074 environment switcher render Live as present-but-unselectable with the reason inline while the gate is closed.
- **Attestation recording**: an owner-only endpoint to record an attestation for a non-machine-checkable item, capturing attester, date and evidence reference; each attestation is audited and can be withdrawn (also audited).
- API surface: extend `GET /api/v1/admin/security/summary` (`SecuritySummary`) with the gate block, and use `GET|PATCH /api/v1/admin/feature-flags/{flagKey}` for the flag mutation; document both in `docs/plan/22-api-openapi.yaml` with `x-rbac`.

## Out of scope
- Environment separation, separate credential sets, separate Postgres schemas/QuestDB namespaces and the startup self-check that refuses live credentials failing the withdrawal-OFF/IP-whitelist assertion - **E44**.
- The kill switch itself (E39) and the key-permission audit tooling (E44); this story consumes their results.
- Producing the pen-test itself (E43-X02) or the posture checks (E43-S02).

## Acceptance criteria
```gherkin
Scenario: Gate closed
  Given the pen-test sign-off or any PRR checklist item is outstanding
  When the Owner opens SCR-137
  Then the Live enablement control is disabled and lists exactly which items are outstanding
  And each outstanding item names what is missing and the action that resolves it

Scenario: Gate opened
  Given all criteria are met
  When the Owner enables Live with step-up authentication and typed confirmation
  Then Live becomes selectable in the environment switcher
  And the enablement is audited as high severity with actor, timestamp and the gate snapshot that justified it

Scenario: Emergency re-disable
  Given Live is enabled
  When the Owner disables Live again
  Then no new live orders are accepted from any path
  And existing positions remain manageable in reduce-only mode
  And the transition is audited and pushed to all clients within ten seconds

Scenario: The gate cannot be bypassed through the API
  Given at least one gate item is outstanding
  When a request is made directly to the feature-flag endpoint to enable live trading, with a valid Owner session and a valid step-up token
  Then the request is refused with an error listing the outstanding items
  And the refusal is audited

Scenario: A manager cannot see or operate the gate
  Given a Manager session
  When the gate endpoints are requested
  Then the requests are denied identically to a non-existent resource
  And the denial is audited

Scenario: Attested items carry accountability
  Given an item that cannot be machine-checked
  When it is attested
  Then the attester identity, the date and the evidence reference are recorded and displayed
  And withdrawing the attestation immediately reopens the gate and is audited

Scenario: Stale evidence reopens the gate
  Given a machine-checked signal whose last evaluation is older than its configured freshness window
  Then the item is treated as outstanding rather than as passing
```

## Technical notes / design
- Gate items are configuration-driven (`security.gate.items`), each declaring `kind: machine|attested`, the evaluating signal or the attestation slot, and a freshness window. The four `07-release-and-prr.md` section 6 items are the seed set; adding an item is a config + doc change, not a code change.
- The overall verdict is the conjunction of item verdicts; a `stale` or `unknown` item is treated as failing (fail-closed) - this is an explicit design rule, since the alternative silently opens the gate when a check stops running.
- Flag mutation is a single server-side chokepoint: the gate check runs inside the same transaction as the flag write, so a concurrent change of evidence cannot be raced.
- Reduce-only enforcement on re-disable is delegated to the OMS (M14) via an existing mode signal; this story asserts the signal is emitted and honoured, not the OMS implementation.
- Flag push to clients uses the existing WS flag topic (`docs/plan/23-ws-protocol.md`); the 10 s bound is asserted in the E2E test.
- Error codes: `E_GATE_BLOCKED` (with an `outstanding` array), `E_STEPUP_REQUIRED`, `E_FORBIDDEN`.
- Data model: attestations stored with `{item_key, attester_user_id, attested_at, evidence_ref, withdrawn_at}`; the flag itself in `feature_flags` with per-environment overrides in `feature_flag_overrides`.

## Test plan
- **Unit**: verdict computation across item states (pass/fail/stale/unknown); fail-closed rule; freshness windows; config-driven item set.
- **Contract**: `SecuritySummary` gate block and the flag endpoint against `docs/plan/22-api-openapi.yaml`, including `x-rbac` declarations.
- **Integration**: enable attempt with an outstanding item (refused + audited); enable with all items met (succeeds + audited high severity); attestation record/withdraw; concurrent enable vs evidence-change race.
- **E2E (Playwright web + Electron)**: the full Owner journey - blocked -> attest -> enable with step-up + typed confirmation -> switcher shows Live -> re-disable -> new live orders refused while reduce-only remains available; flag push observed within 10 s; Manager denied.
- **a11y**: axe-core on SCR-137; keyboard-only path through the enable dialog; screen-reader announcement of the disabled control's reason.
- Coverage target: >= 90% on the gate service, >= 80% frontend.

## Security notes
Threats (`docs/plan/04-security-program.md` section 5.7 admin screens, section 14.6 admin-screen ticket template): elevation of privilege (a Manager enabling live), tampering (forging an attestation), and the subtler failure of **false assurance** - a gate that passes because a check stopped running. Controls: owner-only capability, step-up (SR-025), typed confirmation, transactional gate-check-and-write, fail-closed on stale/unknown, high-severity audit on every transition, and audited attestation withdrawal. Data classification: this control gates access to real money; treat as the highest-severity surface in the epic alongside E43-T09. Security review mandatory; abuse cases in E43-X04.

## Accessibility notes
Per `docs/plan/05-accessibility-standard.md` and the E43-D03 handoff: the disabled enable-control carries `aria-describedby` pointing at the outstanding-items list, so a screen-reader user learns *why* rather than only *that* it is disabled; the enable dialog traps focus, is labelled, and restores focus on close; typed confirmation has a visible, programmatically associated label; item status is text, never colour alone; the re-disable confirmation states the reduce-only consequence in plain language.

## Performance notes
Gate evaluation is served from the cached security summary (computed server-side on a schedule, <= 1% added load per SCR-137) with a forced re-evaluation on the enablement path so the decision is never made on stale data. Flag push to clients within 10 s (US-ADMIN-007 NFR). Budgets per `docs/plan/06-performance-and-load-standard.md`.

## Observability
Metrics `cv_live_gate_status{item,state}`, `cv_live_gate_blocked_attempts_total`, `cv_feature_flag_push_latency_seconds`. Audit events `flag.changed` (high severity, with the gate snapshot), `security.gate_attested`, `security.gate_attestation_withdrawn`, `security.gate_enable_refused`. Alert on any blocked-attempt burst and on any live-enable transition.

""" + DOD_UI + """
## Dependencies
- **E43-D01** design signed off (design-ahead rule).
- **E43-S02** supplies the machine-checked posture signals the gate consumes.
- **E42** admin screens/routing; **E09** auth, step-up and RBAC.
- Blocks **E44** (the environment separation work is gated by this control) and **E43-X07**.

## Branch
`feat/e43-live-enablement-gate`. PR size guidance: (1) gate service + config + tests, (2) flag enforcement + attestation endpoints, (3) SCR-137 UI + host-surface states.

## References
- `docs/plan/11-user-stories.md` US-ADMIN-012, US-ADMIN-007, US-ADMIN-010.
- `docs/plan/07-release-and-prr.md` section 6 Live-enablement gate.
- `docs/plan/30-release-roadmap.md` section 8.1, 8.3, 8.4.
- `docs/plan/14-screens-catalogue.md` SCR-137, SCR-010, SCR-074, SCR-148.
- `docs/plan/18-traceability-matrix.md` row US-ADMIN-012.
- `docs/plan/22-api-openapi.yaml` `/admin/security/summary`, `/admin/feature-flags/{flagKey}`; `docs/plan/23-ws-protocol.md` flag topic.
- `docs/plan/21-database-schema.md` `feature_flags`, `feature_flag_overrides`, `audit_log`.
- `docs/plan/04-security-program.md` SR-025, sections 5.7, 14.6.""")

t(key="E43-S02", kind="Story",
  title="Machine-evaluated security posture checks and the security centre panel",
  labels=["type/feature","area/auth-rbac","priority/p0","security","a11y","qa","design-qa"],
  component="api", sprint="Sprint 20", priority="P0 Critical", perspective="Development",
  risk="None", estimate=8, parent="E43",
  blocked_by=["E43-D02","E43-T04","E43-T10","E27","E42"],
  body="""## Context
**US-ADMIN-010 Security posture panel (Must)**, `docs/plan/11-user-stories.md` section 26:

> As the **owner**, I want a single security status view, so that I can see whether the installation is safe.

with the decisive NFR: *"every check is machine-evaluated, not a manual checklist; results exported as metrics."* The story's scenarios require the panel to show key self-check results, withdrawal-permission status, IP whitelist status, Tailscale-only binding check, KEK availability, 2FA coverage and key ages with pass/fail and timestamps; to escalate any failing control with the **exact remediation step** and raise an alert; and to list Bybit-side hardening advisories (withdrawal address whitelist, anti-phishing code, device review) with an acknowledgement state and the date acknowledged.

The endpoint already exists in the contract: `GET /api/v1/admin/security/summary` returning `SecuritySummary` - "key ages and expiry, IP-whitelist drift, withdrawal-permission verification results, failed-login and denied-request counts, MFA enrolment coverage, and the last audit-chain verification. Owner-only; never includes secret material." This story implements the checks behind it and the SCR-137/SCR-128 surfaces that render them.

It is a prerequisite for E43-S01: the gate consumes these verdicts.

## Scope / Deliverables
- **Check engine**: a scheduled evaluator producing a typed verdict per check - `pass` / `fail` / `stale` / `unverifiable` - each with a value, a timestamp, a source, and a remediation string. Checks to implement:
  1. **Key withdrawal permission** - per key, from the exchange's own reported scopes (`GET /v5/user/query-api` via the backend adapter), never from app belief; `unverifiable` if the call failed.
  2. **IP whitelist present and current** - including **drift** when the deployment's egress IP is absent (OQ-05, `docs/plan/04-security-program.md` section 16.1a).
  3. **Key age vs rotation policy** (90-day schedule, SR-030 family) with an overdue state.
  4. **KEK availability** - the envelope-encryption key is reachable and the last re-wrap timestamp is known (M2).
  5. **Tailscale-only binding check** - the SR-047 listening-socket self-check result.
  6. **2FA coverage** - proportion of users with TOTP enrolled, and specifically every trading-capable user (SR-020).
  7. **Failed-login and denied-request counts** with spike detection, fed by E43-T04 and E43-T09.
  8. **Last audit-chain verification** status and timestamp, fed by E43-T10.
  9. **Stale sessions** - sessions beyond their expected lifetime.
  10. **Dependency/vulnerability summary** from the last scan (E43-T05) and the open-exception count with nearest expiry.
- **Bybit-side advisories**: a static list (withdrawal address whitelist, anti-phishing code, device review) each with an acknowledgement state, acknowledger and date; acknowledging is audited.
- **Metrics export** (NFR): every verdict exported as a Prometheus gauge so the posture is alertable, not merely viewable.
- **Alerting**: any failing control raises an alert (US-ADMIN-010 scenario 2) with the remediation string in the annotation.
- **API**: implement `GET /api/v1/admin/security/summary` fully against the `SecuritySummary` schema, owner-only (`x-rbac: audit:read`), with a **manual re-scan action** that is explicit and shows progress (SCR-137 performance note) - never an automatic refresh.
- **UI**: SCR-137 posture sections and SCR-128 key-health panel rows per the E43-D02 spec, including the `unverifiable` and `drift` states and the `mark as compromised` emergency action; `security.finding_dismissed {findingId, reason}` audited.

## Out of scope
- The Live-enablement gate block (E43-S01, which consumes these verdicts).
- Key rotation flows (E27); the kill switch (E39); the Tailscale scan itself (E43-K01 supplies the evidence, this story surfaces the self-check result).
- Fixing whatever the checks find - each failure produces a remediation action, executed elsewhere.

## Acceptance criteria
```gherkin
Scenario: Posture summary
  Given the Owner opens SCR-137
  Then key self-check results, withdrawal-permission status, IP whitelist status, Tailscale-only binding check, KEK availability, 2FA coverage and key ages are shown with pass or fail and a timestamp for each

Scenario: Failing control escalates with a remediation step
  Given any control fails
  Then the panel escalates it with the exact remediation step in text
  And an alert is raised carrying the same remediation string

Scenario: Advisory items carry acknowledgement state
  Given the Bybit-side hardening advisories
  Then each is listed with an acknowledgement state and, where acknowledged, the acknowledger and the date

Scenario: Exchange truth beats app belief
  Given a key whose stored configuration claims withdrawal is disabled but whose exchange-reported scopes include withdrawal
  Then the check reports fail, naming the exchange-reported scope as the source
  And the finding is alerted at high severity

Scenario: A check that cannot run is not a pass
  Given the exchange verification call fails or has not run within its freshness window
  Then the check reports unverifiable or stale, never pass
  And the Live-enablement gate treats it as outstanding

Scenario: No secret material is ever returned
  Given any response from the security summary endpoint in any check state
  Then no API key, secret, session token, TOTP seed or KEK material appears in the payload

Scenario: Only the Owner can read the posture
  Given a Manager or Viewer session
  When the security summary endpoint is requested
  Then the request is denied identically to a non-existent resource

Scenario: Verdicts are exported as metrics
  Given the check engine has run
  Then every check verdict is present as a gauge on the metrics endpoint with labels identifying the check and the subject
```

## Technical notes / design
- Each check implements a common interface `evaluate() -> Verdict{state, value, source, evaluated_at, remediation}`; the registry is explicit so adding a check is a registration, and the panel renders whatever is registered (no hard-coded UI list).
- Scheduling: checks run on independent intervals appropriate to their cost (exchange-backed checks are rate-limit aware - `GET /v5/user/query-api` is 10 req/s per UID and shares the per-UID budget per SR-044a, so the check acquires from the same tracker and never bursts across accounts). Results are cached for 60 s for the panel (SCR-128 performance note).
- `unverifiable` is a first-class state and must never be collapsed into `pass` - this is the single most important implementation rule in the story.
- Egress IP detection for drift runs hourly with alerting (SR-033 lineage; OQ-05 interim control).
- All exchange contact happens in the backend (SR-119) - the panel never calls Bybit from the browser.
- Error codes: `E_CHECK_UNAVAILABLE`, `E_FORBIDDEN`.
- Config keys: `security.checks.<name>.interval_seconds`, `security.checks.<name>.freshness_seconds`, `security.advisories.enabled`.

## Test plan
- **Unit**: each check's verdict logic incl. failure and stale paths; freshness computation; metric label construction; remediation string presence for every failing verdict (a test asserts no failing verdict has an empty remediation).
- **Contract**: `SecuritySummary` response against `docs/plan/22-api-openapi.yaml`; a test asserting the serialised payload contains no field matching secret patterns (reuses the E43-T06 redaction corpus).
- **Integration**: exchange-verification check against a recorded Bybit fixture for withdrawal-enabled, withdrawal-disabled and error responses; IP-drift simulation; KEK unavailable; audit-chain failure surfaced; rate-limit tracker sharing asserted for two credentials on the same UID.
- **E2E**: Owner views SCR-137 and SCR-128 in compliant, findings-outstanding and check-failed states; manual re-scan shows progress; dismiss-with-reason is audited; Manager denied.
- **a11y**: axe-core on SCR-137/SCR-128; screen-reader reading of verdict badges includes the verdict word; greyscale check.
- Coverage target: >= 90% on the check engine, >= 80% frontend.

## Security notes
Threats (`docs/plan/04-security-program.md` sections 5.1, 5.7): false assurance (a panel that says "safe" when a check never ran), information disclosure through a diagnostic surface, and an oracle that helps an attacker locate the weakest key. Controls: `unverifiable`/`stale` as failing states, owner-only capability, contract test asserting no secret material, audited dismissal with a reason, and exchange-reported scopes as the authority for permission claims. Data classification: metadata about secrets and about users' 2FA status - sensitive, never secret material itself. Security review mandatory.

## Accessibility notes
Per E43-D02/D03: each check is a row with the verdict as text; warnings are text with an icon; the key table exposes age, permissions, allowlist state and rotation-due date as real table semantics; the `mark as compromised` action is a named button with a confirmation stating its immediate effect; the re-scan progress is announced via `role="status"`; contrast verified for all verdict styles.

## Performance notes
Panel adds <= 1% load (SCR-137) and is served from a 60 s server-side cache (SCR-128); exchange-backed checks must not consume rate-limit budget needed by the order path - they acquire from the per-UID tracker and respect the SR-071 reserve. Budgets per `docs/plan/06-performance-and-load-standard.md`.

## Observability
Metrics `cv_security_check{check,subject,state}`, `cv_security_checks_stale_total`, `cv_key_age_days{key_id}`, `cv_2fa_coverage_ratio`, `cv_security_findings_open{severity}`. Audit events `security.finding_dismissed`, `security.advisory_acknowledged`, `admin.key_marked_compromised`, `admin.secrets_policy_changed`. Analytics `security.centre_viewed`, `security.rescan_requested`, `admin.key_health_viewed`.

""" + DOD_UI + """
## Dependencies
- **E43-D02** design signed off; **E43-T04** (failed-login signals), **E43-T10** (audit-chain verification status), **E27** (key vault, key metadata, exchange verification call), **E42** (admin chrome and routing).
- Blocks **E43-S01** (the gate consumes these verdicts).

## Branch
`feat/e43-security-posture-checks`. PR size guidance: (1) check engine + registry + metrics, (2) exchange-backed checks + advisories, (3) SCR-137/SCR-128 UI.

## References
- `docs/plan/11-user-stories.md` US-ADMIN-010, US-ACCT-003, US-ACCT-005, US-ONB-008.
- `docs/plan/14-screens-catalogue.md` SCR-137, SCR-128, SCR-136.
- `docs/plan/18-traceability-matrix.md` rows US-ADMIN-010, SCR-128, SCR-137.
- `docs/plan/22-api-openapi.yaml` `/admin/security/summary` (`SecuritySummary`).
- `docs/plan/04-security-program.md` sections 6.1, 6.2, 6.7, 12, 16.1a (OQ-05), SR-044a, SR-119.
- `docs/plan/20-architecture.md` section 3.11 `KeyVault`, `HealthConsole`.
- ADR-0009 secrets and key management.""")

t(key="E43-T11", kind="Task",
  title="Build the security regression harness for pen-test findings",
  labels=["type/chore","area/auth-rbac","priority/p0","security","qa"],
  component="api", sprint="Sprint 22", priority="P0 Critical", perspective="Security",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-X03"],
  body="""## Context
SR-153 requires that *"security regression tests MUST be added for every confirmed vulnerability (internal finding or pen-test), referencing the finding id"*, and section 13.4 requires that every accepted finding becomes a ticket with a regression test and a retest item. Without a dedicated harness, those tests scatter across the suite, lose their link to the finding, and quietly rot: a year later nobody knows which test is guarding which vulnerability, and deleting it looks harmless.

This ticket builds the harness **after** triage (E43-X03) so it is shaped by real findings rather than guesses, and it becomes the permanent home for security regressions beyond R4.

## Scope / Deliverables
- A dedicated test package (`services/api/tests/security_regressions/` plus a matching Playwright directory for client-side findings) where each test module is named for its finding id and carries a docstring with: finding id, severity, discovery source (pen-test #1 / internal / scan), a one-paragraph description of the vulnerability, and the fix commit.
- A **registry file** mapping finding id -> test id(s) -> ticket -> retest status, and a CI check asserting every finding recorded as "fixed" in the findings register has at least one passing regression test referencing it. A fixed finding without a test fails CI.
- **Pre-fix verification procedure**: each regression test must be demonstrated to fail against the pre-fix commit; the demonstration is recorded in the test docstring (commit hash + observed failure), per `docs/plan/02-definition-of-ready-done.md` section 6.2.
- Shared fixtures for security testing: per-role authenticated clients (Owner/Manager/Viewer), a two-manager/two-sub-account grant topology, a session-manipulation helper, a CSRF-token helper and a WS subscription helper - so a regression test for an authorisation finding is five lines, not fifty.
- Marker/tag so the pack can be run alone (`pytest -m security_regression`) in under a few minutes, making it usable as a pre-release gate.
- Wire the pack into the required checks and into `docs/plan/03-testing-strategy.md`'s SR-150 traceability table.

## Out of scope
- The fixes themselves (funded by the 90-pt reserve as individual remediation tickets filed by E43-X03).
- The broader E2E negative suite (E43-Q03), though it shares the fixtures built here.

## Acceptance criteria
```gherkin
Scenario: Every fixed finding is guarded
  Given the findings register marks a finding as fixed
  When the regression-registry check runs in CI
  Then a passing regression test referencing that finding id exists
  And the check fails if one is missing or is skipped

Scenario: The test actually catches the vulnerability
  Given a regression test for a finding
  When it is run against the pre-fix commit
  Then it fails, and the failure is recorded in the test docstring with the commit hash

Scenario: The pack is fast enough to gate releases
  Given the security regression pack
  When it runs in isolation
  Then it completes within the configured budget and is included in the pre-release gate

Scenario: A deleted test is visible
  Given a regression test is removed or marked skip
  When CI runs
  Then the registry check fails naming the finding left unguarded
```

## Technical notes / design
- Finding ids come from the pen-test report and are reused verbatim; internal findings get ids in the same namespace with an `INT-` prefix so the registry is uniform.
- The registry is a committed data file (YAML/JSON) rather than a docstring scan, so the CI check is deterministic; a second check asserts every registry entry's test id resolves to a real test.
- Fixtures are built on the existing integration test harness (recorded Bybit fixtures, seeded Postgres) so security regressions run against the same environment shape as the rest of the suite.
- Tests must assert the *vulnerability* is absent, not that a particular implementation is present - so a future refactor that preserves the fix keeps passing.

## Test plan
- Meta-tests: registry check against a fixture registry with a missing test (fails), a skipped test (fails) and a complete registry (passes).
- The pack itself: each regression test as filed by E43-X03's remediation tickets.
- Runtime measurement recorded on the ticket.
- Coverage target: the harness code itself >= 85%; the pack's value is measured by registry completeness, not by coverage.

## Security notes
This ticket institutionalises SR-153. Threat it mitigates: silent regression of a fixed vulnerability in a later release - the classic way a pen-test's value expires. Test fixtures must use synthetic credentials with the dummy prefix (SR-145) and must never contain a real finding's exploit payload if that payload embeds a real credential. Security review mandatory.

## Accessibility notes
N/A - test infrastructure.

## Performance notes
Pack runtime budget agreed with DevSecOps and recorded; it runs in the pre-release gate, so it must not extend the pipeline beyond the duration budget in `docs/plan/06-performance-and-load-standard.md`.

## Observability
CI metric `cv_security_regressions_total` and `cv_security_findings_unguarded` (should be zero); the latter is surfaced at PRR.

## Definition of Done
- [ ] Harness, fixtures and registry check merged; pack runnable in isolation.
- [ ] Every finding marked fixed by E43-X03 has a referenced, passing regression test whose pre-fix failure is recorded.
- [ ] `docs/plan/03-testing-strategy.md` SR-150 traceability table updated.
- [ ] Registry check registered as a required status check.
- [ ] Security engineer review comment; QA sign-off.
- [ ] PR merged via the merge queue with 2 approvals incl. a code-owner.

## Dependencies
- **E43-X03** findings triage supplies the finding ids, severities and remediation tickets.
- Feeds **E43-X07** retest and evidence pack.

## Branch
`feat/e43-security-regression-harness`. PR size guidance: (1) fixtures + registry + CI check, (2) the regression tests themselves as they land with each remediation PR.

## References
- `docs/plan/04-security-program.md` SR-150, SR-152, SR-153, sections 13.4, 13.5.
- `docs/plan/03-testing-strategy.md`; `docs/plan/02-definition-of-ready-done.md` section 6.2.""")

t(key="E43-T12", kind="Task",
  title="Record ADR-0016 security-hardening decisions and update security docs",
  labels=["type/docs","area/auth-rbac","priority/p1","security"],
  component="docs", sprint="Sprint 22", priority="P1 High", perspective="Architecture",
  risk="None", estimate=2, parent="E43", blocked_by=["E43-T01","E43-T03","E43-T09","E43-K01"],
  body="""## Context
E43 takes a series of decisions that are not obvious from the code and that a future maintainer (or the next annual pen-test, per section 13.1) will need to understand: the reconciliation of the session-lifetime discrepancy between `docs/plan/20-architecture.md` section 3.10 and SR-024, the lockout-threshold reconciliation (5 vs 10), the style-nonce-versus-scoped-inline CSP decision, the fail-closed rule for stale posture checks, the Tailscale boundary conclusion from E43-K01, and the freeze/retest tagging convention.

`docs/plan/02-definition-of-ready-done.md` requires an ADR whenever a design decision is taken mid-implementation (section 4.2) and for every spike (section 5.2). This ticket consolidates them and brings the plan docs back into agreement with shipped reality, which is an explicit Epic DoD item ("docs reflect final shipped behavior, not the original proposal").

## Scope / Deliverables
- **ADR-0016 "R4 security-hardening decisions"** in `docs/plan/27-adrs/`, following the existing ADR format, covering at minimum:
  1. Session lifetime and trading-freshness model (which of SR-024 / architecture section 3.10 wins, and why).
  2. Lockout threshold and duration, with the DoS trade-off reasoning (lockout as an attack on availability while a position is open).
  3. CSP style handling: nonce vs scoped `'unsafe-inline'`, per surface, with the Electron packaged-build constraint stated.
  4. Fail-closed rule for `stale`/`unverifiable` posture checks and its consequence for the Live gate.
  5. The Tailscale boundary conclusion from E43-K01 (referencing that spike's own ADR rather than duplicating it).
  6. Freeze and retest tagging convention and what may change during a freeze window.
  7. The decision to keep auto-update disabled until signing is operational (or the contrary, with evidence).
- **Doc updates to shipped reality**:
  - `docs/plan/20-architecture.md` section 3.10 (`SessionManager`, `PasswordAuth`) corrected.
  - `docs/plan/04-security-program.md` section 12.3 required-check list extended (`csp-assertion`, regression-registry check), section 16.2 exception register populated with any accepted items and their expiries, section 7.2 capability matrix reconciled with E43-T09's findings.
  - `docs/plan/03-testing-strategy.md` SR-150 traceability table completed for every SR touched by E43.
  - `docs/plan/23-ws-protocol.md` handshake `Origin` check documented if it diverged.
  - `docs/plan/32-risk-register.md` updated with accepted Medium/Low findings and their expiry dates.
- A short **"what changed in R4 security"** section appended to the security program's change history so the next tester can diff against test #1's assumptions.

## Out of scope
- Writing the pen-test report (the tester's deliverable) or the evidence pack (E43-X07).
- Any code change.

## Acceptance criteria
```gherkin
Scenario: Every mid-implementation decision is recorded
  Given the seven decision areas listed in scope
  Then ADR-0016 records each with context, options considered, decision and consequences
  And no decision is left only as a code comment or a ticket thread

Scenario: Docs match shipped behaviour
  Given the shipped session lifetime and lockout policy
  When docs/plan/20-architecture.md section 3.10 is read
  Then the documented values equal the implemented values
  And a test or configuration reference is cited for each

Scenario: The exception register is honest
  Given accepted Medium or Low findings and any accepted scan exceptions
  Then each appears in docs/plan/04-security-program.md section 16.2 with a compensating control, an approver and an expiry inside one release cycle
  And the same items appear in docs/plan/32-risk-register.md

Scenario: SR traceability is complete
  Given every SR touched by E43
  Then the docs/plan/03-testing-strategy.md traceability table names at least one automated test or scheduled manual procedure per SR
```

## Technical notes / design
- ADR format follows the existing files in `docs/plan/27-adrs/` (ADR-0009, ADR-0010, ADR-0011, ADR-0013 are the nearest neighbours and should be cross-referenced rather than restated).
- Where a decision supersedes an earlier ADR's detail, mark the relationship explicitly in both documents.
- Exception entries must carry the fields section 16.2 mandates: id, requirement/finding, reason, compensating control, requested-by, approved-by (Owner + Security), expiry, tracking ticket.

## Test plan
- **Docs CI**: link checker over relative paths and anchors; a check that every SR id referenced in the traceability table exists in `04-security-program.md`.
- **Review**: Architect and Security engineer read-through; the Owner confirms the exception register matches what they signed.
- Coverage target: N/A (documentation).

## Security notes
An inaccurate security document is itself a security risk: the next tester is briefed from these files (section 13.4 states the tester receives this document, the OpenAPI spec, the WS protocol doc and the architecture doc). A stale capability matrix or an unlisted exception would mislead them. Security review mandatory.

## Accessibility notes
N/A - documentation. (Mermaid diagrams added must carry a text description alongside, consistent with the rest of the plan set.)

## Performance notes
N/A.

## Observability
N/A, except that the exception register's nearest expiry is surfaced as `cv_dependency_exceptions_open` (E43-T05) so an expiring exception is visible before it blocks a release.

## Definition of Done
- [ ] ADR-0016 merged in `docs/plan/27-adrs/` with all seven decision areas.
- [ ] `20-architecture.md`, `04-security-program.md`, `03-testing-strategy.md`, `23-ws-protocol.md` and `32-risk-register.md` updated and reviewed.
- [ ] Docs link check green.
- [ ] Architect and Security engineer approvals recorded; Owner confirms the exception register.
- [ ] PR merged via the merge queue.

## Dependencies
- **E43-T01**, **E43-T03**, **E43-T09**, **E43-K01** supply the decisions being recorded.
- Feeds **E43-X07** (the evidence pack cites these documents).

## Branch
`docs/e43-adr-0016-security-hardening`. PR size guidance: one PR; documentation only.

## References
- `docs/plan/27-adrs/` (ADR-0009, ADR-0010, ADR-0011, ADR-0013).
- `docs/plan/02-definition-of-ready-done.md` sections 4.2, 5.2, 2.2.
- `docs/plan/04-security-program.md` sections 7.2, 12.3, 13.1, 16.2.
- `docs/plan/03-testing-strategy.md`; `docs/plan/20-architecture.md` section 3.10; `docs/plan/32-risk-register.md`.""")

json.dump(T, io.open(os.path.join(os.path.dirname(__file__), "_e43_part5.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("part5", len(T))
