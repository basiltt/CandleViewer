# E09-C3 Charter: session identity and concurrency

- Ticket: E09-Q06 (#297) · Format: session-based test management · Date: 2026-10-09
- Tester: AI agent (Agent B). **Deviation (honest scope):** no staging build, no browser session recording, no 60-120 min human time box, and no docker stack were available. Each session was an in-process exploration: the listed oracles were checked against the existing fakes-backed suites by re-running them, plus a code-read of the services. Nothing here was observed in a real browser. Items needing a human or staging are listed under "Not probed" with the open issue that owns them.
- No credentials used; fixtures are deterministic and fake.

## Charter
Same user in three contexts with sign-out-everywhere, role change and disable racing, to find a context that keeps authority or is falsely evicted.

## Oracles
- O1 A revoked session that still passes a request or keeps a socket.
- O2 A sibling session revoked when only one was targeted.
- O3 A refresh token usable twice, or extending absolute lifetime.
- O4 Any revocation without an audit row.

## Areas covered (in-process evidence)
| Probe | Evidence | Result |
|---|---|---|
| Revoke one leaves siblings | `test_session_service.py::test_revoke_one_session_leaves_others_of_the_same_user_untouched` | no false eviction (O2 ok) |
| Sign-out everywhere (optionally excluding current) | `test_sign_out_everywhere_revokes_all_but_can_exclude_current` | ok |
| Refresh reuse revokes family | `test_session_abuse.py::test_ac_ses_03_refresh_reuse_revokes_family_and_access_tokens` | ok (O3) |
| Absolute lifetime not extendable | `test_ac_ses_04_refresh_cannot_extend_absolute_lifetime` | ok |
| IDOR revoke of another user's session | `test_csrf_cookie_abuse.py::test_ac_csrf_05_idor_cannot_revoke_other_users_session` | refused |
| Socket closed on revocation, others unaffected | `tests/unit/ws/test_revocation.py` (3 tests), chaos S3/S4 in `tests/chaos/auth/test_auth_chaos.py` | ok (O1) |
| Role change / disable during session | `tests/unit/test_ws_permissions.py`, `tests/unit/api/test_users_router.py` | next-request effect shown |
| Postgres outage fails closed | chaos S1 | ok; S1b (real restart) **skipped: docker stack unavailable** |

Run result: 69 passed, 1 skipped (S1b).

## Not probed
- True concurrency of three browser contexts; cookie jars in a real browser.
- Idle-lock and absolute-expiry screens (SCR-005/112): #1640. Server clock for E2E expiry: #2086.
- Concurrent role revocation during a step-up-gated action as a single atomic scenario (AC edge case in the ticket): covered only in parts (step-up needs elevation per session; role change refuses next request); no one test asserts both audit rows in order. **Gap, see Follow-ups.**

## Anomalies
None observed in-process.

## Follow-ups (recommend)
1. Add a deterministic interleaving test: manager mid step-up, owner revokes role, action refused, audit order preserved, no partial effect.
