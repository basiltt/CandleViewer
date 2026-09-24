# -*- coding: utf-8 -*-
"""Shared helpers and boilerplate blocks for the E42 ticket tree."""

AREA = "area/accounts-admin"


def t(key, kind, title, labels, component, sprint, priority, perspective, risk,
      estimate, parent, blocked_by, body):
    return dict(key=key, kind=kind, title=title,
                labels=labels + [AREA],
                component=component, phase="P3 Drawing & Alerts", sprint=sprint,
                priority=priority, perspective=perspective, risk=risk,
                estimate=estimate, parent=parent, blocked_by=blocked_by,
                milestone="R3 Trading on demo", body=body)


REF = """## References
- `docs/plan/00-planning-brief.md` — locked decision: admin is RBAC-gated screens **inside** the web app; no separate admin app; Bybit USDT perps only; no Android.
- `docs/plan/11-user-stories.md` §26 ADMIN — US-ADMIN-001, 002, 007, 008, 009, 011, 013, 014.
- `docs/plan/14-screens-catalogue.md` §10 Admin — SCR-120, SCR-121, SCR-122, SCR-123, SCR-124, SCR-135, SCR-136, SCR-143, SCR-145, SCR-146, SCR-147, SCR-148 and §11 SCR-154.
- `docs/plan/15-component-catalogue.md` — CMP-087 AdminLayout, CMP-088 PageHeader, CMP-173 AuditRow, CMP-174 AuditFilterBar, CMP-178 SystemHealthTile, CMP-179 FeatureFlagRow, CMP-095 FeatureFlagChip, CMP-210 HealthChips, CMP-099 PrintExportBar, CMP-105 AccountMultiSelect, CMP-093 AuditActionTrigger, CMP-092 DegradedModeBanner, CMP-089 ForbiddenState, CMP-079 RbacGate.
- `docs/plan/12-sitemap.md` R-300..R-360 (`/admin/*` routes and the 15-minute admin re-auth rule).
- `docs/plan/18-traceability-matrix.md` rows US-ADMIN-001..014 and the SCR-120..SCR-154 rows.
- `docs/plan/21-database-schema.md` §3.1 (`users`, `roles`, `user_roles`, `user_account_access`, `sessions`, `sessions_rotation`), §3.9 (`settings`, `feature_flags`, `feature_flag_overrides`), §3.10 (`audit_log`, `audit_checkpoints`, `system_events`).
- `docs/plan/22-api-openapi.yaml` — `/users`, `/users/{userId}`, `/users/{userId}/roles`, `/users/{userId}/account-access`, `/auth/step-up`, `/auth/sessions`, `/admin/overview`, `/admin/capacity`, `/admin/health`, `/admin/incidents`, `/admin/audit`, `/admin/audit/verify`, `/admin/audit/export`, `/admin/feature-flags`, `/admin/feature-flags/{flagKey}`, `/admin/backups`, `/admin/backups/{backupId}`, `/admin/backups/{backupId}/verify`, `/admin/backups/{backupId}/restore`, `/admin/jobs/{jobId}`, `/admin/security/summary`.
- `docs/plan/23-ws-protocol.md` — the `system` topic (`cv://ws/v1/system.schema.json`) carrying health, feature-flag and maintenance pushes.
- `docs/plan/20-architecture.md` §3.10 Auth/RBAC/Audit (M19) and §3.11 Admin (M21: `UserAdmin`, `FlagAdmin`, `HealthConsole`, `RecorderAdmin`).
- `docs/plan/27-adrs/ADR-0010-auth-and-rbac.md`, `docs/plan/27-adrs/ADR-0014-observability.md`.
- `docs/plan/04-security-program.md` §5.7 Area 7 Admin screens (threats D1..D6), SR-005, SR-017, SR-025, SR-026, SR-027, SR-055, SR-065, SR-067.
- `docs/plan/03-testing-strategy.md`, `docs/plan/05-accessibility-standard.md`, `docs/plan/06-performance-and-load-standard.md`, `docs/plan/02-definition-of-ready-done.md`, `docs/plan/01-sdlc-and-branching.md`.
- `docs/plan/30-release-roadmap.md` §7 R3 — E42 = 34 pts, Sprints S16–S17; §7.3 exit criterion 12 (admin screens complete, RBAC-gated, audited; hash-chain verification passes on a tampered-row test)."""


DOD_ENG = """## Definition of Done
- [ ] Code merged to `main` through the merge queue: conventional commits, 2 approvals including 1 code-owner, PR diff ≤400 LOC, all required checks green.
- [ ] Unit tests added; coverage ≥85% on touched backend modules (M19/M21 held ≥90% as security-relevant per `30-release-roadmap.md` §8.4) and ≥80% on touched frontend packages; no regression to the package baseline.
- [ ] Contract tests green against `docs/plan/22-api-openapi.yaml` and, where WS frames change, `docs/plan/23-ws-protocol.md`.
- [ ] Every state-changing action emits its `audit_log` action and a test asserts the row (actor, object, before/after, severity, outcome).
- [ ] Docs updated where behaviour diverged from plan (`22-api-openapi.yaml`, `23-ws-protocol.md`, `21-database-schema.md`, `14-screens-catalogue.md`); ADR amended if a decision changed.
- [ ] Storybook entries for every new/changed component covering loading, empty, error, degraded and denied states (UI tickets).
- [ ] axe-core CI green on the touched routes plus one manual screen-reader pass (UI tickets).
- [ ] Observability added: metrics/log fields listed in the Observability section exist and are visible in the Grafana admin dashboard.
- [ ] Feature-flag state recorded (which flag gates this, default per environment).
- [ ] QA sign-off comment recorded; design sign-off recorded for UI tickets (the consuming design ticket is Status=Done and has been for ≥2 sprints).
- [ ] Demoed at Sprint Review against staging (demo), never live."""


