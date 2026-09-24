# -*- coding: utf-8 -*-
"""E42 UI stories S01..S07."""
from _e42_lib import t, REF, DOD_ENG, A11Y_ADMIN, PERF_NOTE
from _e42_eng import SEC_ADMIN, OBS_ADMIN

S = []

S.append(t(
    "E42-S01", "Story",
    "Build the admin shell: re-auth gate, admin home and the 403 denied state",
    ["type/feature", "priority/p0", "a11y", "security", "design-qa"],
    "web", "Sprint 16", "P0 Critical", "Development", "None", 5, "E42",
    ["E42-T01", "E42-D05"],
    """## Context
Every other admin screen lives inside this shell, so it ships first. Three surfaces:
- **SCR-149 Admin re-authentication gate** (`docs/plan/14-screens-catalogue.md` §10) — shown on first entry to any `/admin/*` route when the admin token is older than 15 minutes (`docs/plan/12-sitemap.md` R-300). Password + TOTP, explains *why* ("Admin screens need a fresh confirmation"), and on success unlocks admin routes for 15 minutes of activity. Audited as `admin.session_elevated`.
- **SCR-120 Admin home / overview** (`/admin`, R-300) — cards summarising users, accounts, profiles, recorder, health, flags, backups and audit, each with the number that matters and a link. Fed by `GET /api/v1/admin/overview`; must render in ≤800 ms and **never block on the slowest subsystem** — each tile resolves independently with its own loading, error and degraded state.
- **SCR-154 Permission denied (403)** (`14-screens-catalogue.md` §11) — the state a non-admin sees. Per SCR-120's sign-off checklist, non-owner access **hard-404s** at the route level rather than merely hiding controls, and the server refuses regardless (SR-017, threat D1).

The admin area must be *visually distinct* from the trading app so an operator always knows which hat they are wearing, and the re-auth token's remaining validity is visible in the admin chrome so nobody is surprised by a mid-task expiry.

## Scope / Deliverables
- Stories: **US-ADMIN-011** (partial — the health tile roll-up), **US-ADMIN-001** (partial — the users tile), and the shell obligations of **US-ONB-005** referenced by SCR-149.
- Route shell at `/admin` (R-300) using **CMP-087 AdminLayout** (RBAC-gated shell) and **CMP-088 PageHeader**, with the admin-mode chrome treatment and the re-auth countdown indicator.
- **SCR-149**: dialog built from **CMP-043 Dialog**, **CMP-201 PasswordField**, **CMP-204 OtpInput**, **CMP-027 ErrorState / InlineError**, **CMP-001 Button**; `role="alertdialog"`; cancel returns to the non-admin app, never to a dead end; form content preserved and the pending save held if the token expires mid-edit.
- **SCR-120**: tile grid from **CMP-050 Card**, **CMP-178 SystemHealthTile**, **CMP-138 RiskCapMeter**, **CMP-173 AuditRow**, **CMP-210 HealthChips**, each tile an independently-resolving linked region with its own loading/error/degraded state, consuming the per-section `{status, as_of, data|error}` envelope from E42-T01.
- **SCR-154**: **CMP-089 ForbiddenState** plus **CMP-079 RbacGate** for disabled-with-reason affordances.
- `GET /api/v1/admin/overview` and `GET /api/v1/admin/capacity` integration; WS `system` subscription for the live health and flag chips.
- Emission of `admin.overview_viewed` (analytics) and reliance on the server-side `admin.area_entered` audit event.

## Out of scope
- Any individual admin screen's content (users, audit, flags, health, backups) — E42-S02..S07.
- The authentication/TOTP mechanism itself — **E09**; this consumes `POST /api/v1/auth/step-up`.
- Account/key/profile/recorder screens (SCR-125..134, SCR-140..142) — owned by **E27**, **E28** and **E16**; the home tiles only *link* to them.
- The kill-switch control (E39) beyond rendering its current state.

## Acceptance criteria
```gherkin
Scenario: Entering the admin area with a stale token
  Given the owner's admin re-auth token is older than 15 minutes
  When they navigate to /admin
  Then the SCR-149 gate appears as an alertdialog explaining why re-authentication is required and how long the resulting token lasts
  And on successful password plus TOTP entry the admin routes unlock and the chrome shows the remaining validity
  And an audit row with action "admin.session_elevated" is written

Scenario: The overview survives a degraded subsystem
  Given the recorder subsystem is unavailable and Postgres is responding slowly
  When the owner opens /admin
  Then the page renders within 800 ms
  And the recorder tile shows its own error state naming the affected feature and a remediation hint
  And every other tile renders its data independently, with no tile blocked by another

Scenario: A manager cannot reach the admin area
  Given a user holding only the manager role
  When they navigate to /admin directly by URL
  Then the route does not render any admin chrome or data
  And the server returns 403 for every admin API call attempted
  And the denied state explains what is required rather than showing a bare error

Scenario: The token expires mid-edit (edge case)
  Given the owner is part-way through an admin form when the 15-minute token expires
  When they attempt to save
  Then the re-auth gate appears, the form content is preserved, and after successful re-auth the save proceeds
  And no partial write occurred while the token was invalid

Scenario: Keyboard-only and screen-reader operation
  When the admin home and the re-auth gate are operated with the keyboard only
  Then every tile link and every dialog control is reachable in a logical order with a visible focus ring
  And the dialog traps focus, is announced with its reason, and Esc returns focus to the invoking control
  And every tile's warning state is conveyed as text, not by colour alone
```

## Technical notes / design
- The overview consumes the per-section envelope and renders three tile states from `status`: `ok` (data), `degraded` (data plus a caveat and `as_of`), `unavailable` (error, affected features, remediation hint). The tile never invents a zero — an unavailable count renders as "unavailable", never "0", because a false zero on an admin screen is worse than an absent one.
- Token countdown reads `X-Admin-Token-Expires-In` from any admin response (E42-T01) rather than computing locally from a login time; the client clock is not trusted.
- Route guarding: the client guard is a UX affordance only. The comment `// UI hiding is cosmetic; SR-017 server check is the control` belongs next to it, and the E42-X02 matrix test is the proof.
- Live tiles subscribe to the WS `system` topic (implicit subscription, `docs/plan/23-ws-protocol.md` §7) at ≤1 Hz; no tile polls.
- Admin chrome uses the distinct admin theme tokens contributed by E42-D04; the distinction must survive greyscale and high-contrast mode.

## Test plan
- **Unit** (≥80% frontend): tile state mapping from the section envelope incl. the unavailable-is-not-zero rule; countdown formatting and expiry boundary; route-guard redirect logic; dialog focus management.
- **Contract**: MSW handlers generated from `22-api-openapi.yaml` so the UI cannot drift from the schema.
- **Integration (RTL)**: degraded-tile rendering; token-expiry-mid-edit preserving form state; 403 rendering.
- **E2E** (Playwright, web + Electron; suite lands in E42-Q02): stale-token entry → gate → unlock → overview; manager direct-URL attempt; degraded-subsystem overview against a fault-injected backend.
- **a11y**: axe-core on `/admin`, the gate and the 403; one manual NVDA pass.
- **Perf**: overview render ≤800 ms with a healthy backend and with two sources timing out.
- Fixtures: `tests/fixtures/admin/overview_ok.json`, `overview_degraded.json`, `overview_all_down.json`.

""" + SEC_ADMIN + "\n\n" + A11Y_ADMIN + "\n\n" + PERF_NOTE + "\n\n" + OBS_ADMIN + "\n\n" + DOD_ENG + """

## Dependencies
- **E42-T01** — supplies `/admin/overview`, `/admin/capacity`, the elevation middleware, the section envelope and the token-expiry header.
- **E42-D05** — the a11y-reviewed handoff pack covering SCR-120, SCR-149 and SCR-154 must be Status=Done ≥2 sprints before this story starts (design-ahead rule, `02-definition-of-ready-done.md` §3.1).
- **E09** — sessions, TOTP and `POST /auth/step-up`.

## Branch
`feat/admin-screens-shell`. Two PRs: shell + re-auth gate, then the overview tiles.

""" + REF))

