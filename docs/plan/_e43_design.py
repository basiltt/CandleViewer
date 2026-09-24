# -*- coding: utf-8 -*-
"""E43 design tickets (D) - scheduled 2 sprints ahead of the consuming FE stories in S20."""
import json, io, os

T = []
def t(**k):
    k.setdefault("phase", "P4 Backtesting & Scripting")
    k.setdefault("milestone", "R4 Live enablement")
    T.append({kk: k[kk] for kk in ["key","kind","title","labels","component","phase","sprint",
        "priority","perspective","risk","estimate","parent","blocked_by","milestone","body"]})

t(key="E43-D01", kind="Task",
  title="Wireframe to hi-fi: SCR-137 security centre and the Live-enablement gate",
  labels=["type/design","area/auth-rbac","priority/p0","design","ux-research","a11y","security"],
  component="web", sprint="Sprint 18", priority="P0 Critical", perspective="Product",
  risk="None", estimate=5, parent="E43", blocked_by=["E42"],
  body="""## Context
SCR-137 `Admin: security centre` (`/admin/security`) is the screen on which the Owner decides whether this installation is safe enough to touch live money. `docs/plan/14-screens-catalogue.md` SCR-137 specifies it as: failed-login trends, active sessions across all users, step-up usage, key-policy compliance, the dependency/vulnerability summary from the last scan, **the pen-test status gate for Live enablement**, and links to the security program doc. Its three states are *compliant*, *findings outstanding (count by severity)* and *Live enablement blocked* ("Live trading stays disabled until the pen-test sign-off is recorded").

It serves two user stories: **US-ADMIN-010 Security posture panel** (Must) and **US-ADMIN-012 Live-trading enablement gate** (Must), both in `docs/plan/11-user-stories.md` section 26. US-ADMIN-010's NFR is decisive for the design: *"every check is machine-evaluated, not a manual checklist"* - so the screen must never look like a to-do list the Owner can tick. US-ADMIN-012 requires that when the gate is closed it *"lists exactly which items are outstanding"*, and that opening it needs step-up authentication plus typed confirmation.

This is a **net-new interaction** (a gated, evidence-bearing control that refuses to be operated), so it carries a UX-research component: a short structured walkthrough with the Owner persona (`docs/plan/10-personas.md`) to establish what evidence the Owner actually needs to feel entitled to flip the switch.

Design must be Done by end of Sprint 18 so that E43-S01 (Sprint 20) satisfies the design-ahead rule in `docs/plan/02-definition-of-ready-done.md` section 3.1.

## Scope / Deliverables
- **UX research note** (1-2 pages): 3 structured questions to the Owner persona - what evidence is required before enabling live, what "outstanding" must say to be actionable, what the emergency re-disable must feel like. Findings recorded in the ticket and reflected in the wireframes.
- **Wireframes then hi-fi in Figma** for SCR-137 covering all three states (`compliant`, `findings outstanding`, `Live enablement blocked`), plus: loading, partially-stale (one check's result older than its schedule), and check-failed-to-run.
- **Finding categories drawn** exactly as SCR-137's sign-off checklist demands: keys without allowlist, overdue rotations, users without 2FA, stale sessions, failed-login spikes, permission anomalies, withdrawal permission detected.
- **Severity as text**, never colour alone; remediation action per finding as a named button; dismiss-with-reason path; all-clear state; last-scan timestamp with freshness.
- **Live-enablement gate block**: the four gate items from `docs/plan/07-release-and-prr.md` section 6 rendered as machine-checked vs attested rows, each showing evidence, attester and date; disabled-control treatment that explains *why* rather than merely greying out; the step-up + typed-confirmation enable dialog (CMP-043 Dialog, CMP-093 AuditActionTrigger); the **emergency re-disable** path and its consequence copy ("no new live orders are accepted; existing positions remain manageable in reduce-only mode").
- Gate-blocked states of the two hosting surfaces: **SCR-010 App shell** live badge and **SCR-074 Environment switcher** (Live option present but unselectable with the reason inline).
- Components used: CMP-028 Callout/Banner, CMP-036 KeyValueRow, CMP-050 Card, CMP-087 AdminLayout, CMP-093 AuditActionTrigger, CMP-175 KeyPermissionBadge, CMP-178 SystemHealthTile, CMP-043 Dialog.
- Redline/spec page with tokens, spacing, type ramp and motion notes (severity escalation must not animate distractingly; reduced-motion honoured).

## Out of scope
- SCR-128 and SCR-136 (E43-D02); the a11y review and design QA (E43-D03); any implementation.
- The environment-separation visual language (live-mode colour, badge, confirm-on-every-order) - that is **E44**'s design.
- Mobile/Android layouts - out of scope for the plan.

## Acceptance criteria
```gherkin
Scenario: Blocked gate explains itself
  Given at least one Live-enablement gate item is outstanding
  When the Owner views the hi-fi SCR-137 gate block
  Then each outstanding item is named with what is missing and what action resolves it
  And the enable control is rendered disabled with the reason adjacent to it, not only as a tooltip

Scenario: No colour-only severity
  Given a design reviewer inspects any finding row in greyscale
  Then the severity, the affected object and the remediation action are all readable as text

Scenario: Machine-evaluated, not a checklist
  Given the Owner views the posture section
  Then every check displays its own last-evaluated timestamp and its source, and no check is presented as something the Owner ticks manually
  And attested (non-machine-checkable) items are visually distinct and show the attester name and date

Scenario: Emergency re-disable is reachable and unambiguous
  Given Live is enabled
  Then the design shows a re-disable control with copy stating that new live orders stop while open positions stay manageable in reduce-only mode
```

## Technical notes / design
- Data source: `GET /api/v1/admin/security/summary` returning the `SecuritySummary` schema (`docs/plan/22-api-openapi.yaml`): key ages and expiry, IP-whitelist drift, withdrawal-permission verification results, failed-login and denied-request counts, MFA enrolment coverage, last audit-chain verification. **The schema never includes secret material** - the design must not invent a field that would require it.
- Findings are computed server-side on a schedule and cached; a manual re-scan is an explicit action with progress, never an automatic refresh (SCR-137 performance note) - the design needs an in-progress treatment for re-scan.
- Audit events the design must visibly account for: `security.centre_viewed`, `security.rescan_requested` (analytics) and `security.finding_dismissed {findingId, reason}` (audited) - the dismiss dialog must collect a reason.

## Test plan
Design-stage verification only: greyscale review; Figma prototype walkthrough of blocked -> attested -> enabled -> re-disabled; contrast check of all tokens used; a state-matrix review against SCR-137's documented states; a copy review confirming no screen renders secret material.

## Security notes
Threats from `docs/plan/04-security-program.md` section 5.7 (admin screens): information disclosure through a well-meaning UI, and elevation through a control that looks advisory but is authoritative. Controls the design must express: step-up re-authentication (SR-025) before enabling live, typed confirmation, audited dismissal with a reason. Data classification: metadata about secrets, never secrets. Security review label required - the Security engineer signs off the gate block.

## Accessibility notes
WCAG 2.2 AA (`docs/plan/05-accessibility-standard.md`). Headings per section; each finding states risk, affected object and remediation as a named button; severity conveyed in text; the disabled enable-control must be programmatically described (`aria-describedby` pointing at the reason) rather than merely inert; focus order runs posture -> findings -> gate; the enable dialog traps focus and returns it on close; reduced-motion respected.

## Performance notes
N/A for design output, except that the design must not require per-finding live polling: the specified model is scheduled server-side computation plus an explicit re-scan.

## Observability
Design must leave room for a "last evaluated" line per check and a global "last full scan" timestamp so the observability data has somewhere to land.

## Definition of Done
- [ ] UX research note recorded on the ticket with the Owner's answers.
- [ ] Wireframes and hi-fi published in Figma and linked here; all documented states covered.
- [ ] SCR-137's design sign-off acceptance checklist in `docs/plan/14-screens-catalogue.md` fully satisfied, each box ticked in a review comment.
- [ ] Contrast and greyscale checks passed.
- [ ] Sign-off: Chief Design Officer (or delegate) **and** Security engineer, recorded as comments.
- [ ] Status Done by end of Sprint 18 so the design-ahead rule holds for E43-S01.

## Dependencies
- **E42** Admin screens - supplies CMP-087 AdminLayout and the `/admin` routing/chrome this screen lives inside.

## Branch
`design/e43-security-centre` (Figma-linked; no code). PR size guidance: N/A - design artefacts only.

## References
- `docs/plan/14-screens-catalogue.md` SCR-137, SCR-010, SCR-074.
- `docs/plan/11-user-stories.md` US-ADMIN-010, US-ADMIN-012.
- `docs/plan/18-traceability-matrix.md` rows US-ADMIN-010, US-ADMIN-012, SCR-137.
- `docs/plan/15-component-catalogue.md` CMP-028/036/043/050/087/093/175/178.
- `docs/plan/07-release-and-prr.md` section 6; `docs/plan/04-security-program.md` sections 13.5, 14.6.
- `docs/plan/16-design-system-brief.md`, `docs/plan/05-accessibility-standard.md`.""")

