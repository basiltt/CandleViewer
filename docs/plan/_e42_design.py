import json

T = []
def t(key, kind, title, labels, component, sprint, priority, perspective, risk, estimate,
      parent, blocked_by, body):
    T.append(dict(key=key, kind=kind, title=title, labels=labels, component=component,
                  phase="P3 Drawing & Alerts", sprint=sprint, priority=priority,
                  perspective=perspective, risk=risk, estimate=estimate, parent=parent,
                  blocked_by=blocked_by, milestone="R3 Trading on demo", body=body))

DESIGN_DOD = """## Definition of Done
- [ ] Figma file published in the CandleViewer design library with a named page per screen and a version tag.
- [ ] Every state enumerated in Scope is drawn (no "engineer will figure it out" gaps).
- [ ] Every component used maps to a `15-component-catalogue.md` ID; any new or extended component has a design-system entry, tokens and Storybook-ready spec — no ad-hoc one-offs.
- [ ] Copy reviewed: every destructive/consequence string reviewed by the Owner and by Security where it states a guarantee.
- [ ] Contrast and focus-order annotations present on every frame; text alternatives specified for every non-text status.
- [ ] Reviewed and signed off by the Chief Design Officer **and** the frontend lead; sign-off comment recorded on this ticket.
- [ ] Linked from the corresponding `docs/plan/14-screens-catalogue.md` entries; the entry's "Design sign-off acceptance checklist" is fully ticked.
- [ ] Ticket Status=Done at least 2 sprints before the consuming frontend story starts (design-ahead rule, `00-planning-brief.md`).

"""

REFS_D = """## References
- `docs/plan/14-screens-catalogue.md` §10 Admin (SCR-120..149) — each entry's "Design sign-off acceptance checklist" is the acceptance contract for these tickets.
- `docs/plan/15-component-catalogue.md` — CMP-087, CMP-088, CMP-173, CMP-174, CMP-178, CMP-179, CMP-095, CMP-210, CMP-099 and the reused atoms.
- `docs/plan/16-design-system-brief.md` — tokens, theming, density, motion.
- `docs/plan/05-accessibility-standard.md` — WCAG 2.2 AA, focus, contrast, SR expectations.
- `docs/plan/11-user-stories.md` §26 ADMIN (US-ADMIN-001, 002, 007, 008, 009, 011, 013, 014).
- `docs/plan/12-sitemap.md` R-300..R-360; `docs/plan/13-user-flows.md` §4 Manager onboarding by owner (F4).
- `docs/plan/10-personas.md` §7 permission matrix.
- `docs/plan/27-adrs/ADR-0010-auth-and-rbac.md`."""