S.append(t(
    "E42-S02", "Story",
    "Build the users list, invite flow and sub-account capacity surfacing",
    ["type/feature", "priority/p0", "a11y", "security", "design-qa"],
    "web", "Sprint 16", "P0 Critical", "Development", "None", 5, "E42",
    ["E42-S01", "E42-D05"],
    """## Context
**US-ADMIN-001 User management (Must)** is the reason the admin area exists: the owner controls who can reach a terminal that places real orders. This story delivers **SCR-121 Admin: users list** (`/admin/users`, R-301) and **SCR-123 Admin: invite user** (modal), plus the **US-ADMIN-014 Sub-account capacity awareness (Should)** surfacing that SCR-121 places at the foot of the table.

The user-story acceptance criteria are precise and become the Gherkin below: creating a user with a role leaves them **pending until they redeem their invite**; disabling a user **revokes their sessions within 5 seconds, disarms their rules, and retains their data**; deleting a user **retains their audit and journal history under an anonymised reference, and the deletion itself is audited**.

Two guards are non-negotiable: the owner cannot deactivate or demote themselves, and at least one enabled Owner must always exist (SR-055, threat D6) — both enforced server-side and surfaced as a clear, non-generic message.

## Scope / Deliverables
- Stories: **US-ADMIN-001** (Must), **US-ADMIN-014** (Should), and the invite half of **US-ONB-006**/**US-ADMIN-013** referenced by SCR-123.
- **SCR-121** at `/admin/users` using **CMP-049 Table**, **CMP-055 FilterBar**, **CMP-011 Tag / Chip**, **CMP-013 Avatar / ProfileBadge**, **CMP-001 Button**, **CMP-087 AdminLayout**: columns username, role, accounts assigned, 2FA state, last login, status; filters by role and state; row menu (edit, assign accounts, reset password, force 2FA re-enrol, view as, deactivate, delete); bulk deactivate.
- States: empty (owner only) · invite pending · locked (risk lockout, from E39) · deactivated · capacity reached.
- Sub-account capacity line: "Sub-account capacity: N of M used (20 with Business KYC)" from `GET /api/v1/admin/capacity`, with the assumed tier stated and the tier treated as a **recorded fact, never inferred** (US-ADMIN-014 NFR); at capacity, adding is blocked with an explanation of the Business KYC path and the isolation trade-off of sharing a sub-account; recording Business KYC updates the cap to 20 and is audited.
- **SCR-123** invite modal using **CMP-043 Dialog**, **CMP-040 FormField**, **CMP-009 Select**, **CMP-105 AccountMultiSelect**, **CMP-033 CopyButton**, **CMP-027 ErrorState**: username (unique, 3–32 chars, `[a-z0-9._-]`), role, initial account assignments, expiry (default 72 h), copy-link delivery with no e-mail dependency, and the Tailscale ACL reminder. Manager role requires at least one account assignment. The link is shown **exactly once** and is not retrievable afterwards — only revocable and re-issuable.
- Destructive flows: deleting a user requires typing their username plus step-up and explains what happens to their rules and journal entries (retained, reattributed to "deleted user").
- APIs: `GET /api/v1/users`, `POST /api/v1/users`, `GET /api/v1/admin/capacity`; audit actions `user.invited|updated|deactivated|deleted|role_changed`.

## Out of scope
- User detail, sessions and view-as — **E42-S03**.
- Bybit account and API-key CRUD (SCR-125..129) — **E27**; this screen only counts and links.
- Per-account profile editing (SCR-130..133) — **E28**.
- Risk lockout *mechanics* — **E39**; this screen renders the locked state.
- The invite redemption experience for the invitee — **E09**/onboarding.

## Acceptance criteria
```gherkin
Scenario: Create and assign role
  When the owner invites a user with the role manager and at least one account assignment
  Then the user appears in the list with status "pending" until they redeem their invite
  And the invite link is displayed exactly once with a copy control and a "treat this as a secret" warning
  And the expiry is shown as an absolute time, defaulting to 72 hours
  And an audit row with action "user.invited" is written

Scenario: Disable revokes access quickly and keeps the record
  When the owner disables a user
  Then that user's sessions are revoked within 5 seconds
  And their rules are disarmed
  And their data is retained and their row shows status "deactivated"
  And the action is audited with before and after state

Scenario: Delete retains history under an anonymised reference
  Given the owner has typed the target's username and holds a valid step-up token
  When they delete the user
  Then the confirmation first states that their rules and journal entries are retained and reattributed to "deleted user"
  And after deletion their audit and journal history remains queryable under an anonymised reference
  And the deletion itself is audited

Scenario: Self-demotion and last-owner deletion are refused (failure case)
  When the owner attempts to deactivate or demote themselves
  Then the action is refused with the message "You can't remove your own owner role."
  And when any path would leave zero enabled owners the server returns 409 conflict
  And the refusal is audited

Scenario: At sub-account capacity
  Given the recorded tier is the default and 5 sub-accounts are in use
  Then the capacity line reads 5 of 5 used and names the 20-with-Business-KYC path
  And adding another is blocked with an explanation including the isolation trade-off of sharing a sub-account
  And when Business KYC is recorded the cap becomes 20 and the change is audited

Scenario: A manager requires at least one account (validation)
  When an invite is submitted with role manager and no account assignment
  Then submission is refused inline with "A manager needs at least one account."
  And the error is associated with the account field and announced to screen readers
```

## Technical notes / design
- The invite link is generated server-side and returned once in the creation response; the client must not persist it and must clear it from memory on modal close. No endpoint can re-read it (SCR-123 performance/behaviour note) — only revoke and re-issue.
- Cursor-paginated table; 500 users render with ≤4 ms scripting per frame; last-seen/presence refreshes at ≤0.1 Hz (SCR-121 performance budget).
- Status and role are rendered as **text plus** an optional chip, never colour alone; the capacity meter carries a numeric label.
- Every destructive row action is wrapped in **CMP-093 AuditActionTrigger** so audit emission is structural rather than remembered, and disabled affordances use **CMP-079 RbacGate** to state *why* they are disabled instead of silently greying out.
- Optimistic UI is forbidden for state-changing admin actions: the row updates only after the server acknowledges (SCR-122's rule, applied consistently across the area).

## Test plan
- **Unit** (≥80%): username validation rules; manager-needs-an-account rule; capacity copy generation across default/Business-KYC/at-capacity; typed-confirmation matching; status rendering including the locked and deactivated states.
- **Contract**: MSW from `22-api-openapi.yaml` for `/users` and `/admin/capacity`.
- **Integration (RTL)**: invite happy path with the once-only link; delete flow with typed confirm and step-up challenge; self-demotion refusal; empty state (owner only).
- **E2E** (E42-Q02): invite → redeem → appears active; disable → second session observed to be revoked within 5 s.
- **Perf**: 500-row render measured against the 4 ms/frame budget.
- **a11y**: axe-core on the list and modal; manual NVDA pass over the table and the invite form; verified table semantics with `<th scope>` and a caption.
- Fixtures: `tests/fixtures/admin/users_500.json`, `users_owner_only.json`, `capacity_at_cap.json`.

""" + SEC_ADMIN + "\n\n" + A11Y_ADMIN + "\n\n" + PERF_NOTE + "\n\n" + OBS_ADMIN + "\n\n" + DOD_ENG + """

## Dependencies
- **E42-S01** — the admin shell, elevation chrome and denied state.
- **E42-D05** — handoff pack covering SCR-121 and SCR-123, Done ≥2 sprints ahead.
- **E09** — user CRUD endpoints, session revocation, invite redemption.
- **E39** — supplies the lockout state rendered in the status column.
- **E27** — supplies the sub-account facts behind the capacity line.

## Branch
`feat/admin-screens-users-list`. Two PRs: list + capacity, then the invite modal.

""" + REF))

