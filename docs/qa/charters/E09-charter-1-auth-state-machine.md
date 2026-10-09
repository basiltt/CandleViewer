# E09-C1 Charter: auth state-machine boundaries

- Ticket: E09-Q06 (#297) · Format: session-based test management · Date: 2026-10-09
- Tester: AI agent (Agent B). **Deviation (honest scope):** no staging build, no browser session recording, no 60-120 min human time box, and no docker stack were available. Each session was an in-process exploration: the listed oracles were checked against the existing fakes-backed suites by re-running them, plus a code-read of the services. Nothing here was observed in a real browser. Items needing a human or staging are listed under "Not probed" with the open issue that owns them.
- No credentials used; fixtures are deterministic and fake.

## Charter
Interrupt every auth transition (MFA, step-up, recovery, re-enrolment) to find states where authority is gained, kept, or lost wrongly.

## Oracles (defined up front)
- O1 Any state where a user is authenticated but no audit row exists for the login.
- O2 Any error text/status that differs between an unknown user and a wrong password.
- O3 Any code, challenge or recovery code accepted twice.
- O4 Any elevation that survives its session, its action class or its window.

## Areas covered (in-process evidence)
| Probe | Evidence (re-run 2026-10-09) | Result |
|---|---|---|
| Stale or expired MFA challenge | `tests/unit/auth/test_mfa_service.py::test_verify_expired_challenge_raises_challenge_invalid` | refused (O3 ok) |
| Another user's challenge with my code | `tests/security/auth/test_mfa_abuse.py::test_ac_mfa_06_challenge_for_other_user_cannot_use_my_code` | refused |
| Recovery code while TOTP pending, concurrent consume | `test_ac_mfa_05b_concurrent_recovery_code_consumed_once`, `test_ac_mfa_03_recovery_code_single_use` | consumed once |
| Recovery code forces TOTP re-enrolment | `test_mfa_service.py::test_recovery_code_use_forces_totp_reenrollment` | ok |
| TOTP replay inside skew window | `test_ac_mfa_01_totp_replay_inside_skew_window_rejected` | refused |
| Step-up elevation transplanted to another session/action | `test_ac_stepup_01_elevation_not_transplantable_across_session_or_action`; `test_step_up.py::test_elevation_is_revoked_with_the_session` | refused (O4 ok) |
| Unknown vs wrong password | `test_login_timing_enumeration.py`, `test_ac_enum_01` | indistinguishable (O2 ok) |

Run result: 81 tests passed across the MFA / step-up / recovery / MFA-abuse / step-up-abuse files.

## Not probed (needs a human, a browser or staging)
- Closing the tab mid-MFA, browser back/forward during MFA: SCR-002 is not built; tracked in #1640.
- Server-side expiry of a step-up under a moving clock end to end: needs the server test clock, #2086.
- Password change during an active step-up: no existing test combines them; **gap, see Follow-ups**.
- Re-enrolling TOTP while an old authenticator is still configured (real device flow).
- Keyboard-only segment: login and step-up have Playwright keyboard cases (`login.spec.ts`, `stepup.spec.ts`); a manual screen-reader pass is not done here.

## Anomalies
None observed in-process. Dismissal reason for the absence of findings: scope was limited to existing coverage; absence of anomalies is not evidence of absence.

## Follow-ups (recommend, not filed)
1. Add an interaction test: password change while a step-up elevation is live must revoke or void the elevation (needs a decision from the auth owner on intended behaviour).
2. E2E for A02/A05/A06/A09/A10/A11 once SCR-002 exists (#1640).