DOD_QA = """## Definition of Done
- [ ] Test artefacts committed under `tests/` (or `docs/qa/` for plans/charters) and referenced from this ticket.
- [ ] Every scenario has an explicit pass/fail result recorded; failures raised as Bugs with `priority/*` and linked here.
- [ ] Automated suites run in CI on the standard pipeline and are non-flaky over 10 consecutive runs (any flake quarantined with a follow-up Chore).
- [ ] Fixtures are seeded/deterministic and contain no real key material, no real PII and no production audit rows.
- [ ] Coverage/traceability table maps each US-ADMIN story and each acceptance scenario of the covered stories to at least one executed test.
- [ ] QA sign-off comment posted with the pass/fail matrix; the epic-level regression note updated.
- [ ] Results demoed or summarised at Sprint Review."""


DOD_SEC = """## Definition of Done
- [ ] Findings recorded with STRIDE category, likelihood, impact, risk rating and mitigation mapped to an `SR-` control from `docs/plan/04-security-program.md`.
- [ ] Every Critical/High finding is fixed (linked ticket Done) or explicitly accepted by the Owner with a written rationale and an expiry date.
- [ ] Automated regression exists for each exploited path so the issue cannot silently return.
- [ ] `docs/plan/04-security-program.md` §5.7 and `docs/plan/32-risk-register.md` updated with any new threat or retired risk.
- [ ] Security engineer sign-off comment posted on this ticket.
- [ ] SAST (CodeQL/Semgrep/Bandit), SCA (pip-audit/npm audit) and secrets scanning clean or triaged for the touched code.
- [ ] Findings presented at the Security Review; no secret, key or real audit payload included in any artefact."""


DOD_DESIGN = """## Definition of Done
- [ ] Artefacts published in the CandleViewer Figma library with a version tag and linked from the relevant `docs/plan/14-screens-catalogue.md` entries.
- [ ] Every state named in Scope is drawn; the screen's own "Design sign-off acceptance checklist" in `14-screens-catalogue.md` is fully ticked.
- [ ] Every component maps to a `15-component-catalogue.md` ID; new/extended components have a design-system entry with tokens.
- [ ] Contrast and focus-order annotations on every frame; no status conveyed by colour alone.
- [ ] Consequence copy for destructive actions reviewed by the Owner and by Security.
- [ ] Signed off by the Chief Design Officer and the frontend lead (comment on the ticket).
- [ ] Status=Done ≥2 sprints before the consuming frontend story starts (design-ahead rule)."""


A11Y_ADMIN = """## Accessibility notes
Per `docs/plan/05-accessibility-standard.md` (WCAG 2.2 AA; admin screens get no "internal tool" exemption — `02-definition-of-ready-done.md` §8):
- Full keyboard operation: every action reachable by Tab/Shift+Tab in a logical order, visible focus ring (3:1 against the adjacent surface), no keyboard trap in dialogs/drawers, Esc closes and returns focus to the invoking control.
- Status is always text, never colour alone (role, state, severity, health, flag state).
- Tables use real table semantics with `<th scope>`, a caption naming the dataset, and an accessible row count; row actions are real buttons with names that include the row subject ("Deactivate alex").
- Live regions: `role="status"` for benign updates (health tiles, flag applied), `role="alert"` for failures and for the audit-chain integrity failure.
- Dialogs use `role="dialog"`/`alertdialog` with `aria-modal`, a labelled heading and focus placed on the first control, with the consequence text read before the confirm control.
- Target size ≥24×24 CSS px at compact density; text alternatives for every icon-only control.
- axe-core CI must be green on the route, plus one manual NVDA (Windows) pass recorded in the ticket."""


PERF_NOTE = """## Performance notes
Budgets from `docs/plan/06-performance-and-load-standard.md` and the per-screen budgets in `14-screens-catalogue.md`:
- `GET /api/v1/admin/overview` renders SCR-120 in ≤800 ms with each tile resolving independently (no tile may block another).
- Audit filter round-trip ≤400 ms p95 over a 10 M-row `audit_log`; cursor pagination at 200 rows/page (SCR-135).
- Users table: 500 rows render with ≤4 ms scripting per frame; presence/last-seen updates ≤0.1 Hz (SCR-121).
- Health tiles subscribe to WS `system` at 1 Hz and keep the page under 2 ms scripting per frame, and stay responsive while the subsystems they report on are degraded (SCR-143).
- Flag changes propagate to every session within 2 s; force-logout/disable revokes sessions within 5 s.
- The admin area must add ≤1% load to the running system (US-ADMIN-011 NFR) — no polling loop tighter than 1 Hz and no unbounded aggregation queries on the request path."""