# ------------------------------------------------------------------ D01
t("E42-D01", "Task",
  "UX research and wireframes for the admin area (SCR-120..149)",
  ["design", "ux-research", "type/design", "area/accounts-admin", "priority/p1", "a11y"],
  "web", "Sprint 14", "P1 High", "Product", "R5 Scope", 8, "E42", ["E09", "E27"],
  """## Context
E42 introduces fifteen new surfaces at once, all of them operated by exactly one person (the owner persona, `docs/plan/10-personas.md`) under two very different moods: calm periodic administration (invite a manager, review flags) and acute incident response (something is wrong, who did it, make it stop). Designing both moods from the same wireframe is the main risk in this epic; the second risk is that "admin" becomes a dumping ground whose information architecture nobody can hold in their head.

There is no prior art to copy: `27-adrs/ADR-0010-auth-and-rbac.md` records that no researched retail product documents fine-grained RBAC for this use case, so the model is bespoke and must be validated against the owner's actual mental model rather than assumed.

This ticket runs the research and produces the low-fidelity wireframe set that D02/D03/D04 render at high fidelity. It is scheduled in Sprint 14, two sprints ahead of the consuming stories in Sprint 16 (`00-planning-brief.md` design-ahead rule).

## Scope / Deliverables
- **Research** (moderated, with the Owner plus the two designated account managers, 3 sessions × 60 min):
  - Mental-model elicitation for roles vs account grants: does the owner think "this person is a manager" or "this person may touch sub_002"? The answer drives whether SCR-122 leads with role or with grants.
  - Incident-response walkthrough: given "a manager placed an order I did not expect", trace the path the owner *wants* to take. Measures whether SCR-135 audit search or SCR-120 admin home is the correct entry point.
  - Danger-confirmation calibration: which of the SR-025 step-up actions feel proportionate and which feel like friction theatre, so that the confirmation ladder (single click / typed confirm / typed confirm + step-up) is assigned deliberately per action rather than uniformly.
  - Capacity comprehension: does "3 of 5 sub-accounts used (20 with Business KYC)" (US-ADMIN-014) read as informative or alarming?
- **Deliverable 1 — research report** `docs/design/research/e42-admin-research.md`: findings, verbatim quotes, the agreed confirmation ladder table (action → gate), and the agreed IA.
- **Deliverable 2 — information architecture** for the `/admin/*` tree reconciled against `12-sitemap.md` R-300..R-360, stating for each route whether it is owned by E42 or merely linked (E27 accounts/keys, E28 profiles/groups, E39 risk, E16 recorder, E44 security/live gate).
- **Deliverable 3 — lo-fi wireframes (greyscale, all states)** for: SCR-120 admin home, SCR-121 users list, SCR-122 user detail, SCR-123 invite modal, SCR-124 view-as mode, SCR-135 audit log, SCR-136 audit event detail, SCR-143 system health, SCR-144 incident log, SCR-145 feature flags, SCR-146 backups & restore, SCR-147 exchange connectivity, SCR-148 maintenance mode, SCR-149 admin re-auth gate, SCR-154 permission denied.
- **Deliverable 4 — the danger-pattern inventory**: every destructive or consequential action in the epic with its chosen gate, its exact consequence copy, and its audit event name.

## Out of scope
- Any hi-fi visual design, tokens or motion (D02, D03, D04).
- Screens owned by other epics: SCR-125..SCR-133 (E27/E28), SCR-134/SCR-071..073 (E39), SCR-140..142 (E16), SCR-137 (E44).
- Usability testing of the built product (that is E42-D06 design QA and E42-Q04).

## Acceptance criteria
```gherkin
Scenario: The research answers the IA question, not just collects opinions
  Given three moderated sessions have been run
  When the report is published
  Then it states, as a decision with evidence, whether SCR-122 leads with role or with account grants
  And the admin IA lists every /admin/* route with its owning epic

Scenario: The confirmation ladder is assigned deliberately
  When the danger-pattern inventory is reviewed
  Then every SR-025 action in this epic appears exactly once with a gate (typed confirm, step-up, or both), a consequence sentence and an audit event name
  And Security has commented agreement on the ticket

Scenario: Every state is wireframed, including the ugly ones
  Given the wireframe set is submitted for review
  Then loading, empty, error, degraded, permission-denied, re-auth-expired-mid-task and integrity-failure states exist for the screens that can reach them
  And a reviewer can point at a frame for each state named in the corresponding 14-screens-catalogue.md entry

Scenario: Sessions cannot expose production secrets
  Given research sessions use a seeded demo instance
  Then no real Bybit key material, no real audit rows and no manager PII appear in any recording or artefact
```

## Technical notes / design
- Use the seeded demo instance (`21-database-schema.md` §10 seed data) for all prompts; never a live instance.
- The IA must reflect that `/admin` entry itself is gated by the 15-minute admin re-auth token (R-300) and that individual dangerous mutations need a separate 5-minute step-up token (SR-025) — the wireframes must show **both** clocks, because a user who confuses them will experience the product as broken.
- Wireframes are drawn against the ASCII sketches already in `14-screens-catalogue.md` (SCR-120, SCR-121, SCR-135, SCR-143, SCR-145, SCR-146) — those sketches are the agreed content, not a suggestion; deviations must be justified in the report.
- Density: admin screens use the "comfortable" density from `16-design-system-brief.md`, not the trading "compact" density, because they are used rarely and consequentially.

## Test plan
- Research validity: 3 participants, tasks scripted and identical, sessions recorded with consent, findings coded by two researchers independently and reconciled.
- Wireframe completeness: checklist review against every "Design sign-off acceptance checklist" line in the 15 screen entries; a line without a frame is a defect.
- Peer design critique with the frontend lead to confirm every wireframe is implementable with catalogued components.

## Security notes
Research artefacts may contain PII (participant identity, screen recordings) — classification A-19. Store in the design space with owner-only access, retain 90 days, then delete. No production data, no key material, no real audit exports in any artefact (SR-005). The danger-pattern inventory is a security deliverable: Security engineer review is required before D02/D03/D04 start.

## Accessibility notes
Wireframes must annotate, per screen: heading hierarchy (one `h1` per route via CMP-088), landmark structure (CMP-087 `aria-label="Admin area"`), tab order, the text equivalent of every status/severity/health indicator, and the announcement strategy for asynchronous state changes (flag pushes, health degradation). At least one participant session should be run with the participant's own assistive-technology configuration if available.

## Performance notes
Wireframes must respect the measured budgets so the design does not write cheques engineering cannot cash: SCR-120 ≤800 ms with independently-resolving tiles; SCR-135 cursor pagination at 200 rows/page with a ≤400 ms filter round-trip over 10 M rows (i.e. no design that requires a total count); SCR-121 must not require client-side sorting over the whole user set.

## Observability
N/A for the artefacts themselves. The report must, however, list the analytics events the screens should emit (`admin.overview_viewed`, `security.centre_viewed`, `incident.log_viewed`) so D05 handoff can specify them.

""" + DESIGN_DOD + """## Dependencies
- **E09** defines the actual role/permission vocabulary (`21-database-schema.md` §10.1) and the step-up mechanism; wireframing role editing before that vocabulary exists would invent permissions.
- **E27** defines what account and key metadata exists to bind users to.

## Branch
`design/admin-screens-research` (artefacts live in Figma; the report lands in the repo). PR ≤400 LOC (markdown + images).

""" + REFS_D)

