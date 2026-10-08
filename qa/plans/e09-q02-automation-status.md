# E09-Q02 (#293) automation status

Specs live in `apps/web/e2e/auth/` (repo convention; the ticket text says `tests/e2e/auth/`).
API is stubbed at the network layer (C-13.5); the backend-driven suite needs the E03 ephemeral stack.
Browser clock is `page.clock` (no sleeps); server-side clock endpoint does not exist yet.

| Case                         | Status                                                                               |
| ---------------------------- | ------------------------------------------------------------------------------------ |
| A01, A03, A07, A08 (UI half) | automated: login.spec.ts                                                             |
| A04/A05 (TOTP helper only)   | helper vector test; endpoint cases deferred -> #1640 (SCR-002 unbuilt)               |
| A02, A06, A09, A10, A11      | deferred -> #1640 (SCR-002 / recovery UI)                                            |
| B06-B09                      | automated: enrolment.spec.ts                                                         |
| B01-B05                      | deferred -> #1640 (SCR-003 standalone unbuilt); enrolment steps seen in wizard (E03) |
| C01, C09                     | automated: session.spec.ts (stub-level)                                              |
| C04, C05, C06                | automated: stepup.spec.ts (SPA grace window, fake clock)                             |
| C02, C03, C07, D01-D06       | deferred -> #1640 (SCR-005/111/112) and server test clock endpoint                   |
| E02-E05                      | automated: onboarding.spec.ts                                                        |
| E06, E07 (UI half)           | automated: denied.spec.ts; server half owned by E09-Q03                              |
| E08, E09, C08                | not E2E (manual / CI / E09-Q05)                                                      |

Not done: Electron lane (`@electron` tags only), `e2e-auth` CI job, mutation check, 10-run flake data.