S.append(t(
    "E42-S03", "Story",
    "Build user detail with role and account binding, session control and view-as",
    ["type/feature", "priority/p0", "a11y", "security", "design-qa"],
    "web", "Sprint 17", "P0 Critical", "Development", "None", 8, "E42",
    ["E42-S02", "E42-D05"],
    """## Context
**US-ADMIN-002 Role assignment and account binding (Must)** makes delegation explicit and enforceable: *"bindings are the single source of truth for scoping on every API route"*. This story delivers **SCR-122 Admin: user detail / edit** (`/admin/users/:userId`, R-302) and **SCR-124 Admin: "view as"** (read-only impersonation) — the two most privilege-sensitive screens in the epic.

SCR-122 carries identity, role, account assignments with per-account trade/read permission, rule-authoring permission, live-trading permission per account, risk-cap overrides, the active session list with revoke, 2FA state, and the user's own audit trail. SCR-124 is a *mode*, not a page: a persistent, unmistakable banner ("Viewing as alex (read-only) — you cannot act. [Exit]"), every write endpoint refused server-side for the duration, time-boxed to 30 minutes, entry and exit audited at high severity, and an absolute prohibition on impersonating another owner.

Threat **D5** (`04-security-program.md` §5.7) is the shape to avoid: owner-only actions reachable through a shared handler. Administrative mutation of *another* user goes through `/users/{userId}/*`; self-service mutation has no `user_id` parameter at all (SR-026).

## Scope / Deliverables
- Stories: **US-ADMIN-002** (Must), **US-ADMIN-003** (Must — the per-manager risk-limit *administration surface*; enforcement is E39/E28), and the impersonation obligations SCR-124 attributes to US-ADMIN-002/008.
- **SCR-122** using **CMP-040 FormField**, **CMP-065 FormSection**, **CMP-009 Select**, **CMP-004 Toggle**, **CMP-105 AccountMultiSelect**, **CMP-138 RiskCapMeter**, **CMP-093 AuditActionTrigger**, **CMP-087 AdminLayout**: sectioned form (identity · role · account assignments · risk caps · sessions · 2FA · danger zone).
- Role change restates its consequence before saving ("alex will lose access to 3 accounts"); a change summary is shown before save.
- Account assignment per account: trade, live, and the profile in force, with the validation that granting *live* on an account whose key is still inside Bybit's 48 h restriction shows a warning with the **exact unlock time**.
- Risk-cap overrides clamped to the account profile's caps, with the specific message "Can't exceed the account's 3 % daily cap."; each limit change is audited with old and new values (US-ADMIN-003 "Audit" scenario, SR-065/threat D4).
- Session list with per-session revoke and a force-logout-all action; 2FA state with force re-enrol.
- Danger zone: deactivate and delete, both step-up gated with typed confirmation and the last-owner guard.
- **SCR-124 view-as**: mandatory reason field before entry; 30-minute time box with a visible countdown and auto-exit; banner as a `role="status"` landmark first in document order and repeated in every floating window; "hidden in view-as" placeholders; write-denied states; target-user notification; cannot-impersonate-another-owner guard.
- APIs: `GET/PATCH /api/v1/users/{userId}`, `PUT /api/v1/users/{userId}/roles`, `PUT /api/v1/users/{userId}/account-access`, `GET /api/v1/auth/sessions`; audit actions `user.assignment_changed`, `roles.grant`, `roles.revoke`, `admin.view_as_started|ended`.

## Out of scope
- Unbinding a user who holds open positions requires an explicit choice (leave positions / flatten first) — the *choice UI* is in scope here, but the flatten execution is **E29/E34**.
- The RBAC policy engine and session storage — **E09**.
- Risk-cap *enforcement* on the order path — **E39**; this is the administration surface only.
- Per-account profile editing — **E28**.

## Acceptance criteria
```gherkin
Scenario: Binding scopes a manager server-side
  When the owner binds manager M to sub-account S and saves
  Then M can see and trade only S, subject to S's profile
  And the change is pushed to M's active session within 2 s
  And the UI confirms only after the server has acknowledged
  And an audit row records the binding with before and after state

Scenario: Multiple bindings appear in scope
  When the owner binds M to a second sub-account
  Then both appear in M's scope selector
  And server-side scoping covers both, verified by an API call from M's session

Scenario: Unbind with open positions requires an explicit choice
  Given M holds open positions on sub-account S
  When the owner removes that binding
  Then the save is held and an explicit choice is required: leave the positions with the owner taking over, or flatten first
  And neither option proceeds without the choice being made
  And the chosen option is recorded in the audit event

Scenario: Risk-limit tightening never force-liquidates
  Given the manager's current exposure exceeds a newly tightened limit
  When the owner saves the tighter limit
  Then no forced liquidation occurs
  And new entries are blocked while reduce-only actions remain available
  And both the owner and the manager are informed
  And the change is audited with old and new values

Scenario: View-as is unmistakable, read-only and time-boxed
  Given the owner enters view-as for manager alex with a stated reason
  Then a persistent banner appears first in document order in every window reading "Viewing as alex, read-only. You cannot act. Exit view-as."
  And a 30-minute countdown is visible and the mode auto-exits at zero
  And every write endpoint is refused server-side for the duration, even if a control is forced
  And entry and exit are audited with high severity and the target user is notified

Scenario: Owner impersonation is refused (failure case)
  When the owner attempts to enter view-as for another owner
  Then entry is refused with a specific message
  And no impersonation session is created
  And the refused attempt is audited

Scenario: Granting live inside the 48-hour key restriction (edge case)
  Given the account's key is still inside Bybit's 48-hour restriction window
  When the owner grants live permission on that account
  Then a warning states the exact unlock time
  And the rest of the form remains saveable
```

## Technical notes / design
- **No optimistic UI.** Permission changes take effect server-side immediately and are pushed to the affected user's session within 2 s; the UI confirms only after the server acknowledges (SCR-122 performance note). A locally-applied permission change that the server rejected would be a security-relevant lie.
- **View-as is a server-side session mode**, not a client filter: the backend issues an impersonation session whose capability set is read-only by construction. The client banner is a courtesy; the refusal is the control. No write-capable control is mounted at any point during the enter/exit transition (SCR-124 performance note) — both transitions are blocking, typically ≤2 s.
- Changes are diffed client-side into a change summary, but the authoritative before/after lands in the audit row from the server's own read-modify-write, so the two cannot disagree.
- Concurrency: `PATCH` carries an `If-Match` ETag; a conflicting concurrent edit returns `precondition_failed` and the UI re-reads and re-presents the diff rather than clobbering.
- The 48-hour key-restriction unlock time comes from E27's key metadata; if unavailable, the warning states that the restriction status is unknown rather than implying it is clear.

## Test plan
- **Unit** (≥80%): change-summary diffing; cap-clamp validation messages; last-owner guard rendering; countdown and auto-exit; banner presence invariant (a render-time assertion that the banner exists whenever the impersonation flag is set); 48 h warning formatting incl. the unknown case.
- **Contract**: MSW from `22-api-openapi.yaml` for the user, roles, account-access and sessions routes.
- **Integration (RTL)**: unbind-with-open-positions choice gate; ETag conflict re-presentation; view-as enter/exit teardown asserting no write control is mounted mid-transition.
- **E2E** (E42-Q02): bind → second browser session as the manager observes the new scope; revoke session → that session is logged out within 5 s; view-as entry → attempt a write → server refusal observed → exit → audit rows present for both transitions.
- **Security** (feeds E42-X02): attempt every write endpoint while in view-as; attempt to impersonate an owner; attempt to grant a role via the self-service endpoint.
- **a11y**: axe-core on the detail page and in view-as mode; manual NVDA pass confirming the banner is announced first and the Exit control is always reachable by its documented hotkey.
- Fixtures: `tests/fixtures/admin/user_manager_multi_account.json`, `user_with_open_positions.json`, `key_within_48h.json`.

""" + SEC_ADMIN + "\n\n" + A11Y_ADMIN + "\n\n" + PERF_NOTE + "\n\n" + OBS_ADMIN + "\n\n" + DOD_ENG + """

## Dependencies
- **E42-S02** — the users list is the entry point and shares the row-action vocabulary.
- **E42-D05** — handoff pack covering SCR-122 and SCR-124, Done ≥2 sprints ahead.
- **E09** — RBAC grants, session listing/revocation, the impersonation session mode.
- **E27** — key metadata for the 48-hour restriction warning.
- **E28/E39** — profile caps that user-level overrides are clamped to.
- **E29** — the flatten action offered by the unbind-with-open-positions choice.

## Branch
`feat/admin-screens-user-detail`. Three PRs: detail form + bindings, sessions + danger zone, view-as mode.

""" + REF))

