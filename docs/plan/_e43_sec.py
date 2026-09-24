# -*- coding: utf-8 -*-
"""E43 security tickets X01-X07."""
import json, io, os

T = []
def t(**k):
    k.setdefault("phase", "P4 Backtesting & Scripting")
    k.setdefault("milestone", "R4 Live enablement")
    T.append({kk: k[kk] for kk in ["key","kind","title","labels","component","phase","sprint",
        "priority","perspective","risk","estimate","parent","blocked_by","milestone","body"]})

t(key="E43-X01", kind="Task",
  title="Refresh the STRIDE threat model across all ten areas for the R4 surface",
  labels=["type/security","area/auth-rbac","priority/p0","security"],
  component="cross-cutting", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=3, parent="E43", blocked_by=["E34","E42"],
  body="""## Context
SR-157 requires a threat-model review whenever a new epic enters design, a new external interface is added, or a trust boundary changes; `docs/plan/02-definition-of-ready-done.md` section 2.1 makes a STRIDE kickoff mandatory for any epic touching auth, keys, OMS, fan-out or money movement. `docs/plan/04-security-program.md` section 5 already contains a ten-area model (exchange keys, order path, rule engine, fan-out, WS ingestion/fan-out, auth/RBAC, admin screens, recorder data, Electron shell, Tailscale/network) with a risk summary in section 5.11.

That model was written before R2, R3 and R4 shipped their features. By R4 the system has gained: emulated algos, trade-group fan-out with a rate-limit governor, two rule editors, replay, the journal, the admin screen set, the kill switch and the environment gate. The threat model must be re-derived against **what actually exists** before the pen-tester is briefed from it - a stale model produces a mis-scoped test.

## Scope / Deliverables
- A working session (Security engineer + Architect + backend lead + frontend lead + DevSecOps) re-walking all ten areas of section 5 against the shipped architecture, producing:
  - **Updated threat rows** per area with re-scored likelihood/impact and the *current* mitigating control (SR reference), plus any newly identified threat with a proposed control and a ticket.
  - **Updated risk summary** (section 5.11) and the residual-risk register (section 16.1), including whether RR-01..RR-06 still read correctly - notably RR-06 (demo/live parity gaps) which R4 is explicitly meant to close.
  - **Boundary register review** (section 4.1 / `docs/plan/20-architecture.md` section 2.2): confirm B1-B4 are still the complete set given Electron, WSL, Docker and Tailscale as deployed.
  - **Attack-surface inventory**: every externally reachable interface as of the freeze candidate - REST routes, WS topics, the Electron IPC channel list, the custom protocol handler, the CSP report endpoint, the metrics endpoint - so the tester receives a complete map rather than discovering surfaces by accident.
- A **priority ranking** of areas for the pen-test brief: where should the tester's 5-8 days go first, based on the re-scored model. This ranking is an input to E43-X02's brief.
- Updates merged into `docs/plan/04-security-program.md` sections 4.1, 5.x, 5.11 and 16.1.

## Out of scope
- Writing abuse cases (E43-X04, which consumes this); implementing controls (the individual T tickets); the test itself (E43-X02).

## Acceptance criteria
```gherkin
Scenario: All ten areas are re-walked against shipped reality
  Given the ten STRIDE areas in docs/plan/04-security-program.md section 5
  Then each has been reviewed against the freeze-candidate architecture
  And every threat row states the control that exists today with its SR reference, not the control that was planned

Scenario: New threats become tickets
  Given a newly identified threat with no adequate control
  Then it is recorded with a proposed control and a ticket, and the ticket is either scheduled in Sprint 20 or explicitly accepted as a residual risk with owner sign-off

Scenario: The attack-surface inventory is complete
  Given the freeze candidate
  Then every externally reachable interface appears in the inventory
  And a test or enumeration procedure backs the claim of completeness rather than a manual list alone

Scenario: The brief is prioritised by risk
  Given the re-scored model
  Then the pen-test brief ranks the areas, and the ranking's reasoning is recorded
```

## Technical notes / design
- Surface enumeration should be mechanical where possible: routes from the FastAPI app, topics from the WS registry, IPC channels from the preload allowlist (E43-T02), so "complete" is verifiable rather than asserted.
- Re-scoring uses the same likelihood/impact scale already in section 5 so the new numbers are comparable with the old.
- Any threat whose control is "planned" rather than "implemented" must be flagged - that gap is exactly what the tester will find.

## Test plan
Not a code deliverable. Verification: the Architect and Security engineer sign the updated model; a cross-check asserts every area's threats reference at least one SR that exists; the surface inventory is diffed against the mechanical enumeration.

## Security notes
This is the epic's foundational security artefact - every other X ticket and several T tickets depend on its conclusions. The document is sensitive (it is a map of weaknesses) and is stored with the security program doc's access control. It is shared with the pen-tester under the engagement terms (section 13.4 states the tester receives this document).

## Accessibility notes
N/A - documentation. Mermaid diagrams added carry text descriptions.

## Performance notes
N/A.

## Observability
The model names, per area, the telemetry that would reveal an attack in progress; gaps become observability tickets so detection is not left implicit.

## Definition of Done
- [ ] All ten areas re-walked; section 5 and 5.11 updated and merged.
- [ ] Residual-risk register (16.1) and boundary register (4.1) reviewed and updated.
- [ ] Attack-surface inventory produced and mechanically cross-checked.
- [ ] New threats ticketed or accepted with owner sign-off.
- [ ] Prioritised ranking delivered to E43-X02.
- [ ] Architect and Security engineer sign-off recorded.

## Dependencies
- **E34** (fan-out and rate-limit governor) and **E42** (admin screens) are the largest surface additions since the model was written.
- Feeds **E43-X04**, **E43-X02**, **E43-T01**, **E43-T02**, **E43-T03**, **E43-T09**, **E43-K01**.

## Branch
`docs/e43-stride-refresh`. PR size guidance: one PR against `04-security-program.md`.

## References
- `docs/plan/04-security-program.md` sections 4, 5.1-5.11, 16.1, SR-157.
- `docs/plan/20-architecture.md` sections 2.1, 2.2, 3.x.
- `docs/plan/32-risk-register.md`.""")

