import json, io, os

T = []

def t(key, kind, title, labels, component, sprint, priority, perspective, risk, estimate,
      parent, blocked_by, body, phase="P3 Drawing & Alerts", milestone="R3 Trading on demo"):
    T.append(dict(key=key, kind=kind, title=title, labels=labels, component=component,
                  phase=phase, sprint=sprint, priority=priority, perspective=perspective,
                  risk=risk, estimate=estimate, parent=parent, blocked_by=blocked_by,
                  milestone=milestone, body=body))

REF = """## References
- `docs/plan/00-planning-brief.md` — locked decision: admin is RBAC-gated screens **inside** the web app; no separate admin app; no Android.
- `docs/plan/11-user-stories.md` §26 ADMIN — US-ADMIN-001..014.
- `docs/plan/14-screens-catalogue.md` §10 Admin (SCR-120..149) and §11 (SCR-154).
- `docs/plan/15-component-catalogue.md` — CMP-087, CMP-088, CMP-049, CMP-050, CMP-055, CMP-095, CMP-099, CMP-173..179, CMP-210.
- `docs/plan/12-sitemap.md` §R-300..R-360 (`/admin/*` routes, step-up rule).
- `docs/plan/18-traceability-matrix.md` rows US-ADMIN-001..014.
- `docs/plan/21-database-schema.md` §3.1, §3.9, §3.10, §10.1 (`users`, `roles`, `user_roles`, `user_account_access`, `sessions`, `feature_flags`, `feature_flag_overrides`, `audit_log`, `audit_checkpoints`, `system_events`).
- `docs/plan/22-api-openapi.yaml` — `/users*`, `/auth/step-up`, `/auth/sessions`, `/admin/overview`, `/admin/capacity`, `/admin/health`, `/admin/incidents`, `/admin/audit`, `/admin/audit/verify`, `/admin/audit/export`, `/admin/feature-flags`, `/admin/backups*`, `/admin/jobs/{jobId}`, `/admin/security/summary`.
- `docs/plan/23-ws-protocol.md` §6.2, §6.3, §8, §9.5 and the `system` topic schema (`cv://ws/v1/system.schema.json`).
- `docs/plan/27-adrs/ADR-0010-auth-and-rbac.md`; `docs/plan/27-adrs/ADR-0014-observability.md`.
- `docs/plan/04-security-program.md` §5.7 Area 7 Admin screens (D1..D5), SR-005, SR-017, SR-025, SR-026, SR-027, SR-060..SR-069.
- `docs/plan/03-testing-strategy.md`, `docs/plan/05-accessibility-standard.md`, `docs/plan/06-performance-and-load-standard.md`, `docs/plan/02-definition-of-ready-done.md`.
- `docs/plan/30-release-roadmap.md` §7 R3 (E42 = 34 pts, S16–S17)."""

DOD_ENG = """## Definition of Done
- [ ] Code merged to `main` via merge queue; 2 approvals incl. 1 code-owner; conventional commits; PR ≤400 LOC diff.
- [ ] Unit tests added; backend coverage ≥85% on touched modules (security-relevant M19 held ≥90%), frontend ≥80%.
- [ ] Contract tests green against `22-api-openapi.yaml` / `23-ws-protocol.md`.
- [ ] Docs updated (`docs/plan/2x-*` where behaviour diverged) and ADR amended if a decision changed.
- [ ] Storybook entries added for every new/changed component with all states (UI tickets).
- [ ] axe-core CI green + one manual screen-reader pass (UI tickets).
- [ ] Audit events emitted and asserted by test for every state-changing action.
- [ ] QA sign-off recorded on the ticket; design sign-off recorded for UI tickets (design ticket Status=Done ≥2 sprints prior).
- [ ] Demoed at Sprint Review."""