t(key="E43-D02", kind="Task",
  title="Hi-fi SCR-128 key health panel and SCR-136 audit event detail hardening states",
  labels=["type/design","area/auth-rbac","priority/p1","design","a11y","security"],
  component="web", sprint="Sprint 18", priority="P1 High", perspective="Product",
  risk="None", estimate=3, parent="E43", blocked_by=["E42","E27"],
  body="""## Context
Two existing admin surfaces gain states in E43 because the posture engine (E43-S02) starts producing verdicts they must display.

**SCR-128 Admin: key health & secrets policy panel** (`docs/plan/14-screens-catalogue.md`) shows key ages against policy, last successful use, failure counts, rate-limit consumption per UID, envelope-encryption status (KEK id, last re-wrap), and the standing statement that secrets are never displayed, exported or logged. E43 adds the *verified-against-Bybit* dimension: the withdrawal-permission verification result and the IP-allowlist drift result now arrive from `SecuritySummary` rather than from app belief - R4 exit criterion 2 in `docs/plan/30-release-roadmap.md` section 8.3 requires the audit record to carry *"the Bybit-reported scopes, not just the app's belief about them"*.

**SCR-136 Admin: audit event detail** gains the integrity dimension: when the hash-chain verification (SR-063) reports a break, the detail view must show the position of the break and state plainly that the record cannot be edited or deleted. SCR-135/SCR-136's sign-off checklist already requires the "integrity failure state designed" box.

## Scope / Deliverables
- **SCR-128 hi-fi additions**: per-key rows carrying withdrawal-permission verdict (verified-off / verified-on / unverifiable, each with the verification timestamp and source), IP-allowlist state incl. **drift** ("allowlist no longer contains the current egress IP" - see OQ-05 in `docs/plan/04-security-program.md` section 16.1a), key age vs the 90-day rotation policy (SR-030 family) with an overdue state, and the `mark as compromised` emergency action with its immediate effect stated (key disabled, orders halted for that account).
- The SCR-128 checklist items must all be drawn: per-key age, permissions, allowlist and rotation-due state; the secrets-at-rest policy statement (where keys live, how they are encrypted, who can read them); the overdue-rotation state; and a copy review proving **no secret material is rendered anywhere**.
- **SCR-136 hi-fi additions**: the hash-chain integrity banner (verified at <timestamp> / **break detected at sequence N**), the "this record cannot be edited or deleted" statement, and before/after diff rendering for a security-relevant change (role change, flag change, key change) with redaction visibly applied.
- **Design-system contributions**: a `VerificationVerdict` variant set for CMP-175 KeyPermissionBadge (`verified-off`, `verified-on`, `unverifiable`, `stale`) and a `severity` text-first variant set for CMP-028 Callout/Banner, both contributed to `packages/ui` documentation with Storybook stories specified.
- Motion spec: verdict changes fade only; no attention-grabbing pulsing on a security screen; reduced-motion honoured.

## Out of scope
- SCR-137 (E43-D01); a11y review and design QA (E43-D03); implementation.
- Key rotation *flow* design (SCR-127, owned by E27); the audit search screen SCR-135 list layout (owned by E42).

## Acceptance criteria
```gherkin
Scenario: App belief and exchange truth are visually distinct
  Given a key whose withdrawal permission has been verified against Bybit
  Then the badge states that the verdict came from the exchange and when
  And a key whose verification has not run, or failed, renders as "unverifiable" rather than as safe

Scenario: Allowlist drift is surfaced, not hidden
  Given the deployment's egress IP is no longer in a key's allowlist
  Then SCR-128 shows a drift state naming the current egress IP and the remediation step

Scenario: Integrity break is unmissable and precise
  Given the audit hash chain fails verification at sequence N
  Then SCR-136 shows a persistent banner naming sequence N as the break position, in text
  And the banner does not offer any control that would mutate the record

Scenario: No secret material anywhere
  Given a copy review of every SCR-128 and SCR-136 state
  Then no state renders an API secret, session token, TOTP seed or KEK material, masked or otherwise
```

## Technical notes / design
- Fields come from `SecuritySummary` (`GET /api/v1/admin/security/summary`) and from `audit_log` / `audit_checkpoints` (`docs/plan/21-database-schema.md`). Verification results are cached server-side for 60 s; the panel never calls the exchange from the browser (SCR-128 performance note; SR-119 forbids any exchange contact from the renderer).
- Audited events this design must accommodate: `admin.secrets_policy_changed {key, before, after}` and `admin.key_marked_compromised` (both high severity), `audit.record_viewed {recordId}` and `audit.record_exported` - reading the audit log is itself audited, so the design must not hide that fact from the user.

## Test plan
Greyscale review; state-matrix review against SCR-128/SCR-136 documented states; contrast checks; Storybook story list agreed with the design-system team; copy review for secret leakage.

## Security notes
Threats: `04-security-program.md` section 5.1 (key material) and section 5.7 (admin screens) - information disclosure through UI, and false assurance (a UI that shows "safe" when the check never ran). Control: `unverifiable` is a first-class state, never collapsed into "ok". SR-069 forbids secrets in audit payloads; the design mirrors that by rendering redaction explicitly.

## Accessibility notes
Table of keys with age, permissions, allowlist state and next-rotation-due date, plus a policy section written as plain sentences; warnings are text with an icon (SCR-128 a11y note). Badges must have accessible names that include the verdict word. The integrity banner is `role="status"` for non-blocking updates and reachable in the tab order.

## Performance notes
N/A (design). The design must not require per-row live polling; the panel is a 60 s server-cached read.

## Observability
Leaves space for "verified at" timestamps per key and "chain verified at" on SCR-136, which back the `cv_audit_chain_verify_status` metric.

## Definition of Done
- [ ] Hi-fi published in Figma and linked; all new states covered.
- [ ] SCR-128 and SCR-136 sign-off checklists in `docs/plan/14-screens-catalogue.md` ticked in a review comment.
- [ ] Design-system contributions accepted by the design-system team with Storybook stories specified in `docs/plan/15-component-catalogue.md` for CMP-175 and CMP-028.
- [ ] Contrast/greyscale checks passed; copy review recorded.
- [ ] Sign-off: CDO delegate + Security engineer.
- [ ] Status Done by end of Sprint 18.

## Dependencies
- **E42** Admin screens (AdminLayout, audit detail base). **E27** Accounts & API-key vault (SCR-128 base panel and key metadata model).

## Branch
`design/e43-key-health-audit-states`. PR size guidance: N/A - design artefacts.

## References
- `docs/plan/14-screens-catalogue.md` SCR-128, SCR-135, SCR-136.
- `docs/plan/11-user-stories.md` US-ADMIN-008, US-ADMIN-009, US-ADMIN-010, US-ACCT-003, US-ACCT-005.
- `docs/plan/04-security-program.md` sections 6.1, 6.2, 6.8, 16.1a (OQ-05).
- `docs/plan/21-database-schema.md` `api_keys`, `api_key_rotations`, `audit_log`, `audit_checkpoints`.
- `docs/plan/15-component-catalogue.md` CMP-028, CMP-034, CMP-036, CMP-049, CMP-068, CMP-173, CMP-175, CMP-178.""")