t(key="E43-X02", kind="Task",
  title="Commission and run the independent penetration test against the frozen build",
  labels=["type/security","area/auth-rbac","priority/p0","security"],
  component="cross-cutting", sprint="Sprint 21", priority="P0 Critical", perspective="Security",
  risk="None", estimate=8, parent="E43",
  blocked_by=["E43-X01","E43-X04","E43-X06","E43-T05","E43-T06","E43-T08","E43-K01","E43-S01"],
  body="""## Context
SR-159 and `docs/plan/04-security-program.md` section 13 make this the gating event of R4: *"Before live enablement (R4), an external penetration test (section 13) MUST be completed with no open High/Critical findings."* The roadmap fixes the window precisely - code freeze **2027-07-02**, pen-test window opens **2027-07-05**, report delivered **2027-07-16** (`docs/plan/30-release-roadmap.md` section 8.5) - and the epic's own description requires the test to be *"executed by an engineer not on the implementing team (external preferred)"*.

Duration guidance is 5-8 tester-days, grey-box, with credentials for each role provided. The tester receives this security program document, the OpenAPI spec, the WS protocol doc and the architecture doc.

This ticket is the **commissioning and running** of the engagement: scope, contract, environment, identities, rules of engagement, daily contact, and receipt of the report. Triage is E43-X03; remediation is funded by the separate 90-pt reserve; retest is E43-X07.

## Scope / Deliverables
- **Engagement setup**: select and contract an independent tester (external preferred; if internal, an engineer with no implementation involvement in E09/E27/E29/E34/E42/E43, recorded explicitly). Confirm the tester is briefed and has signed the terms.
- **Brief pack** delivered to the tester: `04-security-program.md` (with E43-X01's refreshed model and the prioritised area ranking), `22-api-openapi.yaml`, `23-ws-protocol.md`, `20-architecture.md`, the RBAC matrix (E43-T09), the attack-surface inventory, the abuse-case catalogue (E43-X04), the pre-freeze ZAP report (E43-T08), the Tailscale boundary evidence (E43-K01), the QA handover note of unexplored areas (E43-Q02), and the freeze tag hash.
- **Environment and identities**: staging/demo environment in prod-shape; a dedicated tester identity per role (Owner, Manager, Viewer) with demo credentials only - **no live keys are shared** (section 13.4). Kill switch available throughout. Testing windows agreed with the Owner.
- **Scope confirmation** against section 13.2 items 1-11: authentication; authorisation (horizontal and vertical, every route/topic/admin screen, IDOR, grant-revocation timing); order path (CSRF, replay, idempotency abuse, parameter tampering on size/leverage/account/symbol, risk-cap bypass, native-SL-invariant bypass, unarmed live order submission, fan-out to non-granted accounts); rule engine (IR injection, code execution, budget bypass, cross-user rule targeting, import abuse, resource exhaustion); credential handling (reading a secret through any API, log, export or error path; verification bypass; key swap via tampered identifiers); WebSocket layer (unauthenticated subscribe, topic guessing, origin bypass, flooding, slow consumers, malformed frames); web application (XSS stored/reflected/DOM, CSP bypass, clickjacking, open redirect, prototype pollution, dependency-driven client vulns, `postMessage` abuse); Electron shell (preload bridge abuse, navigation escape, protocol handler abuse, ASAR/integrity tampering, update channel); infrastructure (off-tailnet exposure, Tailscale ACL effectiveness, data-store port exposure, container escape basics, secrets on disk, backup encryption); audit and non-repudiation; kill switch (attempts to disable, starve or race it, and verification that it works while other subsystems are degraded).
- **Out-of-scope confirmation** per section 13.3: Bybit's infrastructure, DoS against the exchange, social engineering of the Owner or managers, physical attacks, the Tailscale platform itself, third-party SaaS.
- **Daily contact**: a short daily check-in so a Critical finding is known the day it is found, not at report delivery; any Critical is escalated immediately to the Owner and Security engineer rather than waiting.
- **Report receipt**: findings with reproduction steps, severity (CVSS plus business context) and suggested fixes; archived in the secure store with the freeze tag hash.

## Out of scope
- Triage and ticketing (E43-X03); remediation (reserve-funded tickets); the retest (E43-X07).
- Any testing against the live environment or with live credentials.

## Acceptance criteria
```gherkin
Scenario: The tester is genuinely independent
  Given the selected tester
  Then they are external, or internal with no implementation involvement in the epics under test
  And the independence determination is recorded on this ticket with names

Scenario: The full scope is exercised
  Given the eleven in-scope areas of docs/plan/04-security-program.md section 13.2
  Then the report records coverage for each area, including areas where nothing was found
  And any area not reached is stated explicitly with the reason

Scenario: No live credential is exposed
  Given the engagement
  Then all testing used demo credentials and tester identities on the staging environment
  And no live key, live account or production KEK was shared at any point

Scenario: A Critical finding is escalated immediately
  Given a Critical finding is discovered mid-engagement
  Then it is reported to the Owner and Security engineer on the day of discovery
  And a decision is recorded on whether to pause the engagement pending a fix

Scenario: The report is actionable
  Given the delivered report
  Then each finding carries reproduction steps, a severity with CVSS and business context, and a suggested fix
  And each is reproducible by the Security engineer on the frozen tag
```

## Technical notes / design
- The engagement runs against the **freeze tag** from E43-T05; if a change lands during the window (security fix only, Security + Owner approved), the tester is notified and the new tag hash recorded, because findings must be attributable to a known build.
- Reproduction by the Security engineer before triage is mandatory - an unreproducible finding is triaged as such, with the tester consulted, rather than being either dismissed or accepted on trust.
- Severity uses CVSS plus business context; business context matters disproportionately here (a Medium CVSS issue that lets a manager bypass a risk cap is a High for this product).
- Evidence storage: report, raw notes and any proof-of-concept artefacts are stored with restricted access; PoCs that embed credentials are sanitised before archiving.

## Test plan
The engagement is the test. Internal verification: the Security engineer reproduces every finding on the frozen tag and records the reproduction, which becomes the seed for the regression test in E43-T11.

## Security notes
This is the highest-stakes activity in the epic. Controls around the engagement itself: demo-only credentials, per-role tester identities (no shared accounts), agreed windows, kill switch available, no testing against Bybit beyond normal demo API usage, and confidential handling of findings until fixed. The engagement's own artefacts are sensitive - a leaked report is a map of exploitable weaknesses in a system holding trading credentials.

## Accessibility notes
N/A - no UI deliverable. (Any finding concerning accessible-name information leakage is routed to E43-Q05.)

## Performance notes
The tester's flooding and slow-consumer tests will stress staging; schedule so they do not collide with E43-Q04's load profiles, and ensure staging capacity approximates prod shape so results are meaningful.

## Observability
A secondary objective: during the engagement, confirm which tester actions were **detected** by our own telemetry (auth-failure spikes, authorisation denial spikes, rate-limit hits, WS anomalies). Undetected attack classes become observability tickets - detection gaps are findings even when exploitation failed.

## Definition of Done
- [ ] Independent tester contracted; independence recorded with names.
- [ ] Brief pack delivered; environment and per-role identities provisioned with demo credentials only.
- [ ] Engagement executed within the agreed window against the freeze tag.
- [ ] Daily check-ins held; any Critical escalated same-day.
- [ ] Report delivered, reproduced internally, and archived with the tag hash.
- [ ] Detection-gap observations recorded.
- [ ] Handed to E43-X03 for triage.

## Dependencies
- **E43-X01** (model + priorities), **E43-X04** (abuse cases), **E43-X06** (key/permission checks), **E43-T05** (freeze tag), **E43-T06** (history swept), **E43-T08** (pre-scan clean), **E43-K01** (boundary evidence), **E43-S01** (the gate exists to be attacked).
- Blocks **E43-X03**, **E43-X07**, and ultimately **E44** and the R4 milestone.

## Branch
N/A - engagement management, not code. Artefacts stored in the secure evidence store and referenced here.

## References
- `docs/plan/04-security-program.md` section 13 (13.1-13.5), SR-159, section 14.
- `docs/plan/30-release-roadmap.md` sections 8.2, 8.3, 8.5.
- `docs/plan/07-release-and-prr.md` section 6 Live-enablement gate.""")