# ------------------------------------------------------------------ D02
t("E42-D02", "Task",
  "Hi-fi design: users list, user detail, invite and view-as (SCR-121..124)",
  ["design", "type/design", "area/accounts-admin", "priority/p1", "a11y"],
  "web", "Sprint 14", "P1 High", "Product", "R5 Scope", 8, "E42", ["E42-D01"],
  """## Context
The user-administration cluster is where delegation is granted and removed. Every consequence in it is social as well as technical: demoting someone, unbinding an account while they hold positions, or watching their screen in read-only impersonation. `04-security-program.md` §5.7 rates the failure modes here as High-to-Critical (D1 hidden-but-callable admin, D5 owner-only actions leaking through shared handlers), and US-ADMIN-002 makes account bindings "the single source of truth for scoping on every API route".

Design's job is to make the consequence of each action legible *before* it is taken — "alex will lose access to 3 accounts" — and to make read-only impersonation unmistakable at every moment it is active.

## Scope / Deliverables
Hi-fi Figma frames, light and dark, comfortable density, for:
- **SCR-121 Admin: users list** (`/admin/users`) — columns username, role, accounts assigned, 2FA state, last login, status; filter bar (role, status) and search; per-row actions (edit, assign accounts, reset password, force 2FA re-enrol, view as, deactivate, delete) with **disabled reasons**; bulk deactivate; sub-account capacity meter with a numeric label (US-ADMIN-014); states: empty (owner only), invite pending, locked (risk lockout from E39), deactivated, capacity reached.
- **SCR-122 Admin: user detail / edit** (`/admin/users/:userId`) — identity, role select, per-account assignment with trade/live toggles and the bound profile name, rule-authoring permission, caps-override section (CMP-138 RiskCapMeter, values clamped to the account profile), active-session list with revoke, 2FA state with force re-enrol, danger zone (deactivate, delete); the **change-summary-before-save** pattern; the "you cannot demote the last owner" guard state; the "granting live on a key inside Bybit's 48 h restriction" warning with the exact unlock time.
- **SCR-123 Admin: invite user** (modal) — username, role, initial account assignments, expiry (default 72 h), the generated link shown **exactly once** with a copy control and the "treat this as a secret" note, the Tailscale ACL reminder, pending-invite list with revoke/resend, expired-invite state, validation messages (`username unique, 3–32 chars, [a-z0-9._-]`; "A manager needs at least one account.").
- **SCR-124 Admin: view-as** — the persistent banner ("Viewing as alex (read-only) — you cannot act. [Exit]") in the main window **and** in every floating Electron window; the mandatory reason field before entry; the 30-minute time box with a visible countdown and auto-exit; "hidden in view-as" placeholders; the write-denied control state (disabled + reason) and the server-refusal state if forced; the target-user notification; the "cannot impersonate another owner" guard.
- **Component specs**: CMP-087 AdminLayout (admin tint, re-auth countdown slot), CMP-088 PageHeader, CMP-105 AccountMultiSelect in its admin configuration, CMP-013 Avatar/ProfileBadge in the view-as banner, CMP-092 DegradedModeBanner reuse for the view-as banner variant.
- **Redlines**: spacing, tokens, focus rings, and the exact copy strings for every consequence and disabled reason.

## Out of scope
- Audit, flags, health, incidents, connectivity, backups, maintenance, re-auth gate, admin home (D03, D04).
- Bybit account/key screens SCR-125..SCR-129 (E27 design tickets).
- Risk-cap policy screen SCR-134 and lockout notice SCR-073 (E39 design).
- Motion specification (D04) and the a11y review pass (D05).

## Acceptance criteria
```gherkin
Scenario: Consequences are stated before the action, not after
  Given the role select on SCR-122 is changed from manager to viewer
  Then the design shows a restated consequence naming the concrete effect ("alex will lose trade access to 3 accounts") before Save is enabled
  And the change-summary frame lists every field that will change with before and after values

Scenario: View-as is unmistakable, including in greyscale
  Given the SCR-124 frames are rendered in greyscale at 100% and at 50% window width
  Then the banner remains the first thing in reading order, remains fully visible, and the Exit control is never clipped
  And a frame exists for the banner inside a floating Electron window

Scenario: Every per-row action has a defined disabled reason
  Given the SCR-121 row menu
  Then each of the seven actions has both an enabled and a disabled frame, and the disabled frame carries a specific reason string, never a bare greyed control

Scenario: The invite link is designed as a one-time secret
  Then the SCR-123 frames show the link exactly once, in a read-only field with a copy control and a secrecy note
  And a separate frame shows the post-dismissal state where the link is no longer retrievable, only revocable and re-issuable

Scenario: The last-owner guard is drawn, not assumed
  Given the owner attempts to demote or deactivate themselves
  Then a guard frame exists explaining why it is refused, with no path that reaches a dead end
```

## Technical notes / design
- Role and status are rendered as **words** plus an optional icon; the `LOCKED` and `invited` states must be distinguishable in greyscale (a11y standard §contrast/colour-independence).
- The caps-override control must visually express clamping: the account profile's ceiling is drawn as the track maximum on CMP-138, so "cannot exceed the account's 3 % daily cap" is visible before the validation message fires.
- The account-assignment control is a labelled multi-select (CMP-105) **plus a reviewable summary list** — the summary is what the user reads before saving; the multi-select is only the input.
- View-as banner reuses CMP-092 DegradedModeBanner's structure but with its own semantic token, because it is a *mode*, not a degradation; the spec must define `color.surface.view-as` in the design system.
- Sessions list rows show device, IP (tailnet address, labelled as such, never confused with the Bybit egress IP) and last-seen; revoke is a named button with a confirmation.

## Test plan
- Design review against every line of the SCR-121/122/123/124 "Design sign-off acceptance checklist" in `14-screens-catalogue.md`.
- Greyscale and 200%-zoom renders of every frame reviewed for information loss.
- Copy review with the Owner for all consequence strings; Security review for the invite-secrecy, impersonation and last-owner strings.
- Implementability review with the frontend lead: every element maps to a catalogued component or has a new design-system entry.

## Security notes
Frames must never depict a secret: no API key material, no password, no TOTP seed, no full invite token in any example frame other than the single designed one-time reveal (SR-005). Impersonation is a High-severity audited capability (`admin.view_as_started|ended`) — the design must make it impossible to be in view-as without knowing it (threat D1/D5 mitigations are partly a design responsibility here). The mandatory reason field exists so the audit row is meaningful. The "cannot impersonate another owner" rule is a designed guard, not an implementation detail.

## Accessibility notes
- One `h1` per route via CMP-088; the users table follows the CMP-049 semantic table contract with a visible caption and column headers.
- The capacity meter carries a numeric text label ("3 of 5 sub-accounts used"), not a bar alone.
- The view-as banner is `role="status"`, first in document order, repeated per window, with a single documented hotkey to exit that is specified here and honoured in the handoff.
- Danger dialogs are `role="alertdialog"` with the consequence rendered as a list; typed confirmation fields have visible labels and format hints.
- Focus order annotated per frame; focus must return to the invoking row action after a modal closes.

## Performance notes
The users list must be designed for cursor pagination and server-side filtering — no design element may require a total count or client-side sort over the whole set (budget: 500 rows without exceeding 4 ms scripting per frame). Permission changes are confirmed in the UI only after the server acknowledges (≤2 s), so an optimistic-success frame must **not** exist; a pending frame must.

## Observability
Specify the analytics/audit events the screens trigger so the handoff can wire them: `user.invited`, `user.updated`, `user.deactivated`, `user.deleted`, `user.role_changed`, `user.assignment_changed`, `admin.view_as_started`, `admin.view_as_ended`.

""" + DESIGN_DOD + """## Dependencies
- **E42-D01** supplies the IA, the confirmation ladder and the lo-fi frames this ticket renders.

## Branch
`design/admin-screens-users` (Figma-primary; repo changes are the screens-catalogue links). PR ≤400 LOC.

""" + REFS_D)

