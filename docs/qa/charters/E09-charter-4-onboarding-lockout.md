# E09-C4 Charter: onboarding and lockout

- Ticket: E09-Q06 (#297) · Format: session-based test management · Date: 2026-10-09
- Tester: AI agent (Agent B). **Deviation (honest scope):** no staging build, no browser session recording, no 60-120 min human time box, and no docker stack were available. Each session was an in-process exploration: the listed oracles were checked against the existing fakes-backed suites by re-running them, plus a code-read of the services. Nothing here was observed in a real browser. Items needing a human or staging are listed under "Not probed" with the open issue that owns them.
- No credentials used; fixtures are deterministic and fake.

## Charter
Abuse invite links (reuse, expiry, wrong person, double-open) and lockout timing, and follow break-glass docs literally.

## Oracles
- O1 An invite redeemable twice or after expiry or revocation.
- O2 Lockout state that differs after reload or clock change.
- O3 Pre-elevated (Owner) invite possible.
- O4 Break-glass step that cannot be followed as written.

## Areas covered (in-process evidence)
| Probe | Evidence | Result |
|---|---|---|
| Reuse / expired (72 h) / unknown / revoked | `test_invite_service.py` (reuse, expired, unknown, revoked), `test_stepup_invite_abuse.py::test_ac_inv_01..03` | uniform rejection |
| Simultaneous redemption | `test_invite_service.py::test_concurrent_redemptions_exactly_one_wins` | one wins (O1 ok) |
| Pre-elevated invite | `test_owner_role_cannot_be_invited`, `test_ac_inv_04_cannot_invite_pre_elevated_owner` | refused (O3 ok) |
| Abandoned enrolment | `test_abandoned_enrolment_leaves_user_invited`, `test_wrong_totp_code_does_not_activate` | stays invited |
| Lockout and expiry on fixed clock | `test_credential_abuse.py::test_ac_cred_04`, `test_ac_cred_05_lockout_expires_on_fixed_clock`; `tests/unit/auth/test_throttle.py` | ok |
| Lockout UI countdown | `apps/web/e2e/auth/login.spec.ts` (A08 UI half) | stub-level |

Run result: 47 passed (1 deselected integration).

## Not probed
- Lockout countdown across a real page refresh and across a system clock change (browser; server clock #2086).
- Invite opened by the wrong person over HTTP (listed NOT RUN in `docs/security/abuse-cases/e09-auth.md`).
- Break-glass drill: owned by E09-X04 (#300); not run here and not duplicated.
- Keyboard-only walk of the onboarding wizard: covered only by the stubbed Playwright spec.

## Anomalies
None observed in-process.