t(key="E43-X03", kind="Task",
  title="Triage pen-test findings and file remediation tickets against the reserve",
  labels=["type/security","area/auth-rbac","priority/p0","security"],
  component="cross-cutting", sprint="Sprint 22", priority="P0 Critical", perspective="Security",
  risk="R5 Scope", estimate=5, parent="E43", blocked_by=["E43-X02","E43-Q02"],
  body="""## Context
The report lands **2027-07-16** and remediation must be complete, retested and signed off by **2027-07-30** (`docs/plan/30-release-roadmap.md` section 8.5). That is a two-week window, which only works if triage is fast, disciplined and pre-agreed. The roadmap pre-allocates a **90-pt remediation reserve** in S21-S22 precisely because "unknown findings are certain, their content is not" (section 4) - the reserve exists so remediation does not cannibalise E44/E45.

Triage is a security decision, not an estimation exercise: severity determines whether R4 can proceed at all (`04-security-program.md` section 13.5 - zero open Critical, zero open High; Medium fixed or exception-registered with an owner-signed expiry within one release; Low may defer with a ticket).

## Scope / Deliverables
- **Findings register**: a single authoritative record with, per finding: id, title, tester-assigned severity, internally-confirmed severity (CVSS + business context), affected area (mapped to the section 5 STRIDE area and the section 13.2 scope item), reproduction status, decision (fix now / fix later / accept), remediation ticket key, regression test id, retest status and, where accepted, the exception entry and expiry.
- **Reproduction**: every finding reproduced internally on the frozen tag before triage concludes; unreproducible findings are worked through with the tester rather than silently dropped.
- **Severity confirmation**: internal severity may differ from the tester's - it must be justified in writing when it does, and a downgrade of a Critical/High requires the Owner's agreement, since it changes whether R4 can ship.
- **Remediation ticket filing**: each accepted finding becomes a child ticket of E43 (keys `E43-R01`, `E43-R02`, ... allocated here), with: reproduction steps, the SR it violates, the proposed fix, a mandatory regression test referencing the finding id (SR-153, harness from E43-T11), a retest item, and `sec:critical`/`sec:review` labels per section 11.1. Estimates are drawn against the 90-pt reserve; if the reserve is exceeded, the overflow is escalated to the Owner with options (descope R5 scope, extend the train, accept risk) rather than absorbed silently.
- **Sequencing**: Criticals first, then Highs, then Mediums with the shortest exception horizon; parallelised across the team by area to fit the window.
- **Internal findings merged**: defects from E43-Q02's exploratory charters and E43-T08's ZAP triage enter the same register with `INT-` ids, so there is one list, not three.
- **Exception entries**: for anything accepted, a `docs/plan/04-security-program.md` section 16.2 entry with id, requirement/finding, reason, compensating control, requested-by, approved-by (Owner + Security), expiry (max one release cycle) and tracking ticket; mirrored into `docs/plan/32-risk-register.md`.
- **Daily standup** on remediation progress during the window, with a burn-down against the reserve.

## Out of scope
- Performing the fixes (the filed `E43-Rnn` tickets); the retest (E43-X07); building the regression harness (E43-T11).

## Acceptance criteria
```gherkin
Scenario: Every finding is reproduced and dispositioned
  Given the delivered report
  Then every finding has a reproduction status, a confirmed severity with justification, and a decision
  And no finding is closed without a recorded reason

Scenario: Criticals and Highs all have tickets scheduled inside the window
  Given findings confirmed as Critical or High
  Then each has a remediation ticket scheduled in Sprint 22 with an owner and an estimate drawn against the reserve
  And none is proposed for the exception process, because section 13.5 forbids accepting open Critical or High

Scenario: Accepted Mediums are properly registered
  Given a Medium finding accepted rather than fixed
  Then a section 16.2 exception entry exists with a compensating control, an Owner approval, an expiry within one release cycle and a tracking ticket
  And the same item appears in docs/plan/32-risk-register.md

Scenario: Reserve overflow is escalated, not absorbed
  Given the total remediation estimate exceeds the 90-point reserve
  Then the Owner is presented with explicit options and the decision is recorded before work continues

Scenario: Every remediation ticket carries a regression test requirement
  Given any filed remediation ticket
  Then its definition of done requires an automated regression test referencing the finding id, demonstrated to fail pre-fix
```

## Technical notes / design
- Finding ids are the tester's verbatim; internal findings use `INT-nnn` in the same namespace so E43-T11's registry is uniform.
- Severity is recorded twice (tester, internal) and never overwritten - the divergence is itself information for the next engagement.
- Business-context adjustment rules agreed in advance: anything bypassing the native-SL invariant, a risk cap, the live gate, RBAC scoping, or key confidentiality is at least High regardless of CVSS.
- Ticket template for `E43-Rnn` follows the section 14 acceptance-criteria templates appropriate to the affected area (14.2 authorisation-bearing endpoint, 14.3 order path, 14.4 credential management, 14.5 rule engine, 14.6 admin screen, 14.7 Electron, 14.8 data/export).

## Test plan
Not a code deliverable. Verification: a completeness check that the register's finding count matches the report's; that every Critical/High has a scheduled ticket; that every accepted item has an exception entry with an expiry; and that every remediation ticket references a regression test id.

## Security notes
Triage is where a High quietly becomes a Medium under schedule pressure - the requirement that any Critical/High downgrade needs the Owner's written agreement exists to make that visible. Findings and the register are confidential until remediated. Data classification: the register describes exploitable weaknesses in a live-money system.

## Accessibility notes
Any finding concerning accessible-name information disclosure is routed to E43-Q05 and E43-D03 rather than being fixed in isolation.

## Performance notes
N/A, except that remediation must not regress the R3 performance baseline - the comparison is made in E43-Q06.

## Observability
Metric `cv_security_findings_open{severity}` driven from the register, surfaced on SCR-137 (E43-S02) so the Owner sees the remediation burn-down on the same screen as the gate.

## Definition of Done
- [ ] Findings register complete, with every finding reproduced, severity-confirmed and dispositioned.
- [ ] Remediation tickets (`E43-Rnn`) filed with owners, estimates against the reserve, regression-test requirements and retest items.
- [ ] Zero Critical/High proposed for acceptance.
- [ ] Section 16.2 exceptions and `32-risk-register.md` entries created for accepted items with owner-signed expiries.
- [ ] Reserve burn-down published; any overflow escalated and decided.
- [ ] Security engineer and Owner sign-off on the triage outcome.

## Dependencies
- **E43-X02** delivers the report; **E43-Q02** contributes internal findings.
- Feeds **E43-T11**, **E43-X07**, **E43-Q06** and the R4 PRR.

## Branch
N/A - register and tickets. Exception entries land via a docs PR (`docs/e43-exception-register`).

## References
- `docs/plan/04-security-program.md` sections 11.1, 13.4, 13.5, 14, 16.2.
- `docs/plan/30-release-roadmap.md` sections 4, 8.2, 8.3, 8.5.
- `docs/plan/32-risk-register.md`; `docs/plan/02-definition-of-ready-done.md` section 6.""")