S.append(t(
    "E42-S04", "Story",
    "Build the audit-log browser, record detail and signed export UI",
    ["type/feature", "priority/p0", "a11y", "security", "perf", "design-qa"],
    "web", "Sprint 17", "P0 Critical", "Development", "R15 Data lifecycle", 5, "E42",
    ["E42-T02", "E42-S01", "E42-D05"],
    """## Context
**US-ADMIN-008 (Must)** and **US-ADMIN-009 (Must)** turn the append-only log into something an investigator can actually use. This story delivers **SCR-135 Admin: audit log** (`/admin/audit`, R-360) and **SCR-136 Admin: audit event detail**.

Three properties must be visible in the UI, not merely true underneath:
1. **Immutability** — the detail view states plainly that the record cannot be edited or deleted, and the screen offers **no mutation affordance at all**.
2. **Integrity** — chain verification is a first-class action; a break is reported with its position and presented as a **security incident**, not a UI error.
3. **Scope** — R-360 makes `/admin/audit` accessible outside the admin hat in reduced form (owners see their own actions; managers see their own actions only), and that scoping is enforced server-side (E42-T02); the UI must never imply it is showing everything when it is not.

Reading the audit log is itself audited (`audit.record_viewed`, `audit.record_exported`) — SCR-136 is explicit that reading the record puts you on the record.

## Scope / Deliverables
- Stories: **US-ADMIN-008** (the browser, verification and immutability surfacing — the writer is E09), **US-ADMIN-009** (search and export).
- **SCR-135** using **CMP-049 Table**, **CMP-174 AuditFilterBar**, **CMP-173 AuditRow**, **CMP-047 DatePicker / DateRangePicker**, **CMP-055 FilterBar**, **CMP-099 PrintExportBar**, **CMP-087 AdminLayout**: filters by actor, action type, account, severity, outcome, IP and time range, plus free text; cursor pagination with stable ordering; a visible "verify chain" action and the slice's `chain_verified` indicator with an explicit caveat that it describes the displayed slice, not the whole table.
- **SCR-136** using **CMP-046 Drawer**, **CMP-036 KeyValueRow**, **CMP-068 CopyableCodeBlock**, **CMP-033 CopyButton**: the full field set (actor, role, action, target, before, after, timestamp, IP, session id, environment, correlation id, result), a before/after **diff rendering** for structured changes, links to the related order/rule/account/user, the raw record in a copyable `<pre>` region, and the statement "this record cannot be edited or deleted".
- Export: step-up challenge → job → progress → download of the signed NDJSON bundle, with the export itself audited and the redaction the caller's role sees preserved in the file.
- Verification failure presentation: an `role="alert"` security-incident banner naming the divergent row id and linking to the security centre, never a toast that can be missed.
- Scope banner for non-owner viewers: "You are seeing only your own actions."
- APIs: `GET /api/v1/admin/audit`, `POST /api/v1/admin/audit/verify`, `POST /api/v1/admin/audit/export`, `GET /api/v1/admin/jobs/{jobId}`.

## Out of scope
- Writing audit rows and the hash chain — **E09**.
- The query/verify/export backend — **E42-T02**.
- The nightly verification job and its alerting — **E04**.
- The security centre screen (SCR-137) — **E43**/security epic; this screen links to it.

## Acceptance criteria
```gherkin
Scenario: Filtered search with stable ordering
  When the owner filters by actor, action type, account, severity and time range
  Then matching entries are listed with cursor pagination and stable ordering
  And the first page returns within 2 s over a 10-million-row log
  And paging forward and back yields the same rows with no duplicates and no gaps

Scenario: Manager scope is stated and enforced
  Given a manager opens the audit screen
  Then a banner states that only their own actions are shown
  And every visible row has them as the actor
  And before and after payloads are redacted
  And the scoping is enforced server-side, verified by a direct API call bypassing the UI

Scenario: Integrity verification reports a break as an incident
  Given the hash chain is broken at a known row
  When the owner runs the integrity check
  Then a security-incident alert names the divergent row id and its position
  And the alert is announced assertively to screen readers
  And it links to the security centre rather than disappearing as a transient toast

Scenario: Export is signed, gated and self-auditing
  When the owner exports the filtered set
  Then a step-up challenge is required before the job starts
  And progress is shown until a signed file is available
  And the export itself appears in the audit log
  And payload redaction matching the caller's role is preserved in the file

Scenario: No mutation affordance exists anywhere (failure case)
  When the audit list and the record detail are inspected for controls
  Then no edit, delete, archive or bulk-modify control exists in any state
  And the detail view states that the record cannot be edited or deleted

Scenario: Empty and over-large results (edge cases)
  When a filter combination matches no rows
  Then an empty state explains which filters are active and offers to clear them
  And when an export would exceed the server's row or size limit
  Then the request is refused with the actual row count and a suggestion to narrow the range
```

## Technical notes / design
- The table is virtualised; rows are plain table semantics with `<th scope>` and a caption, not a div grid, so screen-reader table navigation works over 200-row pages.
- `chain_verified` from the API describes **the returned slice only**; the UI label says so in words. Presenting a slice check as a whole-table guarantee would be a false assurance on a security screen.
- Before/after diff rendering handles three cases: scalar change (old → new), object change (per-key diff), and absent/redacted (a stated reason, never a blank).
- Free-text search hits the `q` implementation chosen in ADR-0022 (E42-K01); the UI debounces at 300 ms and cancels in-flight requests, and shows the active filter set as removable chips so nobody misreads a filtered view as the full log.
- Export polls `GET /admin/jobs/{jobId}` at 1 Hz maximum, with a stated expected duration and a cancel action.

## Test plan
- **Unit** (≥80%): filter-chip state; cursor handling; diff rendering across the three cases; verification-result rendering incl. the break case; export job state machine; empty and refused-export states.
- **Contract**: MSW from `22-api-openapi.yaml` for all four routes.
- **Integration (RTL)**: manager-scope banner and redacted rows; verification failure raising the alert; export step-up challenge flow.
- **E2E** (E42-Q02): search → export → the export appears in the log; tampered-fixture verification surfaces the incident.
- **Perf**: 200-row page render and filter round-trip against the ≤400 ms p95 budget with the backend served from the 1 M-row fixture; virtualised scroll at ≤8 ms scripting per frame.
- **a11y**: axe-core; manual NVDA pass over the table, the filter bar and the detail drawer; assertive announcement of the integrity failure verified.
- Fixtures: `tests/fixtures/audit/page_mixed_severity.json`, `page_redacted_manager.json`, `verify_broken.json`.

""" + SEC_ADMIN + "\n\n" + A11Y_ADMIN + "\n\n" + PERF_NOTE + "\n\n" + OBS_ADMIN + "\n\n" + DOD_ENG + """

## Dependencies
- **E42-T02** — query, verify and export endpoints plus the role-scoped projections.
- **E42-S01** — admin shell.
- **E42-D05** — handoff pack covering SCR-135 and SCR-136, Done ≥2 sprints ahead.

## Branch
`feat/admin-screens-audit-browser`. Two PRs: list + filters + detail, then verification + export.

""" + REF))