# ---------------------------------------------------------------- EPIC
epic_body = """## Context
R3 "Trading on demo" (`docs/plan/30-release-roadmap.md` §7) closes the execution loop. Once several people can reach a system that places real orders on several Bybit accounts, the owner needs the *governance* surface: who may log in, what they may reach, what they actually did, whether the machine is healthy, and which capabilities are switched on right now. The planning brief locks this down: **owner/admin functions are RBAC-gated screens inside the web app — there is no separate admin application** (`00-planning-brief.md`, "Locked decisions"; `27-adrs/ADR-0010-auth-and-rbac.md` decision 6).

E42 is the delivery of that surface. It does **not** invent the security model — `E09` already built authentication, sessions, TOTP, the RBAC policy-decision point and the hash-chained append-only audit *writer* (module **M19**). E42 builds module **M21 `admin`**: the aggregation/administration API and the `/admin/*` screens that read and operate the machinery other epics own (`E27` accounts & keys, `E28` profiles & trade groups, `E39` risk caps & kill-switch, `E16` recorder & retention, `E04` observability). The roadmap scopes it (§7.2) as *"Users and roles CRUD with RBAC matrix editing; Bybit account and key management surfaces; per-account profile administration; audit-log browser with filtering, export and hash-chain verification; system health; feature-flag console incl. the kill-switch; recorder/storage administration; session management (force-logout)"* — 34 pts, Sprints S16–S17, modules **M19, M21**, story domain **ADMIN**.

Three properties shape every ticket below:
1. **The UI gate is cosmetic; the server gate is the control.** `04-security-program.md` §5.7 threat **D1** ("admin screen hidden in the UI but its API remains callable by a Manager", Critical) means every admin route is independently authorised server-side (SR-017) and a role×route matrix test is a required check.
2. **Dangerous administration is step-up gated.** SR-025 requires a ≤5 min elevated session for creating/deleting users, changing roles or grants, changing flags, exporting the audit log, restoring a backup and disabling the kill-switch; `12-sitemap.md` R-300 additionally requires an admin re-auth token ≤15 min old to enter any `/admin/*` route (SCR-149).
3. **The audit log is evidence, not a table.** `21-database-schema.md` §3.10.1 makes `audit_log` append-only at the grant/trigger level with an Ed25519-checkpointed SHA-256 hash chain. The browser must never offer a mutation affordance, must never render a secret (SR-005), must role-scope its projections (threat D3) and must surface chain verification failure as a *security incident*, not a UI error.

## Scope / Deliverables
**User stories owned here (Must/Should of domain ADMIN not owned by another epic):**
- US-ADMIN-001 User management (Must)
- US-ADMIN-002 Role assignment and account binding (Must)
- US-ADMIN-007 Feature flags (Must)
- US-ADMIN-008 Append-only audit log — the *browser, verification and immutability surfacing* (Must; the writer ships in E09)
- US-ADMIN-009 Audit log search and export (Must)
- US-ADMIN-011 System health screen (Must)
- US-ADMIN-013 Manager onboarding workflow (Should)
- US-ADMIN-014 Sub-account capacity awareness (Should)

Stories **explicitly owned elsewhere** and only *linked* from here: US-ADMIN-003/US-ADMIN-004 (E39 risk caps & risk dashboard), US-ADMIN-005 (E28 trade groups), US-ADMIN-006 (E16 recorder/retention; E42 surfaces the entry point only), US-ADMIN-010 and US-ADMIN-012 (E44 security posture and live-enablement gate).

**Screens:** SCR-120 Admin home, SCR-121 users list, SCR-122 user detail/edit, SCR-123 invite user, SCR-124 view-as, SCR-135 audit log, SCR-136 audit event detail, SCR-143 system health, SCR-144 incident/connectivity log, SCR-145 feature flags, SCR-146 backups & restore, SCR-147 exchange connectivity & rate limits, SCR-148 maintenance mode, SCR-149 admin re-authentication gate, SCR-154 permission denied (403), plus the SCR-017 manager-onboarding checklist surface.

**Components:** CMP-087 AdminLayout, CMP-088 PageHeader, CMP-173 AuditRow, CMP-174 AuditFilterBar, CMP-178 SystemHealthTile, CMP-179 FeatureFlagRow, CMP-095 FeatureFlagChip, CMP-210 HealthChips, CMP-099 PrintExportBar (reused: CMP-001, CMP-004, CMP-009, CMP-011, CMP-013, CMP-023, CMP-024, CMP-027, CMP-028, CMP-033, CMP-036, CMP-040, CMP-043, CMP-044, CMP-046, CMP-047, CMP-049, CMP-050, CMP-055, CMP-065, CMP-068, CMP-076, CMP-087, CMP-092, CMP-093, CMP-105, CMP-138, CMP-175, CMP-176).

**API:** `GET/POST /api/v1/users`, `GET/PATCH/DELETE /api/v1/users/{userId}`, `PUT /api/v1/users/{userId}/roles`, `GET/PUT /api/v1/users/{userId}/account-access`, `GET /api/v1/invites/{inviteToken}`, `POST /api/v1/auth/step-up`, `GET /api/v1/auth/sessions`, `GET /api/v1/admin/overview`, `GET /api/v1/admin/capacity`, `GET /api/v1/admin/health`, `GET /api/v1/admin/incidents`, `GET /api/v1/admin/audit`, `POST /api/v1/admin/audit/verify`, `POST /api/v1/admin/audit/export`, `GET/PUT /api/v1/admin/feature-flags[/{flagKey}]`, `GET/POST /api/v1/admin/backups`, `GET /api/v1/admin/backups/{backupId}`, `POST /api/v1/admin/backups/{backupId}/verify`, `POST /api/v1/admin/backups/{backupId}/restore`, `GET /api/v1/admin/jobs/{jobId}`.

**WS:** `system` topic (implicit subscription) — `kind: health | feature_flags | kill_switch | exchange_state | notice | shutdown_notice`; RBAC revocation semantics `23-ws-protocol.md` §9.5.

**DB tables:** `users`, `roles`, `role_permissions`, `user_roles`, `user_account_access`, `sessions`, `sessions_rotation`, `feature_flags`, `feature_flag_overrides`, `audit_log`, `audit_checkpoints`, `system_events`, `exchange_accounts`.

**Architecture modules:** M19 (audit) — read/verify/export side; M21 (admin API & screens, `33-raci.md` row "Admin API & screens (M21)").

## Out of scope
- The audit *writer*, hash-chain trigger, RBAC policy-decision point, sessions and TOTP (E09).
- Bybit account/key CRUD and the key vault itself (E27) — E42 links to SCR-125..SCR-129, it does not rebuild them.
- Per-account profile editing (E28, SCR-130..SCR-133) and trade-group administration (E28, SCR-062).
- Risk caps, lockouts, the risk dashboard and the kill-switch engine (E39, SCR-071..SCR-073, SCR-134) — E42 surfaces the kill-switch *control* on the flags console only, driven by E39's service.
- Recorder/retention editors (E16, SCR-140..SCR-142) — E42 provides the admin-home tile and route entry only.
- Security centre posture panel and live-enablement gating (E44, SCR-137, US-ADMIN-010/012).
- Any separate admin application, any Android surface, any non-Bybit exchange.

## Acceptance criteria
```gherkin
Scenario: Admin is reachable only by the owner, server-side
  Given a signed-in manager
  When they request any /api/v1/admin/* route or navigate to any /admin/* path
  Then the router renders SCR-154 (403) or a 404 for the route, the API answers 403 with no state change
  And an audit row with outcome=denied is written for every attempt

Scenario: Entering admin requires a fresh re-auth
  Given the owner's admin re-auth token is older than 15 minutes
  When they open /admin/users
  Then SCR-149 is presented, password + TOTP are required, and on success admin routes unlock for 15 minutes
  And the remaining validity is visible in the admin chrome

Scenario: The audit log is provably append-only
  Given an operator with direct database access attempts UPDATE or DELETE on audit_log
  Then the statement is refused by the forbid_mutation trigger and grant model
  And when the owner runs POST /admin/audit/verify over the full range the chain verifies to the latest checkpoint
  And a deliberately tampered fixture row is reported with its exact chain position

Scenario: Every consequential admin action is attributable
  When the owner invites a user, changes roles, changes account grants, toggles a flag, exports the audit log or restores a backup
  Then each action required a step-up-elevated session, and each produced one audit row with actor, role, before_state, after_state and severity

Scenario: Health survives the thing it reports on
  Given ingestion is down and Postgres is slow
  When the owner opens /admin/health
  Then every tile resolves independently, the degraded tiles name the affected features and a remediation hint, and no tile blocks another
```

## Technical notes / design
- **M21 `admin`** is a read/aggregate + administration module. It owns no domain state of its own except `feature_flags`/`feature_flag_overrides`; everything else it composes from M14 (OMS), M17 (risk), M2 (credentials), M16/M20, M4 (recorder) and the metrics pipeline (M?/`04-observability` registry from E04). Aggregation endpoints fan out with per-source timeouts and return partial results with per-section `status` so a single slow subsystem cannot make the admin screen unusable.
- **Elevation model.** Two distinct clocks: (a) the SR-025 *step-up* token, 5 min, required per dangerous mutation; (b) the `12-sitemap.md` R-300 *admin area* token, 15 min of activity, required to enter `/admin/*`. Both are server-issued, both are audited (`admin.session_elevated`, `admin.area_entered`), neither is client-computable.
- **Flag resolution order** (`21-database-schema.md` §3.9): user override → role override → percentage rollout (hash of `user_id||flag_key`) → default. `is_killswitch` flags bypass caching and are re-read every 5 s. Changes broadcast on `system` (`kind: feature_flags`) and must apply within 2 s; flags needing a reload declare it.
- **Audit projections.** Owner sees raw `before_state`/`after_state`; viewer/manager see redacted projections scoped to their own actor id (threat D3, SR-067). Redaction is applied in the projection layer, not the template.
- **Error codes** used by the UI: `step_up_required`, `forbidden`, `conflict` (last-owner protection), `precondition_failed` (ETag), `rate_limited`.

## Test plan
- Unit: flag resolution order incl. kill-switch bypass; audit projection redaction per role; last-owner guard; capacity computation; aggregation partial-failure assembly.
- Contract: every E42 route against `22-api-openapi.yaml`; `system` frames against the WS JSON schema.
- Integration: hash-chain verification over a 1 M-row fixture incl. one tampered row; force-logout propagation to a live WS session within 5 s; flag push within 2 s.
- E2E (Playwright, web + Electron): invite → redeem → bind account → trade scope observed → disable → sessions revoked; audit search → export → the export itself audited; view-as enter/exit; maintenance mode enter/exit.
- Perf: audit filter round-trip ≤400 ms over a 10 M-row table; admin overview ≤800 ms; users table 500 rows ≤4 ms scripting/frame.
- Chaos: health screen with ingestion down, Postgres slow and Bybit REST 5xx; flag store unavailable (last-known-good + explicit staleness).
- Security: role×route matrix asserting 403 + no state change + audit row for every disallowed combination.

## Security notes
Threats `04-security-program.md` §5.7: **D1** admin API callable by a manager (Critical), **D2** flag console used to enable live trading (High), **D3** audit viewer leaking raw payloads to a viewer (Medium), **D4** risk caps silently changed (High), **D5** owner-only actions reachable through shared self-service handlers (High). Controls: SR-017 server-side capability check, SR-025 step-up, SR-026 separate self-service vs administrative routes (no `user_id` parameter on self-service), SR-027 new users default to Viewer with no grants, SR-005 secrets never serialised, SR-060..SR-069 audit coverage and hash chain. Data classification: A-03 credentials (referenced, never rendered), A-11 audit log, A-18 flags & kill-switch state, A-19 manager PII. The epic carries the `security` label and a STRIDE model is mandatory (roadmap §7.4 lists E42 among the epics whose Critical/High findings must all be closed).

## Accessibility notes
WCAG 2.2 AA across every admin screen. Status, severity, role and health state are **always words**, never colour alone. The view-as banner is a `role="status"` landmark first in document order, repeated in every floating window, with a single documented exit hotkey. Destructive flows are named buttons with typed confirmation and `role="alertdialog"`. Tables follow the CMP-049 contract with real table semantics and cursor pagination that is keyboard-reachable. The re-auth gate announces failures assertively and preserves in-progress form content on mid-task expiry.

## Performance notes
Budgets from `06-performance-and-load-standard.md` and the screens catalogue: admin overview render ≤800 ms with independent tile resolution; audit filter round-trip ≤400 ms over 10 M rows, 200 rows/page cursor pagination; users table 500 rows without exceeding 4 ms scripting per frame; health page ≤2 ms scripting per frame at the 1 Hz `system` cadence and adding ≤1 % system load; flag propagation ≤2 s; permission change reflected in the target session ≤2 s; invite creation ≤500 ms; audit single-record fetch ≤300 ms; maintenance mode blocks order acceptance server-side within 200 ms.

## Observability
New metrics: `cv_admin_request_duration_seconds{route}`, `cv_audit_query_duration_seconds`, `cv_audit_chain_verify_status`, `cv_audit_chain_last_checkpoint_age_seconds`, `cv_flag_change_total{flag,actor}`, `cv_flag_push_latency_seconds`, `cv_admin_forbidden_total{route,role}`, `cv_stepup_challenge_total{outcome}`, `cv_view_as_sessions_active`. Audit events: `admin.area_entered`, `admin.session_elevated`, `users.create`, `users.disable`, `roles.grant`, `roles.revoke`, `user.assignment_changed`, `flags.change`, `audit.viewed`, `audit.exported`, `admin.view_as_started|ended`, `maintenance.enabled|disabled`, `backup.run|verified|restored|downloaded`, `health.diagnostics_exported`. Alerts: chain-verification failure = critical page; `cv_admin_forbidden_total` spike = security warning.

## Definition of Done
- [ ] All child Stories/Tasks/Spikes/Design/QA/Security tickets Done or explicitly descoped with a recorded disposition.
- [ ] Epic acceptance criteria verified end to end on the demo environment, not per child.
- [ ] Roadmap exit criterion 12 met: "Admin screens complete, RBAC-gated, and audited; audit hash-chain verification passes on a tampered-row test".
- [ ] Roadmap exit criterion 10 met for admin routes: role×route matrix test green (403 + no state change + audit row).
- [ ] Coverage: ≥85% backend on M21, ≥90% on M19 read/verify/export paths, ≥80% frontend; zero open P0/P1.
- [ ] a11y: axe-core CI green on all 15 screens + manual screen-reader pass recorded.
- [ ] perf: every budget in "Performance notes" measured and recorded.
- [ ] security: STRIDE finalised, all Critical/High closed, Security engineer sign-off comment.
- [ ] QA: epic-level regression + exploratory pass executed and recorded.
- [ ] Docs: `12-sitemap.md`, `14-screens-catalogue.md` and ADR-0010 reconciled with shipped behaviour; admin operations runbook published.
- [ ] Demoed to the Owner at Sprint Review with explicit acceptance recorded.

## Dependencies
- **E09** Auth, sessions, 2FA & RBAC — provides `users`/`roles`/`sessions`, the policy-decision point, step-up (`POST /auth/step-up`) and the M19 audit writer with its hash chain. Nothing here is buildable without it.
- **E04** Observability baseline — provides the metrics registry, `GET /admin/health` primitives, incident recording and the Grafana/alerting stack that SCR-143/SCR-144 render.
- **E27** Accounts, sub-accounts & API-key vault — provides `exchange_accounts`, key metadata and SCR-125..SCR-129, which the admin home and users screens link to; also supplies the sub-account capacity facts for US-ADMIN-014.
- **E39** Risk caps, lockouts & kill-switch — provides the kill-switch service and state that the flags console exposes and the lockout state rendered on the users list.
- **E16** Recorder, retention & disk budget — provides SCR-140/SCR-141 and the recorder tile figures on SCR-120.

## Branch
`feat/admin-screens-<short>` per child ticket (e.g. `feat/admin-screens-audit-browser`). PRs ≤400 LOC diff; screens land one at a time behind the `admin.<area>` route, never as one mega-PR.

## Mermaid dependency graph of children
```mermaid
graph TD
  subgraph Design[Design - S14/S15, 2 sprints ahead]
    D01[E42-D01 UX research + wireframes]
    D02[E42-D02 Hi-fi users, invite, detail, view-as]
    D03[E42-D03 Hi-fi audit, flags, health, incidents, connectivity]
    D04[E42-D04 Hi-fi home, re-auth, backups, maintenance + DS/motion]
    D05[E42-D05 A11y design review + handoff]
    D06[E42-D06 Design QA]
  end
  subgraph Eng[Engineering - S16/S17]
    K01[E42-K01 Spike: audit search at 10M rows]
    T01[E42-T01 M21 aggregation API + admin elevation]
    T02[E42-T02 Audit query, verify, export]
    T03[E42-T03 Flags + maintenance service]
    T04[E42-T04 Backups and restore API]
    T05[E42-T05 Docs + ADR-0010 amendment]
    S01[E42-S01 Admin shell, SCR-149, SCR-120, SCR-154]
    S02[E42-S02 Users list, invite, capacity]
    S03[E42-S03 User detail, sessions, view-as]
    S04[E42-S04 Audit browser + detail]
    S05[E42-S05 Flags console + maintenance mode]
    S06[E42-S06 Health, incidents, connectivity]
    S07[E42-S07 Backups + manager onboarding]
  end
  subgraph QASec[QA and Security]
    Q01[E42-Q01 Test plan + fixtures]
    Q02[E42-Q02 E2E suite]
    Q03[E42-Q03 Perf, load, chaos]
    Q04[E42-Q04 A11y audit + exploratory]
    Q05[E42-Q05 Regression pack + sign-off]
    X01[E42-X01 STRIDE]
    X02[E42-X02 RBAC matrix + abuse cases]
    X03[E42-X03 Security review + sign-off]
  end
  D01 --> D02 --> D05
  D01 --> D03 --> D05
  D01 --> D04 --> D05
  D05 --> S01
  K01 --> T02
  T01 --> S01
  T01 --> S02
  S01 --> S02 --> S03
  S01 --> S06
  T02 --> S04
  T03 --> S05
  T04 --> S07
  S02 --> S07
  X01 --> T01
  X01 --> X02
  S03 --> X02
  S05 --> X02
  Q01 --> Q02 --> Q05
  Q01 --> Q03
  S04 --> Q02
  S06 --> Q02
  S07 --> Q02
  Q02 --> Q04 --> Q05
  X02 --> X03
  S01 --> D06
  S07 --> D06
  D06 --> Q05
```

## Risks
- **R5 Scope** — "admin" is a magnet for every unowned screen. The Out-of-scope list above is the contract; anything not listed belongs to E27/E28/E39/E16/E44.
- **R10 Key-person** — the owner is the only holder of the owner role; a total lockout is mitigated by the SR-023 break-glass CLI, which E42 must surface loudly after use.
- **R15 Data lifecycle** — audit retention is indefinite; the browser must scale to 10 M rows, hence E42-K01.
- **Privilege escalation (D1/D5)** is the single highest-consequence failure mode; E42-X02 automates the matrix rather than relying on review.

""" + REF

t("E42", "Epic", "Admin screens (users, roles, audit, health, flags)",
  ["type/feature", "area/accounts-admin", "priority/p1", "design", "qa", "security", "a11y", "perf"],
  "web", "Sprint 16", "P1 High", "Architecture", "R5 Scope", 88, None,
  ["E09", "E04", "E27", "E39", "E16"], epic_body)

json.dump(T, open("__e42_part1.json", "w"), indent=1)
print(len(T))