t(key="E43-X04", kind="Task",
  title="Author the abuse-case catalogue for auth, order path, fan-out and admin",
  labels=["type/security","area/auth-rbac","priority/p0","security","qa"],
  component="cross-cutting", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-X01"],
  body="""## Context
`docs/plan/02-definition-of-ready-done.md` section 3.2 requires, for anything touching keys/withdrawal/RBAC, *"a manual abuse-case check performed (e.g. attempt privilege escalation, attempt withdrawal toggle)"*. Today that instruction is a sentence; it needs to be a catalogue, so that "abuse case checked" means the same thing on every ticket and so that the pen-tester starts from what we have already tried rather than rediscovering it.

Abuse cases are the inverse of user stories: an actor with a goal that the system must defeat. They are derived from E43-X01's refreshed STRIDE model and from the specific invariants this product cannot afford to lose - the native stop-loss on every fanned-out order, the withdrawal permission being off on every key, RBAC scoping, the live gate, and audit non-repudiation.

## Scope / Deliverables
A catalogue of abuse cases, each written in the same Gherkin style as the user stories (actor, goal, attempt, required system response) and mapped to the SR it exercises and the STRIDE area it belongs to. Minimum coverage:
- **Authentication**: enumerate users through timing or error differences; brute-force past the lockout by rotating source addresses; lock a colleague out deliberately while they hold a position; replay a TOTP code; reuse a consumed recovery code; bypass step-up by reusing a stale step-up token; abuse the break-glass path.
- **Session**: adopt a fixed session; keep a rotated session alive; act with a session that outlived a role change; use a session from a different origin; extract a session token from browser storage.
- **Authorisation**: reach another manager's account by id substitution in every payload shape (path, query, body, nested object, batch element, WS subscription); reach Owner-only admin functions indirectly through an export, a job-status poll or a bulk endpoint; act on a grant that was revoked seconds ago; distinguish "forbidden" from "not found" to enumerate objects.
- **Order path**: submit an order without a native stop-loss; tamper size, leverage, symbol or account on an otherwise legitimate ticket; replay an order submission to double-fill; abuse `orderLinkId` idempotency; exceed a risk cap by splitting orders; submit a live order while unarmed; fan out to an account the actor has no grant on; exhaust a UID's rate budget so an exit cannot be sent.
- **Credentials**: read a secret through any API response, log line, error message, export, backup or metrics label; swap a key by tampering with its identifier; persist a key with withdrawal enabled; turn withdrawal on after verification; cause the verification call to fail so the key is treated as fine.
- **Rule engine**: inject into the IR; escape the interpreter; exceed the budget; target another user's account from a rule; exhaust resources through a pathological rule.
- **Admin and the gate**: enable live trading with an outstanding gate item; forge or withdraw an attestation without audit; dismiss a finding without a reason; modify or delete an audit entry; break the hash chain undetectably; export the audit log without the export being audited.
- **Kill switch**: disable it, starve it of rate-limit budget, or race it with an in-flight order; verify it still works while other subsystems are degraded.
- For each case: the **expected system response**, the **control** (SR reference), whether it is currently covered by an automated test (and which), and whether it is a manual check.
- A **per-ticket abuse-case checklist** derived from the catalogue, so a story touching, say, admin screens inherits the right subset rather than the whole catalogue.

## Out of scope
- Executing them as a formal engagement (E43-X02); building missing automated coverage (routed to E43-Q03 and E43-T11); fixing what they reveal.

## Acceptance criteria
```gherkin
Scenario: Every STRIDE area has abuse cases
  Given the ten areas in docs/plan/04-security-program.md section 5
  Then each has at least one abuse case in the catalogue
  And each case names the control and the SR it exercises

Scenario: Coverage gaps are explicit
  Given each abuse case
  Then it states whether an automated test covers it, naming the test, or that it is a manual check
  And every uncovered case with a High or Critical consequence has a ticket to automate it

Scenario: The checklist is usable per ticket
  Given a story touching admin screens
  When its author consults the catalogue
  Then a defined subset of abuse cases applies, and performing them is a recordable DoD step

Scenario: A case that currently succeeds is a finding
  Given an abuse case is executed against the freeze candidate and the system does not defeat it
  Then it is filed as an internal finding with an INT id and enters the same register as pen-test findings
```

## Technical notes / design
- Cases are written so they can be executed by a person with staging access and no source knowledge - that is what makes them usable by QA and by the tester.
- Where a case is already automated, the catalogue links the test id, which keeps E43-Q03's suite and this catalogue mutually honest.
- The withdrawal-toggle case is deliberately included even though the app never requests withdrawal permission: the check is that the system *detects and refuses* a key whose exchange-side permission changed after registration.

## Test plan
The catalogue is executed once against the freeze candidate as part of E43-Q02's charters; anything not defeated becomes an internal finding. Thereafter the automated subset runs continuously via E43-Q03.

## Security notes
The catalogue is an attack playbook for this specific system and is stored with the security program doc's access control. It is shared with the tester (as an input, to avoid duplicated effort) and with QA. Executing cases uses demo credentials on staging only.

## Accessibility notes
N/A - documentation.

## Performance notes
Resource-exhaustion cases overlap with E43-Q04's load profiles; the catalogue references those profiles rather than duplicating them.

## Observability
Each case records whether executing it produced a detectable signal in logs, metrics or the audit log. A case that succeeds silently is doubly bad and is called out.

## Definition of Done
- [ ] Catalogue written covering all ten STRIDE areas and all listed surfaces.
- [ ] Every case mapped to a control/SR and to its automated test or manual designation.
- [ ] Per-ticket checklist subsets defined and referenced from the DoD guidance.
- [ ] Gaps ticketed for automation.
- [ ] Reviewed by the Security engineer, the QA lead and the Architect.
- [ ] Delivered to E43-X02's brief pack.

## Dependencies
- **E43-X01** supplies the refreshed threat model the cases are derived from.
- Feeds **E43-X02**, **E43-Q02**, **E43-Q03**, **E43-T11**.

## Branch
`docs/e43-abuse-cases`. PR size guidance: one PR; documentation.

## References
- `docs/plan/04-security-program.md` sections 5, 13.2, 14.1-14.8, SR-152, SR-153.
- `docs/plan/02-definition-of-ready-done.md` sections 3.2, 8.
- `docs/plan/11-user-stories.md` (style reference for Gherkin).""")