# ------------------------------------------------------------------ D03
t("E42-D03", "Task",
  "Hi-fi design: audit browser, feature flags, health, incidents and connectivity (SCR-135, 136, 143, 144, 145, 147)",
  ["design", "type/design", "area/accounts-admin", "priority/p1", "a11y"],
  "web", "Sprint 15", "P1 High", "Product", "R15 Data lifecycle", 8, "E42", ["E42-D01"],
  """## Context
This is the evidence-and-instrumentation half of the admin area. Two of its screens have unusual design constraints that are easy to get wrong:

- **The audit log must not offer a way to change anything.** `21-database-schema.md` §3.10.1 enforces append-only at the database level (`forbid_mutation` trigger, revoked UPDATE/DELETE grants) and hash-chains every row. The UI's job is to make that guarantee *visible* and to present chain-verification failure as a security incident with a named escalation, not as a red toast.
- **The health screen must keep working while the system it reports on is failing.** `14-screens-catalogue.md` SCR-143 requires every tile to resolve independently, and the roadmap requires the screen to add ≤1 % load to the system it measures.

## Scope / Deliverables
Hi-fi Figma frames, light and dark, comfortable density, for:
- **SCR-135 Admin: audit log** (`/admin/audit`) — columns time, actor, role, action, target, environment, IP, severity, result; CMP-174 AuditFilterBar (actor, action class, target, severity, date range via CMP-047, environment) plus full-text search; CMP-173 AuditRow with an expandable before/after diff rendered as labelled definition lists; the on-page statement of the append-only guarantee; the integrity/verification indicator and the **integrity-failure critical banner** ("Audit chain verification failed at <ts> — contact security"); export via CMP-099 PrintExportBar with its own audit note; high-severity rows distinguishable without colour; states loading, empty-for-filter, verified, integrity-failure, retention notice.
- **SCR-136 Admin: audit event detail** (drawer, CMP-046) — full field set (actor, role at the time, session, IP, user agent, action, target, before, after, request id, environment, correlation id, result), correlated events by request id, links to the related order/rule/account/user, raw record in a copyable `<pre>` region (CMP-068), and the explicit "this record cannot be edited or deleted" statement.
- **SCR-143 Admin: system health** (`/admin/health`) — CMP-178 tiles for API, WS, Bybit public/private WS and REST, per-account rate-limit budgets, ingest, rule engine, recorder, DB tiers, client FPS; per-tile number-with-units **plus a state word**; per-tile degraded and down frames naming what stops working; historical sparkline (CMP-024) with a table alternative; link to the incident log; the **partially-down** frame where some tiles error and the page still functions.
- **SCR-144 Admin: incident / connectivity log** — table (time, subsystem, severity, message, duration, resolution) with severity as text; filters by subsystem, severity and date; open vs resolved states; derived trading-impact line where available; acknowledge action (audited); export; empty state; long messages expanding into a detail row rather than truncating silently.
- **SCR-145 Admin: feature flags** (`/admin/flags`) — CMP-179 FeatureFlagRow with key, plain-language description of the user-visible effect, scope (global / per-user / per-account), state, last changed by/at; **risky flags grouped, marked and step-up-gated**; the `live_trading_enabled` blocked-by-gate state with its reason and a link to SCR-137; the "turning this off affects N armed rules" acknowledgement frame; "requires reload" indicator with a reload action; per-flag change history; search; the kill-switch flag's distinct treatment; CMP-095 FeatureFlagChip usage guidance.
- **SCR-147 Admin: exchange connectivity & rate limits** — per-account, per-endpoint-class table (REST order, REST query, public WS, private WS) with limit, current usage, window and headroom as numbers with units; the fan-out budget view; throttled and banned states with the exchange's stated recovery time; force-reconnect with confirmation; server-time-skew indicator; usage sparkline with table alternative.
- **Component specs / DS contributions**: CMP-173, CMP-174, CMP-178, CMP-179, CMP-210 HealthChips (top-bar cluster), CMP-095, CMP-099 in their admin configurations; severity and health token scales with contrast proofs.

## Out of scope
- Users/invite/view-as (D02); admin home, re-auth gate, backups, maintenance (D04).
- Motion (D04), a11y review pass and handoff (D05).
- The security centre SCR-137 and the live-enablement gate (E44 design).
- Recorder/storage screens SCR-140..142 (E16 design).

## Acceptance criteria
```gherkin
Scenario: The audit log has no mutation affordance anywhere
  Given every SCR-135 and SCR-136 frame is reviewed
  Then no edit, delete, archive or "correct this entry" control exists in any state, including hover, row menu and detail drawer
  And the append-only guarantee is stated on the page as visible copy

Scenario: Chain-verification failure is designed as a security incident
  Given the verification result is a mismatch
  Then a critical banner states the exact chain position of the break and names the escalation ("contact security"), with the rest of the log still readable and clearly marked as unverified beyond that point

Scenario: Health is legible when the backend is half-down
  Given a frame where ingestion is down, Postgres is slow and Bybit REST returns 5xx
  Then each affected tile shows its own error state with the last-good timestamp and the named features that stop working
  And no tile renders a spinner that would block the others

Scenario: Risky flags are visually and procedurally separated
  Given the SCR-145 frames
  Then flags affecting order routing, risk enforcement or audit are grouped under a labelled section, carry a step-up marker, and each has a plain-language description of its user-visible effect
  And the live_trading_enabled row is drawn in its blocked-by-gate state with the blocking reason and a link to the security centre

Scenario: Nothing in these screens renders a secret
  Given any frame containing a before/after diff or a raw record
  Then secret-valued fields are shown as fingerprints or redaction markers only
```

## Technical notes / design
- Severity scale is fixed by `21-database-schema.md` (`debug|info|warning|error|critical`) and the WS `system` schema; design must use exactly these five words, not a parallel vocabulary.
- The before/after diff is a definition list with explicit "before"/"after" labels (not a colour-only side-by-side), because it is read under stress and may be printed/exported.
- Health tiles bind to the `system` WS topic at 1 Hz (`23-ws-protocol.md` §6.1) and to `GET /api/v1/admin/health`; the design must show a per-tile freshness timestamp so a frozen tile is detectable.
- Rate-limit figures come from the backend's own accounting and exchange response headers — the design must never imply the browser queries Bybit directly.
- Flag rows must express resolution order (user override → role override → percentage rollout → default) when an override is active, so the owner understands why a flag reads ON for one person and OFF for another.
- Export controls state the format (CSV/JSON/NDJSON) and that the export is itself audited and signed.

## Test plan
- Checklist review against the "Design sign-off acceptance checklist" of SCR-135, SCR-136, SCR-143, SCR-144, SCR-145 and SCR-147.
- Greyscale renders to prove severity/health/state are never colour-only.
- Stress frames reviewed: 10 M-row filter result, 0-row filter result, all-tiles-down, flag store unavailable.
- Contrast audit of the severity and health token scales against WCAG 2.2 AA (3:1 non-text, 4.5:1 text).

## Security notes
Threat **D3** (audit viewer exposes raw payloads to a viewer) is mitigated partly in design: the frames must specify which fields are owner-only and how the viewer/manager projection differs, so engineering implements two projections rather than one template with a hidden CSS class. Threat **D2** (flag console used to enable live trading) is mitigated by the grouped/step-up-marked risky-flag section and the blocked-gate state. No frame may depict a secret value (SR-005); diffs show fingerprints. Export (`audit.exported`) and acknowledgement (`incident.acknowledged`) are audited actions and must be designed as deliberate, confirmed actions.

## Accessibility notes
- Tables use real table semantics with captions and headers (CMP-049 contract); severity, health state and result are words.
- Health tiles are labelled rows/regions; no reliance on dot colour; sparklines have a table alternative reachable by keyboard.
- The integrity-failure banner is `role="alert"`; routine state changes on health tiles are polite live regions and must not spam a screen reader at 1 Hz — the design specifies a coalescing announcement rule (announce transitions only).
- The audit diff region is an expandable disclosure with a programmatic label naming the row it belongs to.
- Filter controls are labelled; the date-range picker (CMP-047) must be fully keyboard-operable with a typed-date alternative.

## Performance notes
Design must fit: audit filter round-trip ≤400 ms over 10 M rows with 200-row cursor pages (no total counts, no infinite scroll that accumulates DOM without recycling); audit single-record fetch ≤300 ms with a lazily expanded raw payload; health page ≤2 ms scripting per frame at 1 Hz and ≤1 % added system load; incident log 10k rows scrolling without exceeding 8 ms scripting per frame; flag propagation ≤2 s.

## Observability
Events to specify in the handoff: `audit.viewed`, `audit.exported`, `audit.record_viewed`, `audit.record_exported`, `flag.changed`, `incident.log_viewed`, `incident.exported`, `incident.acknowledged`, `connectivity.panel_viewed`, `connectivity.budget_changed`, `connectivity.reconnect_forced`, `health.diagnostics_exported`.

""" + DESIGN_DOD + """## Dependencies
- **E42-D01** IA, lo-fi frames and the danger-pattern inventory.

## Branch
`design/admin-screens-audit-health`. PR ≤400 LOC.

""" + REFS_D)