t(key="E43-D03", kind="Task",
  title="Accessibility review, design QA and handoff for E43 security surfaces",
  labels=["type/design","area/auth-rbac","priority/p1","design","design-qa","handoff","a11y"],
  component="web", sprint="Sprint 19", priority="P1 High", perspective="Product",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-D01","E43-D02"],
  body="""## Context
`docs/plan/02-definition-of-ready-done.md` section 3.2 makes `design-qa` default-on for net-new UI and makes a11y default-on for every UI surface including RBAC-gated admin screens - "there is no 'internal tool, a11y doesn't matter' exception". E43 ships or changes three admin surfaces (SCR-137, SCR-128, SCR-136) plus two host-surface states (SCR-010, SCR-074). This ticket closes the design phase: an accessibility review of the hi-fi, a formal handoff package to engineering, and the design-QA pass performed against the built screens in Sprint 20/21.

It is scheduled in Sprint 19 for the review + handoff halves so E43-S01/S02 start Sprint 20 with a signed-off, annotated spec; the design-QA half executes against the build before E43-X07's evidence pack closes.

## Scope / Deliverables
- **Accessibility review** of every state in E43-D01 and E43-D02 against `docs/plan/05-accessibility-standard.md`: contrast ratios for all token pairs used, focus order diagrams, visible focus treatment, keyboard operability of every control including the disabled enable-control and the dismiss-with-reason dialog, screen-reader copy for badges/banners/verdicts, reduced-motion behaviour, and target sizes.
- **Handoff package**: annotated Figma frames with token names (not hex values), spacing/type references to `docs/plan/16-design-system-brief.md`, a per-state data-binding table mapping each rendered field to its `SecuritySummary` / `audit_log` source, an interaction spec for step-up + typed confirmation, and an explicit empty/loading/error/stale matrix per screen.
- **Design-QA pass** (executed once E43-S01/S02 are on staging): built screens compared against spec for spacing, tokens, type, colour and states; discrepancies fixed or filed as Bugs with `priority/*` set and linked here.
- Sign-off record capturing CDO delegate, accessibility specialist and Security engineer.

## Out of scope
- Producing the designs themselves (E43-D01/D02); the automated axe-core audit run (E43-Q05 owns the executed audit); implementation.

## Acceptance criteria
```gherkin
Scenario: Every interactive control is keyboard reachable
  Given the annotated handoff package
  Then every control on SCR-137, SCR-128 and SCR-136 has a defined keyboard path, a visible focus treatment and a documented tab position
  And the disabled Live-enablement control has a documented programmatic description of why it is disabled

Scenario: Contrast passes at AA
  Given every token pair used in the E43 hi-fi
  Then each text/background pair meets WCAG 2.2 AA contrast for its size class, recorded in a table on the ticket

Scenario: Design QA finds nothing unrecorded
  Given the built screens on staging
  When the design-QA pass is executed
  Then every discrepancy is either fixed in the same sprint or filed as a Bug linked to this ticket with a priority label
  And no discrepancy is closed by amending the design retroactively without a recorded decision

Scenario: Handoff is self-sufficient
  Given an engineer who has not attended any design review
  When they open the handoff package
  Then every rendered field names its data source and every state names its trigger condition
```

## Technical notes / design
- Data-binding table must reference real sources only: `SecuritySummary` fields from `docs/plan/22-api-openapi.yaml`, `audit_log` / `audit_checkpoints` columns from `docs/plan/21-database-schema.md`, and feature-flag state from `feature_flags` / `feature_flag_overrides`.
- Screen-reader copy is specified as literal strings so engineering does not improvise accessible names for security verdicts.

## Test plan
- Manual screen-reader script (NVDA + VoiceOver) written here and reused verbatim by E43-Q05.
- Keyboard-only walkthrough script per screen.
- Contrast table computed from the token set.

## Security notes
The handoff must not embed any real credential, real user identity or real audit payload in example frames; use synthetic fixtures with an obvious dummy prefix (mirrors SR-145 for test fixtures). Accessible names must not leak information the visual design deliberately withholds.

## Accessibility notes
This ticket *is* the accessibility work for the epic's design phase: WCAG 2.2 AA across all states, manual screen-reader passes, focus management for dialogs, `role="status"` vs `role="alert"` decisions for verdict and integrity banners, and reduced-motion compliance.

## Performance notes
N/A.

## Observability
N/A.

## Definition of Done
- [ ] Accessibility review recorded with the contrast table and focus-order diagrams.
- [ ] Handoff package published and linked; engineering (E43-S01/S02 owners) confirm it is sufficient in a comment.
- [ ] Design-QA pass executed against staging with pass/fail per screen; discrepancies fixed or filed.
- [ ] Sign-off comments from CDO delegate, accessibility specialist and Security engineer.
- [ ] Screen-reader scripts handed to QA for E43-Q05.

## Dependencies
- **E43-D01**, **E43-D02** supply the designs being reviewed and handed off.

## Branch
`design/e43-a11y-handoff`. PR size guidance: N/A - artefacts plus any Bug tickets filed.

## References
- `docs/plan/05-accessibility-standard.md`; `docs/plan/16-design-system-brief.md`.
- `docs/plan/02-definition-of-ready-done.md` sections 3.1, 3.2, 8.
- `docs/plan/14-screens-catalogue.md` SCR-137, SCR-128, SCR-136, SCR-010, SCR-074.""")

json.dump(T, io.open(os.path.join(os.path.dirname(__file__), "_e43_part2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("part2", len(T))