t(key="E43-X05", kind="Task",
  title="Complete the custom Semgrep ruleset and DAST rule tuning",
  labels=["type/security","area/auth-rbac","priority/p1","security"],
  component="infra", sprint="Sprint 20", priority="P1 High", perspective="Security",
  risk="None", estimate=3, parent="E43", blocked_by=["E02","E43-X01"],
  body="""## Context
`docs/plan/04-security-program.md` section 12.2 specifies twelve **custom CandleViewer Semgrep rules** maintained in `.semgrep/`, each encoding an invariant that a generic ruleset cannot know:
1. `cv-route-without-capability` - a FastAPI route decorator without a `capability=` argument.
2. `cv-secret-as-str` - an exchange secret assigned to a plain `str` or passed to a formatting call.
3. `cv-log-secret` - a logging call whose arguments include a known secret-bearing field name.
4. `cv-order-without-sl` - an OMS order construction path lacking the stop-loss validation call.
5. `cv-query-without-scope` - a SQLAlchemy query on account-scoped tables without a grant filter.
6. `cv-eval-in-rule-engine` - any dynamic execution primitive inside the rule-engine package.
7. `cv-electron-unsafe-webprefs` - `BrowserWindow` options deviating from SR-110.
8. `cv-ipc-dynamic-channel` - `contextBridge`/`ipcRenderer` with a non-literal channel.
9. `cv-cors-wildcard` - CORS configured with `*` or origin reflection.
10. `cv-audit-missing` - mutation handlers on security-relevant entities with no audit write in the same function.
11. `cv-unpinned-action` - a GitHub Action referenced by tag instead of SHA.
12. `cv-path-from-request` - a filesystem path constructed from request data.

By R4 these must all exist, be tuned against the real codebase (a rule with a 50% false-positive rate gets ignored, which is worse than no rule), and block at `ERROR` severity. This ticket completes, tunes and documents them, and does the equivalent tuning for the DAST (ZAP) ruleset so E43-T08's results are comparable run to run.

## Scope / Deliverables
- Implement or complete each of the twelve rules in `.semgrep/`, each with: a positive test fixture, a negative test fixture, a message naming the SR it enforces, and a documented remediation.
- **Tune against the real codebase**: run each rule over the full repository, review every hit, and either fix the code or refine the rule. The end state is zero unexplained findings; any suppression carries an inline justification and security approval (mirroring the `# nosec` policy in section 12.1).
- Confirm the registry packs listed in section 12.2 are enabled (`p/python`, FastAPI equivalents, `p/typescript`, `p/react`, `p/electron`, `p/docker`, `p/github-actions`, `p/secrets`, `p/owasp-top-ten`, `p/sql-injection`, `p/jwt`, `p/insecure-transport`).
- **Severity wiring**: `ERROR`-severity findings block the merge; `WARNING` requires a triage comment (section 12.1) - verify both behaviours actually hold in CI rather than assuming.
- Confirm the other SAST gates are configured as specified: Bandit (High/Medium blocks; `# nosec` needs justification + security approval), Ruff `S` ruleset plus forbidden-API rules (`eval`, `exec`, `pickle`, `subprocess shell=True`, raw `str` secrets), ESLint `security`/`no-unsanitized`/React rules including `dangerouslySetInnerHTML` without a sanitiser, CodeQL for Python and TS.
- **DAST tuning**: a committed ZAP tuning/context file (alert thresholds, known-false-positive suppressions with justifications) so E43-T08's runs are diffable; each suppression names why it is not exploitable here.
- **Fuzzing configuration** (SR-155): confirm Atheris targets exist for the exchange-message decoders and the client WS binary framing decoder, and Hypothesis targets for the rule IR parser, with a committed corpus and a nightly longer run.
- Document the ruleset in `docs/plan/04-security-program.md` section 12.2 if anything diverged.

## Out of scope
- Running the DAST scan (E43-T08); dependency/license scanning (E43-T05); secrets scanning (E43-T06).

## Acceptance criteria
```gherkin
Scenario: All twelve custom rules exist and are tested
  Given the .semgrep directory
  Then each of the twelve rules exists with a positive and a negative fixture
  And the rule test suite passes in CI

Scenario: The ruleset is clean against the codebase
  Given a full-repository Semgrep run
  Then there are zero unexplained findings
  And every suppression carries an inline justification and a recorded security approval

Scenario: An invariant violation blocks the merge
  Given a pull request that adds a route without a capability argument, or an OMS order path without the stop-loss validation call, or a query on an account-scoped table without a grant filter
  When CI runs
  Then Semgrep fails at ERROR severity and the merge is blocked

Scenario: DAST results are comparable
  Given two consecutive ZAP runs with no code change
  Then the alert sets are identical
  And every suppressed alert has a recorded justification

Scenario: Fuzz targets exist and run
  Given the decoders and the rule IR parser
  Then fuzz targets exist with a committed corpus and a nightly run
  And a newly discovered crash blocks the next release
```

## Technical notes / design
- Rules 4 and 5 (`cv-order-without-sl`, `cv-query-without-scope`) are the hardest to write without false positives because they are dataflow properties, not syntactic ones; use Semgrep taint mode and accept a narrower, precise rule over a broad, noisy one - a rule that fires only on the common construction path is still valuable, and the broader property is covered by E43-Q03's runtime tests.
- Rule 10 (`cv-audit-missing`) needs an explicit list of security-relevant entities; derive it from `docs/plan/04-security-program.md` section 8.2's event catalogue so the rule and the catalogue cannot drift.
- Rule 2/3 need a canonical list of secret-bearing field names shared with the redaction filter (E43-T06), so all three controls agree on what a secret looks like.
- Suppression policy: inline comment with rule id, reason, ticket and reviewer initials; a CI check counts suppressions and fails if the count grows without an accompanying approval.

## Test plan
- **Rule tests**: positive/negative fixtures per rule, run in CI (Semgrep's own test runner).
- **Integration**: a scratch PR per high-value rule (route without capability, missing SL, unscoped query, wildcard CORS, unsafe webPreferences, dynamic IPC channel) asserting the merge is blocked.
- **Tuning evidence**: the full-repo run output before and after tuning, attached.
- Coverage target: N/A (rules); the measure is zero unexplained findings plus passing rule tests.

## Security notes
These rules are the cheapest possible enforcement of the product's hardest invariants - the native SL on the order path, account scoping on every query, capability declarations on every route. They fail *at review time*, before a defect can reach a tester or a user. The risk to manage is rule rot: a noisy rule gets suppressed everywhere, so tuning quality matters more than rule count. Security review mandatory.

## Accessibility notes
N/A - no UI surface. (The ESLint a11y rules remain owned by the frontend platform configuration; this ticket does not change them.)

## Performance notes
Semgrep must fit the PR pipeline budget in `docs/plan/06-performance-and-load-standard.md`; use targeted paths per rule and incremental scanning on diffs, with the full scan nightly.

## Observability
CI metric `cv_sast_findings{rule,severity}` and `cv_sast_suppressions_total`; a rising suppression count is a leading indicator of rule rot and is reviewed at the biweekly scan triage (section 11.4).

## Definition of Done
- [ ] All twelve custom rules implemented, fixture-tested and tuned to zero unexplained findings.
- [ ] Registry packs, Bandit, Ruff, ESLint and CodeQL configurations verified against section 12.1.
- [ ] Blocking behaviour verified by scratch PRs for the high-value rules.
- [ ] ZAP tuning/context file committed with justified suppressions.
- [ ] Fuzz targets and corpus confirmed with a nightly run.
- [ ] `docs/plan/04-security-program.md` section 12.2 updated if anything diverged.
- [ ] Security engineer review; PR merged via the merge queue.

## Dependencies
- **E02** (CI pipeline) and **E43-X01** (which invariants matter most on the current surface).
- Feeds **E43-T01**, **E43-T02**, **E43-T08** and every subsequent PR in the repository.

## Branch
`chore/e43-sast-dast-rules`. PR size guidance: group rules by language/area across three PRs.

## References
- `docs/plan/04-security-program.md` sections 12.1, 12.2, 12.3, 8.2, SR-155.
- `docs/plan/03-testing-strategy.md`; ADR-0013 CI pipeline.""")