# ------------------------------------------------------------------ D04
t("E42-D04", "Task",
  "Hi-fi design: admin home, re-auth gate, backups, maintenance mode and 403 + motion spec (SCR-120, 146, 148, 149, 154)",
  ["design", "type/design", "area/accounts-admin", "priority/p2", "a11y"],
  "web", "Sprint 15", "P2 Medium", "Product", "R5 Scope", 5, "E42", ["E42-D01"],
  """## Context
The remaining admin surfaces are the frame around the rest: the landing page that tells the owner where to look, the gate that makes entering admin a deliberate act, the two most destructive operations in the product (restore and maintenance mode), and the refusal screen a non-owner sees. This ticket also owns the **motion specification** for the whole epic, because admin motion has a specific job: it must signal state transitions (elevation granted, flag applied, restore progressing) without ever animating a danger confirmation into feeling routine.

## Scope / Deliverables
Hi-fi Figma frames, light and dark, comfortable density, for:
- **SCR-120 Admin home / overview** (`/admin`) — linked card regions for users, accounts (with keys needing rotation), profiles, recorder, storage, health, flags, backups and audit, each with the number that matters, a per-card loading/error/degraded state, and an "Attention:" text-prefixed warning with a direct action link; the visual distinction of the admin area from the trading app; the re-auth freshness indicator in the chrome; the non-owner hard-404 outcome documented.
- **SCR-149 Admin re-authentication gate** — `role="alertdialog"` explaining why re-auth is required and the resulting token's validity window; password (CMP-201) + TOTP (CMP-204) with a visible label and format hint; the countdown/freshness indicator in the admin chrome; the **expiry-during-an-admin-edit** case (form content preserved, save held, re-auth inline, save resumes); failure and lockout states; cancel returns to the non-admin app rather than a dead end.
- **SCR-146 Admin: backups & restore** (`/admin/backups`) — schedule and retention summary; backup list with timestamp, scope (Postgres OMS/rules/audit/config, QuestDB snapshot, Parquet sync), size, integrity result; "back up now" with progress; the **restore wizard** as a stepper (choose backup → impact preview → typed confirm + step-up → progress → verification → summary); the explicit statement of what a restore does and does not recover ("market history is not restored from these backups"; "a restore does not change anything on Bybit"); the open-positions acknowledgement; failed-backup and failed-verification states; last-successful-backup age warning; the audited, step-up-gated download with its handling warning.
- **SCR-148 Admin: maintenance mode** — entry and exit flows each with their own confirmation; the exact consequence list ("New orders are blocked. Running algos are cancelled. Recording continues. Native exchange stops remain active. Managers see a maintenance notice."); scheduled-window option with advance notice; the manager/viewer-facing maintenance notice; open positions and their protection stated explicitly; typed confirmation and step-up gate.
- **SCR-154 Permission denied (403)** — what happened, what to do, who to ask; no leakage of the existence or shape of the denied resource beyond what the user already knows.
- **Motion specification** for the whole E42 surface: elevation-granted transition, flag-applied push, tile state change on SCR-143, restore progress, banner entry/exit for view-as and maintenance; durations, easing and the `prefers-reduced-motion` behaviour for each; the rule that **no danger confirmation is animated in a way that shortens deliberation**.
- **Design-system contributions**: `color.surface.admin-tint` and the admin chrome treatment, the re-auth countdown pattern (extending CMP-035), severity/health token proofs shared with D03, and the CMP-087 AdminLayout spec finalisation.

## Out of scope
- Users/invite/view-as (D02); audit/flags/health/incidents/connectivity (D03).
- The security centre SCR-137 and live-enablement gating (E44).
- The a11y review pass and engineering handoff pack (D05); design QA of the built result (D06).

## Acceptance criteria
```gherkin
Scenario: Admin re-auth never destroys work in progress
  Given the owner is mid-edit on SCR-122 and the 15-minute admin token expires
  When they attempt to save
  Then a frame exists showing the form content preserved, the save held, re-authentication presented inline, and the save resuming afterwards
  And no frame shows the edit being discarded

Scenario: Restore states what it does not do
  Given the restore wizard impact-preview step
  Then the copy explicitly states that trading is halted during restore, that nothing on Bybit is changed, and that market history is not recovered from these backups
  And the open-positions acknowledgement frame exists

Scenario: Maintenance mode lists consequences as facts
  Given the maintenance entry dialog
  Then the consequences are a list of concrete statements including what remains protected (native exchange stops)
  And both the owner-facing dialog and the manager-facing notice are drawn

Scenario: Motion never rushes a dangerous decision
  Given the motion spec
  Then every danger confirmation has either no entry animation or an entry animation that does not enable the confirm control before it completes
  And each specified motion has a prefers-reduced-motion alternative

Scenario: The admin area is recognisably not the trading app
  Given SCR-120 rendered beside a trading workspace screenshot
  Then the chrome, surface tint and density differ in a way that survives greyscale
```

## Technical notes / design
- Two clocks again: the 15-minute admin-area token (SCR-149, `12-sitemap.md` R-300) and the 5-minute per-action step-up (SR-025). The chrome shows the former; the latter appears as a modal at the moment of action. The design must make it obvious which one just expired.
- The restore wizard's step-up and typed confirmation come at step 3, *after* the impact preview — the user must see the consequence before being asked to type.
- Backup download is high-severity and audited (`backup.downloaded`) because the artefact contains encrypted secrets; the design states the handling obligation.
- SCR-120 card data comes from a single `GET /api/v1/admin/overview` plus the `system` topic for live tiles; each card owns its own loading and error state and never blocks a sibling.
- 403 copy must be identical regardless of whether the resource exists, to avoid an existence oracle.

## Test plan
- Checklist review against the "Design sign-off acceptance checklist" of SCR-120, SCR-146, SCR-148, SCR-149 (and the SCR-154 entry).
- Motion spec reviewed by the motion lead and validated with `prefers-reduced-motion: reduce` variants for every specified transition.
- Greyscale and 200%-zoom passes; admin-vs-trading distinction validated in greyscale.
- Copy review by Owner and Security for the restore, maintenance and 403 strings.

## Security notes
The restore path is the most destructive in the product: it is owner-only, step-up-gated and audited (`backup.restored`, high severity) per `22-api-openapi.yaml` `/admin/backups/{backupId}/restore`. Downloading a backup exposes encrypted secret material (asset A-03/A-08) — the design must warn about handling and must never offer a decrypted view. The 403 screen must not leak resource existence. The re-auth gate's failure path must not distinguish "wrong password" from "wrong TOTP" in a way that aids enumeration; failure copy is generic and announced assertively.

## Accessibility notes
- SCR-149 is `role="alertdialog"` with focus moved to the explanation, then to the password field; failures announced assertively; the TOTP field has a visible label, autocomplete hint and format hint.
- The restore wizard is a stepper with programmatic step state and text percentages on progress (never a bar alone).
- Maintenance entry is `role="alertdialog"`; consequences are a real list; typed confirmation has a visible label stating exactly what to type.
- SCR-120 cards are linked regions with headings; "Attention:" is text-prefixed, not colour-signalled.
- Every specified motion has a reduced-motion alternative; no essential information is conveyed by motion alone.

## Performance notes
SCR-120 renders ≤800 ms with independently resolving tiles and must not block on the slowest subsystem. Re-auth token issue ≤400 ms. Maintenance mode blocks order acceptance server-side within 200 ms and broadcasts the notice to all sessions within 2 s — the design must show a pending state for that window rather than claiming success immediately. Backups run server-side; the screen reports job state and never performs work in the browser.

## Observability
Events for handoff: `admin.overview_viewed` (analytics), `admin.area_entered` (audited, with `{route, reauthTokenAge}`), `admin.session_elevated`, `backup.run|verified|restored|downloaded`, `maintenance.enabled|disabled`.

""" + DESIGN_DOD + """## Dependencies
- **E42-D01** IA, lo-fi frames and the confirmation ladder.

## Branch
`design/admin-screens-shell-ops`. PR ≤400 LOC.

""" + REFS_D)