S.append(t(
    "E42-S05", "Story",
    "Build the feature-flag console and the maintenance-mode control",
    ["type/feature", "priority/p0", "a11y", "security", "design-qa"],
    "web", "Sprint 17", "P0 Critical", "Development", "None", 5, "E42",
    ["E42-T03", "E42-S01", "E42-D05"],
    """## Context
**US-ADMIN-007 Feature flags (Must)** exists so the owner can shed load or disable a risky feature *without a deployment*. This story delivers **SCR-145 Admin: feature flags** (`/admin/flags`, R-351) and **SCR-148 Admin: maintenance mode** (R-356).

SCR-145's validations are the interesting part: `live_trading_enabled` cannot be turned on until the PRR/pen-test gate is satisfied — the toggle is disabled **with the blocking reason** and a link to SCR-137 — and turning *off* a flag that an armed rule depends on lists the affected rules and requires acknowledgement. Every toggle emits an audit event with before/after and is step-up gated for safety-affecting flags (threat **D2**, SR-025).

SCR-148's consequence list is copy that must be exactly right, because it is what an operator reads at the worst moment: "New orders are blocked. Running algos are cancelled. Recording continues. Managers see a maintenance notice." — plus the explicit statement that **native exchange stops remain active**. Open positions keep their exchange-side protection while the app is in maintenance; saying otherwise, or failing to say it, would be a safety failure.

## Scope / Deliverables
- Stories: **US-ADMIN-007** (Must); the flags-console half of **US-ADMIN-012** (the live-enablement toggle's *blocked* presentation; the gate's criteria are E44); **US-REL-003**/**US-REL-004** as referenced by SCR-145/SCR-148.
- **SCR-145** using **CMP-049 Table**, **CMP-179 FeatureFlagRow**, **CMP-004 Toggle**, **CMP-095 FeatureFlagChip**, **CMP-093 AuditActionTrigger**, **CMP-087 AdminLayout**: flag key, plain-language description of the user-visible effect, state, scope (global / per-user / per-account), last changed by and when; search; per-flag change history; the "requires reload" indicator with a reload action.
- Risky flags (anything affecting order routing, risk enforcement or audit) are **grouped, marked and step-up-gated**; stale flags past `expires_at` are marked as flag debt.
- States: applied · rollout in progress (scoped to users/accounts) · blocked by gate · rollback available.
- Live update: flag changes arrive over the WS `system` topic and apply **without a reload where possible**, within 2 s; flags that require a reload say so and offer the action rather than taking effect silently later.
- **SCR-148** using **CMP-044 ConfirmDialog**, **CMP-028 Callout / Banner**, **CMP-004 Toggle**, **CMP-065 FormSection**, **CMP-093 AuditActionTrigger**: entry and exit flows each with their own confirmation, the exact consequence list, a scheduled-window option with advance notice, the manager/viewer-facing maintenance notice, the open-positions protection statement, step-up gate and typed confirmation; `role="alertdialog"` on entry.
- APIs: `GET /api/v1/admin/feature-flags`, `PUT /api/v1/admin/feature-flags/{flagKey}`; the maintenance endpoints from E42-T03; audit actions `flags.change`, `maintenance.enabled|disabled`.

## Out of scope
- The kill-switch *mechanism* and its global hotkey — **E39**; this console exposes its state and the administrative toggle.
- The live-enablement gate's criteria, attestation and evaluation — **E44**; this screen renders the verdict and the outstanding items.
- Flag resolution, caching and propagation — **E42-T03**.
- The security centre (SCR-137) linked from the blocked live-trading toggle — **E43**.

## Acceptance criteria
```gherkin
Scenario: Toggling a flag takes effect everywhere quickly
  Given a second session is open in another browser
  When the owner disables the liquidation-heat estimate flag
  Then the feature disappears for all users within 10 seconds, and in practice within 2 seconds
  And the change is audited with before and after state
  And the flag row shows who changed it and when

Scenario: Safety flags require step-up
  When the owner toggles a flag controlling live enablement, one-click trading or rule arming
  Then step-up authentication is required before the change is submitted
  And the flag is visually grouped and marked as risky
  And the audit row carries high severity

Scenario: Live enablement is blocked with its reason
  Given the pen-test sign-off or any PRR checklist item is outstanding
  Then the live-trading toggle is disabled and lists exactly which items are outstanding
  And it links to the security centre
  And forcing the change through the API still returns 412 with the outstanding items

Scenario: Disabling a flag an armed rule depends on (edge case)
  Given an armed rule depends on the flag being disabled
  When the owner turns it off
  Then the affected rules are listed by name
  And the change proceeds only after an explicit acknowledgement
  And the acknowledgement is recorded in the audit event

Scenario: Maintenance mode states exactly what it does and does not do
  When the owner enters maintenance mode
  Then an alertdialog lists the consequences: new orders blocked, running algos cancelled, recording continues, managers see a maintenance notice
  And it states explicitly that native exchange stop orders remain active
  And entry requires a typed confirmation and step-up
  And all sessions receive the notice within 2 seconds
  And maintenance.enabled is audited

Scenario: A flag change arrives while the console is open (concurrency)
  Given another admin changes a flag while this console is open
  Then the row updates from the system push without a manual refresh
  And an attempt to submit a stale value is refused with a conflict and the console re-reads the current value
```

## Technical notes / design
- Toggles are labelled with the **flag name**, not "on/off" (SCR-145 a11y requirement), so a screen-reader user hears "node_graph_rule_editor, on" rather than an anonymous switch.
- The console consumes the same `system` topic payload that every other client consumes; there is no admin-only flag channel, which means the console cannot show a state that ordinary clients do not have.
- Stale-value protection uses the `If-Match` ETag from E42-T03; a conflict re-reads and re-presents rather than retrying blindly.
- The blocked live-trading toggle renders `precondition_failed`'s enumerated items directly — the outstanding list is data from the gate, never hard-coded UI copy, so it cannot drift from the real gate.
- Maintenance entry disables the trading chrome app-wide via the same push, so an operator cannot be looking at an actionable ticket while the backend refuses orders.

## Test plan
- **Unit** (≥80%): flag row state rendering across applied/rollout/blocked/rollback; risky-flag grouping; requires-reload affordance; dependent-rule acknowledgement gating; maintenance consequence-list rendering; ETag conflict handling.
- **Contract**: MSW from `22-api-openapi.yaml`; `system` push payloads validated against `cv://ws/v1/system.schema.json`.
- **Integration (RTL)**: push-driven row update; blocked toggle rendering from a `precondition_failed` payload; step-up challenge on a risky flag.
- **E2E** (E42-Q02): toggle a flag in session A and observe the feature disappear in session B within 2 s without a reload; enter maintenance and observe an order attempt refused.
- **a11y**: axe-core; manual NVDA pass over the flags table and the maintenance alertdialog, confirming the consequence list is read before the confirm control.
- **Perf**: propagation measured end-to-end against the 2 s budget.
- Fixtures: `tests/fixtures/flags/console_mixed_kinds.json`, `live_gate_blocked.json`, `dependent_rules.json`.

""" + SEC_ADMIN + "\n\n" + A11Y_ADMIN + "\n\n" + PERF_NOTE + "\n\n" + OBS_ADMIN + "\n\n" + DOD_ENG + """

## Dependencies
- **E42-T03** — flag service, push propagation, maintenance mode, the protected-flag registry.
- **E42-S01** — admin shell.
- **E42-D05** — handoff pack covering SCR-145 and SCR-148, Done ≥2 sprints ahead.
- **E39** — kill-switch state; **E44** — the live-enablement gate verdict.

## Branch
`feat/admin-screens-flags-console`. Two PRs: flags console, then maintenance mode.

""" + REF))