t(key="E43-X06", kind="Task",
  title="Key-permission and RBAC-grant verification audit ahead of the pen-test",
  labels=["type/security","area/auth-rbac","priority/p0","security"],
  component="auth", sprint="Sprint 21", priority="P0 Critical", perspective="Security",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-S02","E43-T09","E27"],
  body="""## Context
R4 exit criterion 2 (`docs/plan/30-release-roadmap.md` section 8.3) is unusually specific: *"every configured key on every account manually verified in **Bybit's own settings** (not merely trusted from app config) to have withdrawal OFF, IP whitelist limited to the Tailscale-reachable addresses, and trade+read scope only. The audit record includes the Bybit-reported scopes, not just the app's belief about them."* Section 13.5 repeats it as a live-enablement exit criterion, and `docs/plan/07-release-and-prr.md` section 6 makes the key-permission audit one of the four gate items.

The roadmap schedules the audit as work item `s10` for **2027-07-19 to 2027-07-23**, deliberately in the first week of S22 so findings have a full week to be fixed before the 2027-07-30 gate. This ticket performs the **pre-test** half in S21 - verifying the demo/staging key estate and the grant model that the tester will probe - so the tester does not spend a day discovering a misconfigured key that we could have found ourselves. E44 owns the production key-permission audit *tooling*; this ticket owns the security verification act and the record.

## Scope / Deliverables
- **Per-key verification record** for every key configured in the environments under test: Bybit-reported scopes from `GET /v5/user/query-api` (the authority), the app's stored belief, agreement or divergence, IP-whitelist contents versus the current egress address, key age versus the 90-day rotation policy, last successful use, and the UID the key resolves to.
- **Manual cross-check** in Bybit's own settings UI for at least the demo estate, with evidence captured - the requirement is explicitly that the exchange's own view is consulted, not only the API's answer.
- **Withdrawal assertion**: no key has withdrawal permission; any that does is disabled immediately and an incident note written (this is a standing invariant, not a preference).
- **IP whitelist assertion**: every key's whitelist is limited to the Tailscale-reachable addresses; record any drift (OQ-05 in section 16.1a acknowledges a home egress IP may change, with the documented decision to accept brief trading outage over removing the whitelist).
- **Scope assertion**: trade + read only; no unexpected permission (transfer, sub-account management) unless justified and recorded.
- **UID mapping record**: which credentials resolve to which UID - this matters because rate limits are per UID and shared across keys (SR-044a), so the audit record doubles as the input to E43-Q04's budget assertions.
- **RBAC grant audit**: for every user, the role and the account grants actually stored in `user_roles` and `user_account_access`, compared against the intended assignment; any orphaned grant, any user with more scope than intended, and any disabled user retaining a grant is corrected and audited.
- **2FA coverage check**: every trading-capable user has TOTP enrolled (SR-020); any exception is closed before the test.
- Results recorded in the audit record and surfaced through E43-S02's posture checks, so the same facts drive the panel and the gate.

## Out of scope
- The production (live) key audit itself, which happens in S22 against live keys as an R4 exit item with E44's tooling; this ticket verifies the estate under test and proves the procedure.
- Key rotation flows (E27); building the verification call (E27/E43-S02).

## Acceptance criteria
```gherkin
Scenario: Exchange truth is recorded, not app belief
  Given every configured key in the environments under test
  Then the audit record contains the Bybit-reported scopes for each
  And any divergence between exchange-reported scopes and the app's stored belief is recorded and resolved

Scenario: No key carries withdrawal permission
  Given the audit
  When any key is found with withdrawal enabled
  Then that key is disabled immediately, an incident note is written, and the account is treated as compromised until the key is replaced

Scenario: Whitelists are correct or drift is recorded
  Given each key's IP whitelist
  Then it is limited to the Tailscale-reachable addresses
  And any drift from the current egress address is recorded with the remediation decision

Scenario: Grants match intent
  Given the stored role and account grants for every user
  Then each matches the intended assignment
  And any orphaned or excessive grant is removed and the removal is audited

Scenario: Every trading-capable user has 2FA
  Given the user list
  Then every user with any trading capability has TOTP enrolled
  And any exception is closed before the pen-test window opens

Scenario: The record feeds the panel and the gate
  Given the completed audit
  Then the same verdicts appear on SCR-137 and SCR-128
  And the key-permission gate item reflects the audit's completion date and attester
```

## Technical notes / design
- `GET /v5/user/query-api` is rate-limited at 10 req/s per UID and shares the UID's budget (SR-044b's table), so the audit sweep acquires from the per-UID tracker rather than bursting.
- The record's schema mirrors E43-S02's `Verdict` shape so the audit and the continuous checks are the same data, captured at different cadences.
- Manual cross-check evidence: screenshots of Bybit's key settings with the secret fields absent/masked, stored in the secure evidence store. Never capture a secret in evidence.
- Any disabled key triggers the existing `admin.key_marked_compromised` audited action rather than an out-of-band database edit.

## Test plan
- **Procedure verification**: perform the audit on the staging estate and confirm every field can be filled from real sources.
- **Integration**: the divergence case (app believes withdrawal off, exchange reports on) exercised against a recorded fixture and confirmed to produce a failing verdict and an alert.
- **Contract**: the audit record fields align with `SecuritySummary` so the panel and the record cannot disagree.
- Coverage target: N/A (procedure); the artefact is the record plus the fixes it triggers.

## Security notes
This is a crown-jewel control (assets A-01/A-02). Threats (`04-security-program.md` section 5.1): a key silently gaining withdrawal permission after registration; a whitelist removed to "fix" connectivity; a grant left behind after a role change. The audit is the compensating control for all three, and its value depends entirely on consulting the exchange rather than our own database. No secret material is ever read, displayed, exported or captured in evidence (SR-069, SR-005 family). Security review mandatory; the record is an input to the Owner's written sign-off.

## Accessibility notes
The audit's verdicts are rendered on SCR-128/SCR-137 by E43-S02 and are covered by E43-Q05; this ticket ensures every verdict has a text remediation string so the panel is not left with a status and no action.

## Performance notes
The sweep must not consume rate-limit budget needed by the order path; it runs off-peak and respects the SR-071 reserve.

## Observability
Metrics `cv_key_withdrawal_verified{key_id,state}`, `cv_key_whitelist_drift{key_id}`, `cv_key_age_days{key_id}`, `cv_grants_unexpected_total`, `cv_2fa_coverage_ratio`. Audit events for every correction made during the audit.

## Definition of Done
- [ ] Per-key verification record complete for every key in the environments under test, including Bybit-reported scopes.
- [ ] Manual cross-check performed in Bybit's own settings with sanitised evidence stored.
- [ ] Zero keys with withdrawal permission; whitelists correct or drift recorded with decisions.
- [ ] UID mapping recorded and handed to E43-Q04.
- [ ] RBAC grant audit complete with corrections audited; 2FA coverage complete for trading-capable users.
- [ ] Verdicts visible on SCR-137/SCR-128 and reflected in the gate item.
- [ ] Security engineer sign-off; record filed for the Owner's R4 sign-off.

## Dependencies
- **E43-S02** (posture checks and the verification call), **E43-T09** (grant model correctness), **E27** (key vault and key metadata).
- Feeds **E43-X02** (tester briefed on a verified estate), **E43-S01** (gate item), **E43-X07** (evidence pack).

## Branch
`chore/e43-key-permission-audit` (record and any corrective scripts; no secret material in the repository).

## References
- `docs/plan/30-release-roadmap.md` section 8.3 exit criterion 2, section 13 work item `s10`.
- `docs/plan/04-security-program.md` sections 6.1, 6.2, 5.1, 13.5, 16.1a (OQ-05), SR-020, SR-044b, SR-071.
- `docs/plan/07-release-and-prr.md` section 6.
- `docs/plan/21-database-schema.md` `api_keys`, `api_key_rotations`, `user_roles`, `user_account_access`.
- `docs/plan/11-user-stories.md` US-ACCT-003, US-ACCT-005, US-ADMIN-010.""")

