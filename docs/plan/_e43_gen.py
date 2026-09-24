# -*- coding: utf-8 -*-
"""Generator for docs/plan/backlog/E43.json - Security hardening & pen-test remediation."""
import json, io, os

T = []

def t(key, kind, title, labels, component, sprint, priority, perspective, risk,
      estimate, parent, blocked_by, body, phase="P4 Backtesting & Scripting",
      milestone="R4 Live enablement"):
    T.append({
        "key": key, "kind": kind, "title": title, "labels": labels,
        "component": component, "phase": phase, "sprint": sprint,
        "priority": priority, "perspective": perspective, "risk": risk,
        "estimate": estimate, "parent": parent, "blocked_by": blocked_by,
        "milestone": milestone, "body": body,
    })

DOD_COMMON = """## Definition of Done
- [ ] Acceptance criteria verified by an automated test or a recorded manual procedure (per `docs/plan/02-definition-of-ready-done.md` section 4.2).
- [ ] Coverage threshold met for touched packages (backend/engine >= 85%, frontend >= 80%; security-relevant modules M2/M14/M17/M18/M19 held >= 90% per `docs/plan/30-release-roadmap.md` section 8.4).
- [ ] Docs updated: `docs/plan/04-security-program.md` (SR traceability), `docs/plan/03-testing-strategy.md` SR-150 traceability table, ADR added/updated if a design decision was taken.
- [ ] SAST/SCA/secrets scans clean or triaged with a section 16.2 exception entry carrying an expiry date.
- [ ] Security engineer review comment posted (mandatory: `area/auth-rbac` per `02-definition-of-ready-done.md` section 8).
- [ ] QA sign-off comment with pass/fail per scenario.
- [ ] PR(s) merged to `main` via the merge queue with 2 approvals incl. a code-owner; all required checks green.
- [ ] Feature-flag state recorded where behaviour is flag-gated.
"""