S.append(t(
    "E42-S06", "Story",
    "Build system health, incident log and exchange connectivity screens",
    ["type/feature", "priority/p1", "a11y", "perf", "design-qa"],
    "web", "Sprint 17", "P1 High", "Development", "None", 5, "E42",
    ["E42-T01", "E42-S01", "E42-D05"],
    """## Context
**US-ADMIN-011 System health screen (Must)** exists so the owner can diagnose quickly: WS connection states, ingest rates and lag, rate-limit budget per account, queue depths, database sizes and latency, error rates and process uptime — with drill-down into recent errors and reconnects, and a degraded state that **names the affected features and gives a remediation hint**. Its NFR is unusual and important: *"health data is served from the metrics pipeline, with the screen adding ≤1% load"* — the screen must not become part of the problem it reports on.

This story delivers **SCR-143 Admin: system health** (`/admin/health`, R-350), **SCR-144 Admin: incident / connectivity log**, and **SCR-147 Admin: exchange connectivity & rate limits**.

SCR-147 carries the fan-out arithmetic the owner actually needs before R3's fan-out epic goes live: per-account REST and WS budgets, current consumption, recent `10018` events, per-endpoint weights and a simulator ("a 5-account fan-out with brackets costs ≈ 15 requests — 9% of your minute budget"), plus throttled/banned states with the exchange's stated recovery time, a force-reconnect action and a server-time-skew indicator.

## Scope / Deliverables
- Stories: **US-ADMIN-011** (Must); **US-OBS-003**, **US-OBS-005**, **US-OBS-006** as attributed by SCR-144/SCR-147; **US-ADMIN-014**'s connectivity aspect.
- **SCR-143** using **CMP-178 SystemHealthTile**, **CMP-210 HealthChips**, **CMP-092 DegradedModeBanner**, **CMP-024 Sparkline**, **CMP-036 KeyValueRow**, **CMP-087 AdminLayout**: per-subsystem tiles (API, WS, Bybit, ingestion, book engine, bars, order-flow, OMS, rules, recorder, replay, DB) each with status, key metric and last-updated; drill-down showing recent errors, recent reconnects and the last hour of relevant metrics; degraded state naming the affected features and a remediation hint.
- **SCR-144** using **CMP-049 Table**, **CMP-055 FilterBar**, **CMP-047 DateRangePicker**, **CMP-068 CopyableCodeBlock**: chronological `system_events` (`docs/plan/21-database-schema.md` §3.10.2) — WS disconnects, resubscriptions, sequence gaps, exchange 5xx, `10018` rate-limit hits, engine restarts, recorder gaps — with duration, impact, what the system did automatically, filters by subsystem/severity/date, open vs resolved states, an acknowledge action (audited) and export.
- **SCR-147** using **CMP-023 Progress Bar**, **CMP-024 Sparkline**, **CMP-049 Table**, **CMP-036 KeyValueRow**: per-account, per-endpoint-class (REST order, REST query, public WS, private WS) limit, current usage, window and headroom as numbers with units; the fan-out budget simulator; throttled and banned states with recovery time; force-reconnect with confirmation; server-time-skew indicator; historical usage sparkline **with a table alternative**.
- Data: `GET /api/v1/admin/health`, `GET /api/v1/admin/incidents`, `GET /api/v1/admin/capacity`, and the WS `system` topic for live state (`exchange_state`, `connection_quality` deltas per `docs/plan/23-ws-protocol.md` §9.5).

## Out of scope
- The metrics pipeline, Prometheus exporters and Grafana dashboards — **E04**; this screen consumes them.
- The rate-limit governor itself — **E34**; this screen visualises its accounting.
- Recorder and storage administration screens (SCR-140..142) — **E16**.
- Alerting rules and their delivery — **E40**.

## Acceptance criteria
```gherkin
Scenario: Health overview shows every subsystem
  When the owner opens /admin/health
  Then WS connection states, ingest rates and lag, per-account rate-limit budget, queue depths, database sizes and latency, error rates and process uptime are all shown
  And every figure carries a freshness timestamp
  And status is conveyed as text, never by colour alone

Scenario: Drill down into a subsystem
  When the owner selects a subsystem tile
  Then recent errors, recent reconnects and the relevant metrics over the last hour are shown
  And each metric series has a table alternative for screen-reader users

Scenario: A degraded subsystem names its blast radius
  Given the ingestion subsystem is degraded
  Then its tile is escalated with a text label
  And the affected features are named explicitly
  And a remediation hint is given
  And the degradation is announced via a polite live region rather than silently changing

Scenario: The health screen survives the failure it reports
  Given Postgres is slow and the exchange connection is down
  When the owner opens /admin/health
  Then every tile resolves independently within the page budget
  And no tile blocks another
  And the page remains interactive throughout

Scenario: Rate-limit budgets and the fan-out simulator
  When the owner opens the connectivity screen with five accounts configured
  Then per-account, per-endpoint-class usage against limit with headroom is shown as numbers with units
  And the simulator states the request cost and the percentage of the minute budget for a five-account fan-out with brackets
  And recent 10018 events are listed with the exchange's stated recovery time

Scenario: The screen does not add measurable load (failure/edge case)
  When the health screen is left open for one hour
  Then the additional load on the backend stays within 1 percent
  And no polling loop runs faster than 1 Hz
  And closing the tab releases every subscription
```

## Technical notes / design
- Health data comes from the metrics pipeline through `GET /api/v1/admin/health` plus WS `system` deltas at ≤1 Hz. **No tile queries a subsystem directly** and the browser never queries the exchange directly (SCR-147 performance note) — usage figures come from the backend's own rate-limit accounting and the exchange's response headers.
- Each tile is an independent data boundary: its own loading, error, degraded and stale states, driven by the per-section envelope from E42-T01. A tile whose data is older than 3× its expected cadence self-marks as stale rather than presenting an old number as current.
- SCR-144's incident table is cursor-paginated with live appends over `system`; 10k rows scroll within 8 ms scripting per frame; long messages expand into a detail row rather than truncating silently.
- Every sparkline has a `<table>` alternative toggled by a real control, per `docs/plan/05-accessibility-standard.md` — a chart is never the only representation.
- Force-reconnect and incident acknowledgement are audited (`connectivity.reconnect_forced`, `incident.acknowledged`) and wrapped in **CMP-093 AuditActionTrigger**.

## Test plan
- **Unit** (≥80%): tile status mapping incl. stale detection; degraded-state copy assembly (affected features + remediation hint); fan-out simulator arithmetic against worked examples; incident row rendering and expansion; sparkline-to-table toggle.
- **Contract**: MSW from `22-api-openapi.yaml`; `system` deltas validated against `cv://ws/v1/system.schema.json` including the `exchange_state` and `connection_quality` shapes.
- **Integration (RTL)**: all-degraded rendering; live incident append; stale-data self-marking.
- **E2E** (E42-Q02): kill the WS connection and observe the health tile, the incident row and the recovery, end to end.
- **Chaos** (E42-Q03): the screen is opened while ingestion is down and Postgres is slow, asserting independent tile resolution and continued interactivity.
- **Perf**: one-hour open-tab load measurement against the ≤1% budget; 10k-row incident scroll against the 8 ms/frame budget.
- Fixtures: `tests/fixtures/health/all_ok.json`, `ingestion_degraded.json`, `exchange_banned.json`, `incidents_10k.json`.

## Security notes
Data classification: **Internal/Confidential** — operational telemetry reveals architecture and capacity, which is useful to an attacker. Controls: the health, incidents and connectivity routes are admin-authorised server-side (SR-017); error messages surfaced from subsystems are sanitised so stack traces, connection strings, internal hostnames and key identifiers never reach the browser (SR-005); the `q`/filter parameters are parameterised server-side. Force-reconnect is a state-changing action and therefore audited and rate-limited. No API key, secret or account credential appears in any health payload — per-account rows are labelled by account **label**, never by key material or UID secrets.

""" + A11Y_ADMIN + "\n\n" + PERF_NOTE + "\n\n" + OBS_ADMIN + """
- This screen is itself instrumented: `cv_admin_health_view_active` (gauge) so the ≤1% load claim can be verified from production data rather than asserted.

""" + DOD_ENG + """

## Dependencies
- **E42-T01** — the aggregation framework and the per-section envelope.
- **E42-S01** — admin shell.
- **E42-D05** — handoff pack covering SCR-143, SCR-144 and SCR-147, Done ≥2 sprints ahead.
- **E04** — the metrics pipeline and `system_events` producers.
- **E34** — the rate-limit governor accounting rendered by SCR-147.

## Branch
`feat/admin-screens-health`. Three PRs: health tiles + drill-down, incident log, connectivity + simulator.

""" + REF))