# ------------------------------------------------------------------ D05
t("E42-D05", "Task",
  "Accessibility design review and engineering handoff pack for the admin area",
  ["design", "handoff", "a11y", "type/design", "area/accounts-admin", "priority/p1"],
  "web", "Sprint 15", "P1 High", "Product", "R5 Scope", 5, "E42", ["E42-D02", "E42-D03", "E42-D04"],
  """## Context
Fifteen screens designed by three parallel tickets will not be consistent by accident, and the design-ahead rule means engineering starts building them in Sprint 16 from whatever this pack says. This ticket is the single gate between design and implementation: a dedicated accessibility review across the whole set, reconciliation of the three hi-fi packages into one consistent system, and a handoff pack complete enough that a developer never has to ask a question (`02-definition-of-ready-done.md` Story DoR: design ticket Status=Done, states enumerated, components catalogued).

## Scope / Deliverables
- **Accessibility design review** across SCR-120, 121, 122, 123, 124, 135, 136, 143, 144, 145, 146, 147, 148, 149, 154, producing a findings list with severity and a resolution per finding (fixed in the Figma file, or an accepted deviation with the CDO's and the accessibility lead's recorded agreement):
  - Heading hierarchy and landmark structure per route (one `h1` via CMP-088; CMP-087 `aria-label="Admin area"`).
  - Keyboard operability of every control, including the date-range picker, the account multi-select, the row-action menus, the stepper and the expandable audit diff; documented tab order per screen; no keyboard trap.
  - Screen-reader semantics: table semantics on every table, live-region strategy for the 1 Hz health tiles (announce transitions only, never every sample), `role="status"` for the view-as banner, `role="alert"` for integrity failure, `role="alertdialog"` for danger dialogs.
  - Colour independence: status, role, severity, health, result and flag state are words in every frame; greyscale proof attached.
  - Contrast audit of all new tokens (admin tint, severity scale, health scale) at AA (4.5:1 text, 3:1 non-text) in both themes.
  - Focus visibility and focus return after every modal/drawer/menu.
  - Reduced-motion variants for every motion in the D04 spec.
  - Target size and spacing for the row-action menus at comfortable density.
- **Consistency reconciliation**: one danger-pattern implementation across the epic (single typed-confirm component behaviour, single step-up modal behaviour), one severity vocabulary, one empty-state pattern, one error-state pattern, one pagination pattern.
- **Engineering handoff pack** (`docs/design/handoff/e42-admin.md` + Figma dev-mode links) containing, per screen: route, the exact API calls and WS topics it binds to, every state with its trigger and its copy, the component ID for every element, redlines/tokens, the audit and analytics events it must emit, the disabled reasons, the validation rules and messages, the keyboard map, and the performance budget it must meet.
- **Design-system contributions merged**: CMP-087, CMP-173, CMP-174, CMP-178, CMP-179, CMP-210, CMP-095, CMP-099 admin configurations and `color.surface.admin-tint` accepted into the library with Storybook-ready specs.

## Out of scope
- Producing new screen designs (D02/D03/D04 own those; this ticket may only amend them to resolve findings).
- Automated axe-core runs against built code and the manual screen-reader pass on the implementation (E42-Q04).
- Design QA of the built screens (E42-D06).

## Acceptance criteria
```gherkin
Scenario: Every screen has a recorded a11y verdict
  Given the review is complete
  Then each of the 15 screens has a pass verdict or a findings list, and every finding has a resolution or a recorded accepted deviation with the accessibility lead's agreement

Scenario: The handoff pack is self-sufficient
  Given a frontend developer who has not attended any design session
  When they are given the pack and asked to build SCR-135
  Then they can identify the route, the endpoints, every state and its trigger, every component ID, the audit events, the keyboard map and the performance budget without asking a question
  And this is validated by an actual dry-run walkthrough with a developer who did not attend, recorded on the ticket

Scenario: One danger pattern, not three
  Given the typed-confirm and step-up interactions across SCR-122, SCR-123, SCR-145, SCR-146 and SCR-148
  Then all use the same component behaviour, the same focus handling and the same copy structure
  And any deviation is documented with its reason

Scenario: Contrast is proven, not asserted
  Then a contrast report lists every new token pair with its measured ratio in both themes, and no pair used for text is below 4.5:1 or for non-text below 3:1

Scenario: Health announcements do not flood assistive technology
  Given the SCR-143 live-region strategy
  Then the specification announces state transitions only, with a documented coalescing window, and this is stated in the handoff pack
```

## Technical notes / design
- The handoff pack is the artefact the Story DoR checks against; it must name, per screen, the `14-screens-catalogue.md` entry it satisfies so traceability is mechanical.
- Specify the two elevation clocks explicitly for engineering: admin-area token (15 min, `admin.area_entered`) and step-up token (5 min, SR-025), including what the UI does when each expires mid-task.
- Specify the projection difference for audit rows between owner and viewer/manager so engineering builds two server projections rather than client-side hiding (threat D3).
- Specify that all admin route gating in the client is a UX affordance only and that the server is the control (SR-017) — the pack must not describe any client-side check as security.

## Test plan
- Review executed against the `05-accessibility-standard.md` checklist, screen by screen, with results recorded per screen.
- Keyboard-only walkthrough of every flow performed on the prototype.
- Screen-reader walkthrough of the prototype with NVDA (Windows) and VoiceOver, covering the view-as banner, the integrity-failure alert, the restore stepper and the re-auth gate.
- Handoff dry-run with a developer who did not attend the design work (acceptance criterion 2).
- Contrast report generated with a token-level tool and attached.

## Security notes
The pack must reproduce, verbatim, the security-relevant copy agreed in D02/D03/D04 (invite secrecy, impersonation notice, restore consequences, maintenance consequences, audit immutability, 403 non-disclosure). It must state SR-005 (no secret is ever rendered, diffs show fingerprints), SR-017 (server-side gate), SR-025 (step-up list) and SR-026 (self-service vs administrative routes are distinct) as build constraints, so a developer cannot implement a shortcut in good faith. Security engineer review of the pack is required before sign-off.

## Accessibility notes
This ticket *is* the accessibility deliverable for the design phase; its output feeds E42-Q04's audit of the implementation. Any accepted deviation must include the reason, the affected user group, and the compensating behaviour.

## Performance notes
The pack carries the per-screen budget so engineering builds to it from day one: SCR-120 ≤800 ms; SCR-135 ≤400 ms filter round-trip at 200 rows/page over 10 M rows; SCR-136 ≤300 ms; SCR-143 ≤2 ms scripting/frame at 1 Hz, ≤1 % added load; SCR-144 10k rows ≤8 ms scripting/frame; SCR-121 500 rows ≤4 ms scripting/frame; flag push ≤2 s; permission change visible to the target session ≤2 s; invite ≤500 ms; re-auth ≤400 ms.

## Observability
The pack lists, per screen, the audit events (`admin.area_entered`, `admin.session_elevated`, `users.*`, `roles.*`, `user.assignment_changed`, `flags.change`, `audit.viewed`, `audit.exported`, `admin.view_as_started|ended`, `maintenance.enabled|disabled`, `backup.*`, `health.diagnostics_exported`, `incident.acknowledged`, `connectivity.*`) and the analytics events, so instrumentation is not retrofitted.

""" + DESIGN_DOD + """## Dependencies
- **E42-D02**, **E42-D03**, **E42-D04** — the three hi-fi packages this ticket reviews, reconciles and packages.

## Branch
`design/admin-screens-handoff`. PR ≤400 LOC (markdown pack + contrast report).

""" + REFS_D)