t(key="E43-X07", kind="Task",
  title="Retest Critical and High findings and assemble the R4 evidence pack",
  labels=["type/security","area/auth-rbac","priority/p0","security"],
  component="cross-cutting", sprint="Sprint 22", priority="P0 Critical", perspective="Security",
  risk="None", estimate=5, parent="E43",
  blocked_by=["E43-X03","E43-T11","E43-T12","E43-Q06","E43-X06"],
  body="""## Context
`docs/plan/04-security-program.md` section 13.5 sets the exit criteria for live enablement: zero open Critical, zero open High, Mediums fixed or exception-registered with an owner-signed expiry, **a retest report confirming remediation of all fixed items**, kill-switch drill passed, credential verification green on every live key, backup restore drill passed, audit chain verified and mirrored. Section 13.1 schedules the retest explicitly ("Retest of #1 findings + configuration review of the live-bound deployment", blocking, SR-159) and allows 2-3 tester-days.

The R4 gate on **2027-07-30** consumes a single artefact: an evidence pack the Owner can read and sign. This ticket produces it, and runs the retest that makes it true.

## Scope / Deliverables
- **Retest engagement** (2-3 tester-days) by the same independent tester against the post-remediation tag: every Critical and High finding re-attempted, every fixed Medium spot-checked, plus a configuration review of the live-bound deployment (keys, IP whitelist, Tailscale ACLs, backups) per section 13.1.
- **Retest report** archived with both tag hashes (freeze and retest), stating per finding: retested, result, and residual comment.
- **Evidence pack** assembled for the R4 PRR and the Owner's written sign-off, containing:
  1. Pen-test report (E43-X02) and retest report, with the independence determination.
  2. Findings register with dispositions, remediation tickets and regression test ids (E43-X03, E43-T11).
  3. Section 16.2 exception entries and matching `32-risk-register.md` rows, with owner signatures and expiry dates.
  4. Key-permission audit record incl. Bybit-reported scopes (E43-X06) and, for the live estate, the S22 production audit result.
  5. Hardening evidence: CSP assertion output, Electron hardening assertion output, RBAC matrix coverage result, audit-chain verification and mirror comparison, SBOM set with signatures, SCA/license triage table, secrets-history sweep result, Tailscale boundary evidence.
  6. QA sign-off (E43-Q06) with the baseline-versus-post-remediation comparison.
  7. a11y audit report (E43-Q05).
  8. Load profile results incl. the SR-071 reserve assertion (E43-Q04).
  9. The Live-enablement gate snapshot from E43-S01 showing all four items satisfied with attesters and dates.
  10. ADR-0016 and the updated security program sections (E43-T12).
- **Gate verification**: confirm each of the four `docs/plan/07-release-and-prr.md` section 6 items is evidenced, and that the gate service's machine verdict agrees with the pack - a disagreement between the pack and the running system is itself a blocker.
- **Owner walkthrough**: present the pack, obtain the written sign-off required by roadmap exit criterion 10, and record it.
- **Detection-gap follow-ups**: file tickets for any attack class the tester executed that our telemetry did not reveal (from E43-X02's observations).

## Out of scope
- Performing remediation (the `E43-Rnn` tickets); the chaos, rollback and restore drills (E45) and the environment-separation proof (E44) - the pack references their results but does not produce them.
- The first live trade (roadmap exit criterion 11, executed after the gate opens).

## Acceptance criteria
```gherkin
Scenario: Every Critical and High is retested and closed
  Given the findings confirmed Critical or High
  When the retest runs against the post-remediation tag
  Then each is confirmed remediated by the independent tester
  And zero remain open

Scenario: Accepted items are signed and time-boxed
  Given Medium or Low findings accepted rather than fixed
  Then each has an owner-signed exception with an expiry inside one release cycle in docs/plan/04-security-program.md section 16.2
  And the same items appear in docs/plan/32-risk-register.md

Scenario: The pack is complete and self-contained
  Given the R4 PRR
  When the evidence pack is reviewed
  Then all ten listed components are present with dates and authors
  And no component is a promise rather than an artefact

Scenario: The running system agrees with the pack
  Given the Live-enablement gate service
  When the pack claims all four gate items are satisfied
  Then the gate service independently reports the same, with fresh evaluations
  And any disagreement blocks the gate until reconciled

Scenario: Owner sign-off is recorded
  Given the completed pack and walkthrough
  Then the Owner's written authorisation for live enablement is recorded, referencing the pen-test summary and the key audit

Scenario: Detection gaps become work
  Given attack classes executed during the engagement that produced no telemetry signal
  Then each has a follow-up observability ticket
```

## Technical notes / design
- Both tag hashes appear on every artefact so a reader can tell which build each claim is about; artefacts referring to the pre-remediation build are labelled as such rather than quietly reused.
- The gate snapshot is taken live during the walkthrough, not copied from an earlier screenshot - this is the check that the pack and the system have not diverged.
- Storage: the pack lives in the secure evidence store with restricted access; only the sign-off record and a redacted summary go into the release ticket.
- If the retest finds a Critical or High unremediated, R4 does not ship: the ticket's escalation path is to the Owner with the options and the date impact, recorded.

## Test plan
- **Completeness check**: a checklist run against the ten components with author and date per item.
- **Agreement check**: live gate verdict compared with the pack's claims during the walkthrough.
- **Regression check**: E43-T11's registry shows a passing regression test for every finding marked fixed.
- Coverage target: N/A (assurance artefact).

## Security notes
The evidence pack is the most sensitive single document the project produces - it consolidates a map of every weakness found, fixed and accepted, alongside the key estate. Access is restricted; the redacted summary is what circulates. The pack is also a non-repudiation artefact: the Owner's sign-off on it authorises real-money trading, so every claim in it must be an artefact with a date and an author, never a summary written from memory.

## Accessibility notes
The pack includes the a11y audit; its own presentation to the Owner must be readable as plain text/PDF with real headings, not as a set of screenshots.

## Performance notes
Includes the load and latency comparison from E43-Q06 and E43-Q04 so the Owner can see that hardening did not degrade the trading path.

## Observability
Records the detection results from E43-X02 (which attacks were visible in telemetry) and files the gaps - this is how the pen-test improves monitoring rather than only code.

## Definition of Done
- [ ] Retest executed by the independent tester against the post-remediation tag; report archived with both tag hashes.
- [ ] Zero open Critical/High confirmed by the tester.
- [ ] All accepted items carry owner-signed exceptions with expiries in section 16.2 and `32-risk-register.md`.
- [ ] Evidence pack assembled with all ten components, each dated and attributed.
- [ ] Gate service verdict independently confirms the pack during the walkthrough.
- [ ] Owner's written authorisation for live enablement recorded.
- [ ] Detection-gap tickets filed.
- [ ] Security engineer, Architect, DevSecOps and QA lead sign-offs recorded for the PRR (`docs/plan/30-release-roadmap.md` section 8.4).

## Dependencies
- **E43-X03** (findings and remediation), **E43-T11** (regression guarantees), **E43-T12** (ADR and doc accuracy), **E43-Q06** (QA sign-off), **E43-X06** (key audit record).
- Blocks the R4 milestone and, through it, **E44**'s live enablement.

## Branch
N/A - assurance artefacts. Any doc updates land via `docs/e43-r4-evidence`.

## References
- `docs/plan/04-security-program.md` sections 13.1, 13.5, 16.2, SR-159, SR-160.
- `docs/plan/30-release-roadmap.md` sections 8.3, 8.4, 8.5.
- `docs/plan/07-release-and-prr.md` sections 5.2, 6.
- `docs/plan/32-risk-register.md`.""")

json.dump(T, io.open(os.path.join(os.path.dirname(__file__), "_e43_part7.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("part7", len(T))