S.append(t(
    "E42-S07", "Story",
    "Build the backups and restore screen and the guided manager-onboarding flow",
    ["type/feature", "priority/p1", "a11y", "security", "design-qa"],
    "web", "Sprint 17", "P1 High", "Development", "R15 Data lifecycle", 5, "E42",
    ["E42-T04", "E42-S02", "E42-D05"],
    """## Context
Two surfaces that both live at the edge of the epic:
- **SCR-146 Admin: backups & restore** (`/admin/backups`, R-355) — the list, "run backup now", verification results, and the restore flow gated by maintenance mode, typed confirmation and step-up, with the explicit statement of what a restore does and does **not** recover (market history is not restored from these backups).
- **US-ADMIN-013 Manager onboarding workflow (Should)** at `/admin/users/new` (R-303, `docs/plan/13-user-flows.md` §4) — a guided, resumable flow through sub-account creation, the 48-hour key restriction, key creation with 2FA, permission scoping, IP whitelisting, profile creation, limits and the invite. Its NFR is a hard rule: *"the flow never stores a secret outside the encrypted store, and never displays one after entry."*

The onboarding flow is deliberately a **wizard over other epics' capabilities**: it orchestrates E27 (accounts and keys), E28 (profiles and limits) and E42-S02 (invite). It owns the sequencing, the blocked-step handling and the resume state — not the underlying operations.

## Scope / Deliverables
- Stories: **US-ADMIN-013** (Should), plus the backup/restore surface referenced by SCR-146.
- **SCR-146** using **CMP-049 Table**, **CMP-044 ConfirmDialog**, **CMP-023 Progress Bar**, **CMP-036 KeyValueRow**, **CMP-093 AuditActionTrigger**, **CMP-087 AdminLayout**: backup list with timestamp, scope (Postgres OMS / rules / audit / config), size, integrity-check result and retention; run-now with progress; restore flow with its maintenance-mode gate, typed confirmation and step-up; failed-backup and failed-verification states; last-successful-backup age warning; audited, step-up-gated download/export.
- The **restore scope statement rendered from the server's manifest** (E42-T04), enumerating covered datasets and the explicitly-not-covered ones (QuestDB tick/L2/bar history, Parquet cold storage) — data, not hard-coded copy.
- **Manager onboarding wizard** at `/admin/users/new`: stepper with completed/blocked/pending states; a blocked key step shows the **exact unlock time** of the 48-hour restriction and lets the rest of the flow continue; resume-where-you-left-off with completed steps marked; a final review step before the invite is issued.
- Secret handling in the wizard: key material is entered once, submitted directly to the E27 vault endpoint, never held in component state beyond the submit, never echoed back, and never written to local/session storage or logs.
- APIs: the backup routes from E42-T04, `GET /api/v1/admin/jobs/{jobId}`, plus the E27/E28/E42-S02 endpoints the wizard orchestrates; audit actions `backup.run`, `backup.restore`, `user.invited`.

## Out of scope
- Backup execution, scheduling and off-box copy — **E04/infra**.
- API-key vault storage, the key self-check and the IP-whitelist enforcement — **E27**; the wizard calls them.
- Profile and risk-limit semantics — **E28**/**E39**.
- Disaster-recovery runbook prose — **E45**, linked from this screen.

## Acceptance criteria
```gherkin
Scenario: Guided steps cover the whole manager setup
  When the owner starts the manager onboarding flow
  Then the flow walks through sub-account creation, the 48-hour key restriction, key creation with 2FA, permission scoping, IP whitelisting, profile creation, limits and the invite
  And each completed step is marked and summarised

Scenario: A blocked step does not block the flow
  Given the 48-hour key restriction is active for the new sub-account
  Then the key step is blocked and states the exact unlock time
  And the remaining steps continue to be completable
  And the flow can be finished later without redoing completed steps

Scenario: Resume where you left off
  Given the owner leaves the flow part-way through
  When they return to it
  Then it resumes at the first incomplete step with all completed steps marked
  And no re-entry of any previously supplied value is required, except secrets, which are never stored for resume

Scenario: No secret survives the flow (failure case)
  When key material is entered and submitted
  Then it is sent directly to the vault endpoint and cleared from client state
  And it is never displayed again, never written to storage, and never appears in any log or audit payload
  And navigating back to the key step shows the key's metadata only, with a re-enter action

Scenario: Restore requires every gate and states its scope
  Given maintenance mode is not active
  When the owner attempts a restore
  Then the action is blocked with the missing gate named, and the restore does not start
  And when all gates are satisfied the confirmation states, from the server manifest, exactly which datasets are restored and that market history is not among them
  And the restore is audited at critical severity

Scenario: A stale or failed backup is unmistakable (edge case)
  Given the last successful backup is older than the configured threshold, or a verification has failed
  Then the screen shows the age warning or the failure as text with the method used
  And a backup whose verification failed cannot be selected for restore
```

## Technical notes / design
- The wizard's resume state is server-side (a draft onboarding record), not `localStorage`, so it survives a different machine and cannot be tampered with client-side. Secrets are explicitly excluded from the draft.
- Each wizard step delegates to the owning epic's endpoint and renders that endpoint's own validation errors verbatim rather than re-implementing the rules — duplicated validation is how the wizard and the real screen drift apart.
- The typed confirmation for restore is verified server-side (E42-T04); the client merely collects it.
- Backup job progress is polled at 1 Hz with a phase label (`preflight`, `stopping_services`, `restoring`, `verifying`, `complete`) — never an indeterminate spinner for an operation of this consequence.
- The "what a restore does not recover" list is rendered from the manifest response; if the manifest is unavailable the restore action is disabled, because an unstated scope on a destructive action is not acceptable.

## Test plan
- **Unit** (≥80%): wizard step-state machine incl. blocked-step continuation and resume; secret-clearing assertions (a test that the key field's value is absent from component state and from any serialised draft after submit); restore gate composition; backup age-warning threshold; manifest-unavailable disabling.
- **Contract**: MSW from `22-api-openapi.yaml` for the backup and job routes and the orchestrated E27/E28 routes.
- **Integration (RTL)**: blocked 48 h step; resume from a server draft; restore blocked on missing maintenance; failed-verification backup not selectable.
- **E2E** (E42-Q02): full onboarding against demo fixtures ending in a redeemable invite; run-backup → verify → attempt restore without maintenance (blocked) → enter maintenance → restore in a throwaway environment.
- **Security**: a test that greps the built bundle, the network log and the audit rows for the fixture key material and asserts zero occurrences.
- **a11y**: axe-core on the wizard and the backups screen; manual NVDA pass over the stepper (step position and state announced) and the restore alertdialog.
- Fixtures: `tests/fixtures/backups/list_mixed.json`, `verify_failed.json`, `onboarding_draft_step3.json`.

""" + SEC_ADMIN + """

Additionally for this story, the dominant threat is **secret exposure during onboarding** (SR-005, and E27's key-handling controls): key material must never be logged, echoed, stored in a draft, retained in component state after submit, or included in any audit payload. Restore is the most destructive action in the product outside of live trading and carries a `critical`-severity audit row plus three independent gates.

""" + A11Y_ADMIN + "\n\n" + PERF_NOTE + "\n\n" + OBS_ADMIN + "\n\n" + DOD_ENG + """

## Dependencies
- **E42-T04** — backup list/verify/restore endpoints and the restore scope manifest.
- **E42-S02** — the invite step the wizard terminates in.
- **E42-T03** — maintenance mode, a precondition of restore.
- **E42-D05** — handoff pack covering SCR-146 and the onboarding flow, Done ≥2 sprints ahead.
- **E27** — sub-account creation, key creation, permission scoping, IP whitelisting, the 48-hour restriction metadata.
- **E28** — profile creation and limits.

## Branch
`feat/admin-screens-backups-onboarding`. Two PRs: backups & restore, then the onboarding wizard.

""" + REF))
