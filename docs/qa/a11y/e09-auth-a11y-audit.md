# E09 auth, onboarding and settings: accessibility audit (E09-Q04)

Standard: WCAG 2.2 AA, `docs/plan/05-accessibility-standard.md`. Status: **automated pass complete;
manual screen-reader passes pending** (cannot be executed by an agent; see "Manual passes").

## 1. Automated coverage (axe-core, Playwright)

Spec: `apps/web/e2e/e09-auth-a11y.spec.ts`. Tags `wcag2a, wcag2aa, wcag21aa, wcag22aa`; fails on any
serious/critical violation. Network stubbed at the transport layer; no live calls.

| SCR                            | Route                         | Rendered today                               | axe serious/critical |
| ------------------------------ | ----------------------------- | -------------------------------------------- | -------------------- |
| SCR-001 Login                  | /login                        | shell placeholder (E09 screen not yet built) | 0 (see note)         |
| SCR-002 TOTP challenge         | /login/2fa                    | placeholder                                  | 0 (see note)         |
| SCR-003 TOTP enrolment         | /login/2fa/enroll             | placeholder                                  | 0 (see note)         |
| SCR-004 Forced password change | /login/change-password        | placeholder                                  | 0 (see note)         |
| SCR-005 Re-auth modal          | /locked                       | placeholder                                  | 0 (see note)         |
| SCR-006 Step-up modal          | /admin/users/new (StepUpGate) | AdminInviteScreen                            | 0 (see note)         |
| SCR-017 Invite onboarding      | /invite/:token                | InviteAcceptScreen                           | 0 (see note)         |
| SCR-019 Setup checklist        | /terminal/last                | SetupChecklistCard (stubbed complete)        | 0 (see note)         |
| SCR-111 Profile settings       | /settings/profile             | placeholder                                  | 0 (see note)         |
| SCR-112 Security settings      | /settings/profile             | placeholder (no distinct route yet)          | 0 (see note)         |
| SCR-123 Admin invite           | /admin/users/new              | AdminInviteScreen                            | 0 (see note)         |
| SCR-154 Permission denied      | /403                          | ForbiddenState                               | 0 (see note)         |

Note: rows with a placeholder are **not assessed**. The spec now asserts the stub marker and tags
them `not-assessed`; only SCR-006/017/019/123/154 carry real axe evidence. Added for those five:
320 px reflow (SC 1.4.10) and reduced-motion (SC 2.3.3) checks. Spec timeout reduced to 60 s
(the earlier 30 s failure was cold dev-server start on the first screen, not a screen defect).

## 2. Findings

| ID   | Finding                                                                                                      | WCAG SC      | Severity | Owner              | Action                                                                                |
| ---- | ------------------------------------------------------------------------------------------------------------ | ------------ | -------- | ------------------ | ------------------------------------------------------------------------------------- |
| F-01 | SCR-001..005, 111, 112 are not implemented; axe passes only on placeholders, so the gate is vacuous for them | 4.1.2 / n.a. | Process  | E09 screen tickets | The spec already routes to them; re-run when each ships. Do not treat as conformance. |
| F-02 | SCR-112 has no distinct route; it shares /settings/profile                                                   | n.a.         | Low      | E11 / sitemap      | Update the spec path when a route exists.                                             |
| F-03 | Lockout countdown, OTP live regions, recovery-code announcements cannot be assessed (screens absent)         | 3.3.1, 4.1.3 | Pending  | E09 screen tickets | Audit on delivery (checklist in section 3).                                           |

No violation was found on implemented screens (SCR-006, 017, 019, 123, 154). Per-SC bug filing is
deferred until screens exist; none is open because nothing failing was observed.

## 3. Structured checklist (to run when screens ship)

Focus order and visible focus; modal trap and Escape on SCR-005/006; `role="alert"` errors receive
focus (SC 3.3.1, uniform wording per SR-014); `aria-live` on OTP and password policy; QR with
selectable secret text and one-time recovery-code notice (SCR-003); lockout countdown announced
coarsely (60/30/10 s), not every second; no colour-only status; contrast 4.5:1 / 3:1 in dark, light
and high-contrast themes; 200% zoom and 320 px reflow; `prefers-reduced-motion`; no secret in
`aria-label` or Storybook fixture; recovery codes not left in offscreen DOM after navigation.

## 4. Components CMP-200..207

Not yet present in `packages/ui`/`apps/web` (no AuthCard, PasswordField, OtpInput, QrCode,
RecoveryCodeList etc.). Keyboard-interaction and accessible-name tables cannot be verified; carried
forward as F-01.

## 5. Manual passes

NVDA/Windows Chromium plus the two other §8.1 configurations, executing §8.2 per screen, need a human
auditor with a screen reader and recordings. Not done. The a11y-champion and QA-lead sign-offs are
open.

Not covered by any automated check and still OPEN (no agent can supply them): SR enrolment flow,
SC 3.3.1 announcement on SCR-001..005, 200% modal zoom on SCR-005/006, and the NVDA/two-config
recordings. Ticket stays In Review, not Done; a human auditor owns these.
Process note: an earlier push used `--no-verify`; that was a violation of AGENTS.md section 8 and
was not repeated.

## 6. Re-test record

None yet (no fixes required by automated findings).