# ------------------------------------------------------------------ D06
t("E42-D06", "Task",
  "Design QA of the built admin screens against the handoff pack",
  ["design", "design-qa", "a11y", "type/design", "area/accounts-admin", "priority/p2"],
  "web", "Sprint 17", "P2 Medium", "Product", "R5 Scope", 3, "E42",
  ["E42-D05", "E42-S01", "E42-S02", "E42-S03", "E42-S04", "E42-S05", "E42-S06", "E42-S07"],
  """## Context
Design sign-off on a Figma file is a promise; design QA on the running build is the verification. `02-definition-of-ready-done.md` requires design sign-off as a Done condition for UI stories, and the roadmap's R3 design gate (§7.4) names design QA on confirmation and danger states explicitly. Admin screens are used rarely and under pressure, so drift that would be harmless on a trading pane — a missing disabled reason, a consequence sentence quietly shortened, a status rendered as a colour dot — is exactly the kind of drift that costs an owner a bad decision here.

## Scope / Deliverables
- A screen-by-screen comparison of the implemented build against `docs/design/handoff/e42-admin.md` and the Figma source of truth for: SCR-120, SCR-121, SCR-122, SCR-123, SCR-124, SCR-135, SCR-136, SCR-143, SCR-144, SCR-145, SCR-146, SCR-147, SCR-148, SCR-149, SCR-154.
- Verification of **every enumerated state**, driven with seeded fixtures and fault injection, not just the happy path: loading, empty, filtered-to-nothing, error, degraded/partially-down health, integrity failure, invite pending/expired, locked, deactivated, capacity reached, re-auth expired mid-edit, flag blocked by gate, restore failure, maintenance active, 403.
- Verification of the **danger patterns**: every typed confirmation, every step-up prompt, every consequence string reproduced verbatim; focus handling and focus return; no animation that enables confirmation before deliberation.
- Verification of the **view-as** banner in the main window and in a floating Electron window, in greyscale, at 50 % width and at 200 % zoom.
- Token/redline audit: spacing, type scale, admin tint, severity and health scales, focus rings, in both themes.
- A defect list filed as Bugs against the owning stories with severity, screenshot, expected-vs-actual, and the handoff-pack line violated; blocking defects identified explicitly.
- A final design sign-off comment on E42 recording pass/fail per screen.

## Out of scope
- Functional/black-box testing (E42-Q01/Q02) and the formal accessibility audit (E42-Q04) — overlaps are handed to those tickets rather than duplicated here.
- Redesigning anything: a finding that the design itself was wrong produces a follow-up design ticket, not an in-place change during QA.
- Screens owned by other epics even when reachable from admin navigation.

## Acceptance criteria
```gherkin
Scenario: Every screen gets an explicit verdict
  When design QA completes
  Then each of the 15 screens has pass or fail recorded with evidence, and no screen is left unassessed

Scenario: States are verified with fixtures, not imagination
  Given the fixture set and fault injection from E42-Q01
  When each enumerated state is driven
  Then a screenshot exists for every state named in the handoff pack, including integrity failure and partially-down health

Scenario: Consequence copy is verbatim
  Given every destructive confirmation in the build
  Then its copy matches the handoff pack word for word, or a defect is filed
  And any intentional wording change carries recorded Owner and Security agreement

Scenario: Blocking defects stop sign-off
  Given a defect that changes the meaning of a consequence, hides a disabled reason, or renders a status as colour alone
  Then it is marked blocking and E42 design sign-off is withheld until it is fixed and re-verified

Scenario: The admin area still reads as distinct from the trading app
  Given the built admin home beside a built trading workspace, in greyscale
  Then the distinction survives, matching the D04 specification
```

## Technical notes / design
- Run against the staging demo environment with the seeded dataset plus the E42-Q01 fixtures (10 M-row audit fixture, tampered-row fixture, degraded-subsystem fixtures, 500-user fixture).
- Use Figma dev-mode inspection for token comparison rather than eyeballing; record measured values in the defect notes.
- Electron floating-window checks must use the actual shell, not a browser tab, because the view-as and maintenance banners have per-window requirements.
- Check both themes and both `prefers-reduced-motion` settings.

## Test plan
- 15 screens × enumerated states, executed from a written script derived from the handoff pack.
- Greyscale pass over every status-bearing screen.
- 200 % zoom and 50 % window-width reflow pass.
- Keyboard-only spot pass on the danger flows (full keyboard/SR coverage belongs to E42-Q04).
- Re-verification pass after fixes, recorded.

## Security notes
Design QA must confirm the security-relevant visual guarantees actually hold in the build: no secret or key material rendered anywhere including audit diffs and raw records (SR-005); the audit log offers no mutation affordance in any state; the view-as banner cannot be scrolled away or hidden in any window; the 403 screen does not leak resource existence; risky flags are grouped and marked. Any failure here is a security defect, filed with the `security` label and routed to E42-X03.

## Accessibility notes
Spot-check focus visibility, focus return after modals, and that every status is a word — full coverage is E42-Q04's, but a colour-only status found here is filed immediately as blocking. Verify reduced-motion variants exist and are honoured.

## Performance notes
Note any perceived regression against the budgets (SCR-120 ≤800 ms, SCR-135 ≤400 ms filter, SCR-143 ≤2 ms scripting/frame) and hand measurement to E42-Q03 rather than measuring here.

## Observability
Confirm the audit/analytics events listed in the handoff pack actually fire for the screens under review, by observing the audit log itself — an admin screen that does not record its own use is a defect (`admin.area_entered`, `audit.viewed`, `flag.changed`).

""" + DESIGN_DOD + """## Dependencies
- **E42-D05** is the specification being verified.
- **E42-S01..S07** are the implementations under review; QA cannot start on a screen before its story is code-complete.

## Branch
`design/admin-screens-design-qa` (defect list + evidence). No production code changes from this ticket.

""" + REFS_D)

json.dump(T, open("__e42_part2.json", "w"), indent=1)
print(len(T), sum(x['estimate'] for x in T))