# ---------------------------------------------------------------- EPIC
epic_body = """## Context
R4 "Live enablement" (`docs/plan/30-release-roadmap.md` section 8) adds **almost no new features - its product is assurance**. Nothing in CandleViewer may touch live money until an independent penetration test has been executed and every Critical/High finding is resolved and re-tested (`docs/plan/04-security-program.md` section 13.5, SR-159). E43 is the epic that carries that obligation.

The system arriving at R4 is already substantial: local auth with Argon2id + mandatory TOTP and server-side sessions (E09, module M18), an append-only hash-chained audit log (M19), an envelope-encrypted API-key vault (E27, module M2), an OMS that fans out orders across sub-accounts with a native stop-loss invariant (E29/E32/E34), a rule engine, an Electron shell and a Tailscale-only network boundary. Each of those was reviewed in isolation as it was built. E43 reviews them **as one attack surface**, from the outside, by someone who did not build them - `docs/plan/04-security-program.md` section 13.4 requires the tester to be independent of the implementing team, external preferred.

The epic is deliberately split in three phases that map onto the three R4 sprints:
1. **Sprint 20 - pre-test hardening.** Close the things we already know are loose before paying a tester to find them: CSP tightening (SR-112), Electron fuse/hardening audit (SR-110..SR-119), session-fixation and CSRF review (SR-012/013/041/042), auth rate-limit and lockout review (SR-014..SR-016), dependency freeze plus a full SCA and license sweep (SR-130..SR-136), full-history secrets scanning (SR-142), SBOM generation and signing (SR-133/SR-137), and an authenticated ZAP full scan against staging. Code freeze for the test is **2027-07-02**.
2. **Sprint 21 - the test itself.** The pen-test window opens **2027-07-05** and the report lands **2027-07-16** (`30-release-roadmap.md` section 8.5). Scope is fixed by `04-security-program.md` section 13.2: authentication, authorisation (horizontal and vertical), order path, rule engine, credential handling, the WebSocket layer, the web application, the Electron shell, infrastructure/Tailscale, audit non-repudiation and the kill switch.
3. **Sprint 22 - triage, remediation, retest.** Every accepted finding becomes a ticket with a regression test (SR-153) and a retest item. Remediation is funded by the **named 90-pt R4 remediation reserve** (`30-release-roadmap.md` section 4 and 8.2) which sits *outside* this epic's 55 points - E43's own points buy the hardening, the tooling, the surfaces and the assurance process, not the unknown findings.

E43 also owns the two ADMIN user stories that make security posture visible and make the live gate honest: **US-ADMIN-010 Security posture panel** and **US-ADMIN-012 Live-trading enablement gate** (the gate's *backend environment separation* is E44's; the *criteria evaluation, blocking and evidence* is E43's).

## Scope / Deliverables
**User stories:** US-ADMIN-010 (Must, security posture panel), US-ADMIN-012 (Must, live-trading enablement gate - criteria/attestation half), plus hardening obligations against US-ONB-005/US-ONB-008 (auth/2FA), US-ACCT-003/US-ACCT-005 (key permissions and health) and US-ADMIN-008/US-ADMIN-009 (audit integrity) that are re-verified rather than re-built here.

**Screens:** SCR-137 Admin: security centre (`/admin/security`), SCR-128 Admin: key health & secrets policy panel, SCR-136 Admin: audit event detail, SCR-010 App shell (live-gate badge surface), SCR-074 Environment switcher (gate-blocked state).

**Components:** CMP-028 Callout/Banner, CMP-033 CopyButton, CMP-034 MaskedValue, CMP-035 Countdown/Timer text, CMP-036 KeyValueRow, CMP-043 Dialog, CMP-046, CMP-049 Table, CMP-050 Card, CMP-068, CMP-087 AdminLayout, CMP-093 AuditActionTrigger, CMP-173, CMP-175 KeyPermissionBadge, CMP-178 SystemHealthTile.

**API:** `GET /api/v1/admin/security/summary` (`SecuritySummary` schema, `x-rbac: audit:read`), `GET /api/v1/admin/audit`, `POST /api/v1/admin/audit/verify`, `POST /api/v1/admin/audit/export`, `GET /api/v1/admin/health`, `GET|PATCH /api/v1/admin/feature-flags/{flagKey}`.

**DB tables:** `users`, `user_roles`, `user_account_access`, `sessions`, `sessions_rotation`, `api_keys`, `api_key_rotations`, `feature_flags`, `feature_flag_overrides`, `audit_log`, `audit_checkpoints`.

**Backend modules:** M2 key vault / secrets, M18 auth-sessions-RBAC, M19 audit log; surfaces of M1 (settings/environment), M14 (OMS order path) and M21 (admin) are exercised but owned elsewhere.

**Children (31):** 15 engineering tickets - 12 Tasks, 2 Stories, 1 Spike (**62 engineering pts**, against the 55-pt budget +/-15%); 3 design tickets (D, 11 pts); 6 QA tickets (Q, 20 pts); 7 security tickets (X, 30 pts). Design/QA/security points are tracked separately from the engineering budget. Remediation tickets `E43-Rnn`, filed by E43-X03 after triage, are funded by the separate 90-pt R4 reserve and are not counted here.

## Out of scope
- **Android / any mobile client** - out of scope for the whole plan (owner decision 2026-09-14).
- A separate admin application - admin is RBAC-gated screens inside the web app.
- Non-Bybit exchanges; spot, inverse or options instruments (USDT linear perps only).
- Environment separation *mechanics* (typed `live`/`demo`/`testnet` setting, separate schemas/namespaces, startup self-check, key-permission audit tooling) - that is **E44**.
- Chaos/failover/reconciliation and rollback/restore drills - that is **E45**.
- Testing Bybit's own infrastructure, DoS against the exchange, social engineering, physical attacks, and the Tailscale vendor platform (`04-security-program.md` section 13.3).
- The unknown remediation work itself beyond triage/coordination: funded by the separate 90-pt R4 reserve, filed as new tickets by E43-X03.

## Acceptance criteria
```gherkin
Scenario: Pen-test exit criteria met
  Given the independent penetration test described in docs/plan/04-security-program.md section 13 has been executed against the demo environment
  When the report and the retest report are archived
  Then there are zero open Critical findings and zero open High findings
  And every Medium finding is either fixed or recorded as a section 16.2 exception signed by the Owner with an expiry date inside one release cycle
  And docs/plan/32-risk-register.md carries an entry for each accepted item

Scenario: Hardening baseline enforced by CI, not by memory
  Given the pre-test hardening pass is complete
  When a developer opens a pull request that weakens any hardening control
  Then the corresponding required check (electron-hardening, semgrep, gitleaks, license-scan, rbac-matrix, trivy, csp-assertion) fails and the merge is blocked

Scenario: The live gate cannot be opened on an unproven build
  Given at least one Live-enablement gate item from docs/plan/07-release-and-prr.md section 6 is outstanding
  When the Owner opens SCR-137 Admin security centre
  Then the Live enablement control is disabled and lists exactly which items are outstanding, with the attester and date for each attested item
  And no API call can enable the live-trading flag while any item is outstanding

Scenario: Every confirmed finding leaves a regression test behind
  Given a pen-test finding has been accepted and remediated
  When the remediation PR is reviewed
  Then it contains an automated regression test referencing the finding id (SR-153) and the test fails against the pre-fix commit
```

## Technical notes / design
- **Traceability contract.** Every ticket in this epic names the `SR-xxx` requirements it satisfies; `docs/plan/03-testing-strategy.md` holds the SR -> test traceability table required by SR-150 and it must be complete before the PRR.
- **Freeze discipline.** From 2027-07-02 the branch under test is frozen at a tagged commit. Remediation lands on `main` after the report and is re-tested against a new tag; the tester is given both hashes.
- **Finding lifecycle.** report -> triage (severity confirmed, CVSS + business context) -> ticket with `sec:critical`/`sec:review` + regression test + retest item -> fix -> retest -> archive. Tickets created during triage are children of E43 with keys allocated from `E43-R01` upwards by E43-X03 and are funded by the reserve.
- **Severity policy.** Critical/High block R4 outright. Medium requires an owner-signed exception with expiry. Low may be deferred to R5 with a ticket.
- **No live credentials anywhere in this epic.** Testing runs against demo with demo credentials and per-role tester identities (`04-security-program.md` section 13.4); CI never holds production credentials (SR-140).

## Test plan
- Per-child test plans, plus epic-level: the full required-check set on `main` (`04-security-program.md` section 12.3) green on the frozen tag; the ZAP authenticated full scan with zero new High; the RBAC matrix test covering every route x role x grant scenario (SR-151); the SR-152 negative-test suite; the audit-chain verification test against a populated database.
- Epic-level QA: E43-Q06 regression pack and sign-off, executed on the retest tag.

## Security notes
This epic *is* the security work; threat sources are `04-security-program.md` section 5 areas 1-10 in their entirety. Data classification: touches secrets (API keys, KEK handles, session tokens, TOTP seeds), PII (user records) and financial data (orders, positions, journal). Security review label mandatory on every child.

## Accessibility notes
SCR-137, SCR-128 and SCR-136 are UI surfaces and carry the full WCAG 2.2 AA obligation per `docs/plan/05-accessibility-standard.md`; there is explicitly no "internal admin tool" exemption (`02-definition-of-ready-done.md` section 8). Findings and severities must be conveyed as text, never by colour alone.

## Performance notes
Hardening must not regress the budgets in `docs/plan/06-performance-and-load-standard.md`: CSP and Electron changes must not cost chart-engine frame time; the security summary is computed server-side on a schedule and cached, adding <= 1% load (SCR-137 performance note); auth rate-limiting adds <= 5 ms p95 to the login path.

## Observability
Metrics `cv_security_findings_open{severity}`, `cv_auth_failed_logins_total`, `cv_auth_lockouts_total`, `cv_audit_chain_verify_status`, `cv_sbom_published_info`, `cv_scan_findings{tool,severity}`. Audit events `security.finding_dismissed`, `security.rescan_requested`, `flag.changed`, `audit.export_requested`. Alerts for auth-failure spikes and audit-chain divergence.

## Definition of Done
- [ ] Every child ticket Done or explicitly descoped with a recorded disposition.
- [ ] Pen-test executed by an independent tester; report and retest report archived; zero open Critical/High.
- [ ] Medium/Low findings fixed or risk-accepted in writing by the Owner with expiry dates in `docs/plan/32-risk-register.md`.
- [ ] Coverage: M2/M18/M19 >= 90%; no regression from R3.
- [ ] `docs/plan/04-security-program.md` and `docs/plan/03-testing-strategy.md` updated to shipped reality; ADR-0016 merged.
- [ ] a11y: axe-core green on SCR-137/SCR-128/SCR-136 plus a manual screen-reader pass.
- [ ] Security sign-off recorded with reviewer name, scan results and outstanding exceptions (SR-160).
- [ ] QA epic-level regression/exploratory pass executed and recorded.
- [ ] Demoed to the Owner at Sprint Review with explicit acceptance; PRR Live-enablement gate items evidenced.
- [ ] Retro note filed.

## Dependencies
- **E09** Auth, sessions, 2FA & RBAC (M18/M19) - the subject of most hardening.
- **E27** Accounts, sub-accounts & API-key vault (M2) - credential-handling surface.
- **E42** Admin screens - SCR-137/SCR-128/SCR-136 host chrome and admin routing.
- **E34** Trade-group fan-out & rate-limit governor - order-path attack surface under test (roadmap dependency `E34 --> E43`).
- **E02** Monorepo scaffold & toolchain - CI gate plumbing.
- Feeds **E44** (live gate can only open once E43's criteria are met) and **E49**.

## Branch
`feat/e43-security-hardening-<short>` per child (e.g. `feat/e43-security-csp`, `feat/e43-security-electron-fuses`). PR size guidance: <= 400 LOC diff; hardening changes are reviewed line by line, so prefer one control per PR.

## References
- `docs/plan/30-release-roadmap.md` section 8 (R4), section 3 epic register row E43, section 12 dependency graph.
- `docs/plan/04-security-program.md` sections 5, 6, 12, 13, 14, 16.
- `docs/plan/03-testing-strategy.md`, `docs/plan/05-accessibility-standard.md`, `docs/plan/06-performance-and-load-standard.md`, `docs/plan/07-release-and-prr.md` section 6.
- `docs/plan/11-user-stories.md` section 26 ADMIN (US-ADMIN-010, US-ADMIN-012).
- `docs/plan/14-screens-catalogue.md` SCR-137, SCR-128, SCR-136; `docs/plan/18-traceability-matrix.md`.
- `docs/plan/20-architecture.md` sections 2.2, 3.10, 3.11; `docs/plan/21-database-schema.md`; `docs/plan/22-api-openapi.yaml`.
- ADR-0009 secrets and key management, ADR-0010 auth and RBAC, ADR-0011 Electron vs Tauri, ADR-0013 CI pipeline.

## Child dependency graph
```mermaid
flowchart TD
    subgraph design["Design - Sprint 18"]
        D01[E43-D01 Wireframe to hi-fi SCR-137 gate and findings]
        D02[E43-D02 Hi-fi SCR-128 / SCR-136 + DS contributions]
        D03[E43-D03 a11y review, design QA, handoff]
    end
    subgraph s20["Sprint 20 - pre-test hardening"]
        X01[E43-X01 STRIDE refresh]
        X04[E43-X04 Abuse cases]
        X05[E43-X05 SAST/DAST rules]
        T01[E43-T01 CSP tightening]
        T02[E43-T02 Electron hardening audit]
        T03[E43-T03 Session fixation + CSRF]
        T04[E43-T04 Rate-limit + lockout]
        T05[E43-T05 Dep freeze + SCA]
        T06[E43-T06 Secrets history scan]
        T07[E43-T07 SBOM + signing]
        T09[E43-T09 RBAC matrix coverage]
        T10[E43-T10 Audit chain + mirror]
        K01[E43-K01 Tailscale boundary spike]
        S01[E43-S01 Security centre gate]
        S02[E43-S02 Posture checks]
    end
    subgraph s21["Sprint 21 - the test"]
        T08[E43-T08 ZAP full scan]
        X02[E43-X02 Independent pen-test]
        X06[E43-X06 Key/permission checks]
    end
    subgraph s22["Sprint 22 - remediate and prove"]
        X03[E43-X03 Findings triage]
        T11[E43-T11 Regression harness]
        T12[E43-T12 ADR-0016 + docs]
        X07[E43-X07 Retest + evidence pack]
    end
    subgraph qa["QA"]
        Q01[E43-Q01 Black-box plan]
        Q02[E43-Q02 Exploratory charter]
        Q03[E43-Q03 E2E negative suite]
        Q04[E43-Q04 Rate-limit DoS load]
        Q05[E43-Q05 a11y audit]
        Q06[E43-Q06 Regression pack + sign-off]
    end
    D01 --> D03
    D02 --> D03
    D01 --> S01
    D02 --> S02
    X01 --> X04
    X01 --> T01
    X01 --> T03
    X04 --> X02
    X05 --> T01
    T02 --> T07
    T05 --> T07
    T06 --> X02
    T01 --> T08
    T03 --> T08
    T04 --> T08
    T09 --> T08
    K01 --> X02
    T08 --> X02
    S01 --> X02
    S02 --> S01
    X06 --> X02
    X02 --> X03
    X03 --> T11
    X03 --> X07
    T11 --> X07
    T12 --> X07
    Q01 --> Q06
    Q02 --> X03
    Q03 --> Q06
    Q04 --> Q06
    Q05 --> Q06
    Q06 --> X07
```
"""

t("E43", "Epic", "Security hardening & pen-test remediation",
  ["type/feature", "area/auth-rbac", "priority/p0", "security", "qa", "design", "a11y", "perf"],
  "auth", "Sprint 20", "P0 Critical", "Security", "None", 123, None,
  ["E09", "E27", "E42", "E34", "E02"], epic_body)

json.dump(T, io.open(os.path.join(os.path.dirname(__file__), "_e43_part1.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("part1", len(T))
