# E09 regression pack (auth, session, RBAC)

Ticket: E09-Q06 (#297). Source plan: `qa/plans/e09-auth-rbac-test-plan.md`. Automation status: `qa/plans/e09-q02-automation-status.md`.
All paths below are relative to `services/api/` unless they start with `apps/`.

## How to run
Automated backend subset (single command, about 30 s locally, no network, no docker):

```
cd services/api
uv run pytest -p no:randomly --no-cov \
  tests/unit/auth tests/unit/audit tests/unit/api tests/unit/ws tests/unit/test_ws_permissions.py \
  tests/contract/rbac tests/security/auth tests/qa/test_e09_dryrun_group_a.py tests/chaos/auth
```
Expected at authoring time (2026-10-09): 1094+ passed, 1 skipped (chaos S1b needs docker). Any failure is a release-gate blocker.
Frontend E2E (needs Playwright browsers; **not run by the pack author**): `apps/web/e2e/auth/*.spec.ts`.
A CI-runnable tag does not exist yet; this pack lists paths instead. Adding a pytest marker is a follow-up (see Gaps).
Time budget: automated about 10 min including setup; manual items below about 2 h. Cold execution by a second person has **not** happened.

## A. Behaviour to automated test
| Case | Behaviour | Test (file::test) |
|---|---|---|
| A01 | Password step returns mfa_required, no session | `tests/qa/test_e09_dryrun_group_a.py::test_e09_tc_a01_correct_credentials_return_mfa_required_no_session`; `apps/web/e2e/auth/login.spec.ts` (A01) |
| A02 | TOTP verify issues session | `tests/unit/auth/test_mfa_service.py::test_verify_valid_code_creates_a_session` |
| A03 | Disabled user refused | `tests/qa/test_e09_dryrun_group_a.py::test_e09_tc_a03_disabled_account_rejected_after_password_check` |
| A04/A05 | TOTP skew +-1 accepted, further refused | `tests/unit/auth/test_mfa_service.py::test_verify_tolerates_clock_drift_within_one_step`; `tests/chaos/auth/test_auth_chaos.py::test_s2_totp_step_skew_pm1_accepted_pm3_rejected_replay_refused` |
| A06 | TOTP replay refused | `tests/unit/auth/test_mfa_service.py::test_verify_reused_code_is_rejected`; `tests/security/auth/test_mfa_abuse.py::test_ac_mfa_01_totp_replay_inside_skew_window_rejected` |
| A07 | Unknown user vs wrong password indistinguishable | `tests/qa/test_e09_dryrun_group_a.py::test_e09_tc_a07_unknown_user_and_wrong_password_are_indistinguishable`; `tests/unit/auth/test_login_timing_enumeration.py::test_login_timing_unknown_vs_wrong_password_indistinguishable_over_1000_samples` |
| A08 | Lockout with Retry-After | `tests/qa/test_e09_dryrun_group_a.py::test_e09_tc_a08_lockout_returns_423_with_retry_after`; `tests/security/auth/test_credential_abuse.py::test_ac_cred_05_lockout_expires_on_fixed_clock` |
| A09 | 5 wrong TOTP codes lock challenge | `tests/unit/auth/test_mfa_service.py::test_verify_locks_after_five_failed_attempts` |
| A10 | Expired challenge refused | `tests/unit/auth/test_mfa_service.py::test_verify_expired_challenge_raises_challenge_invalid` |
| A11 | Recovery code single use | `tests/unit/auth/test_mfa_service.py::test_recovery_code_use_forces_totp_reenrollment`; `tests/security/auth/test_mfa_abuse.py::test_ac_mfa_03_recovery_code_single_use` |
| B01-B05 | Enrolment, recovery codes once, regeneration | `tests/unit/auth/test_mfa_service.py::test_first_login_enrolment_returns_recovery_codes`; `tests/security/auth/test_mfa_abuse.py::test_ac_mfa_04_recovery_code_dead_after_regeneration`; `tests/unit/auth/test_recovery_codes.py` (E2E for standalone SCR-003: manual M3) |
| B06-B09 | Forced password change and policy | `apps/web/e2e/auth/enrolment.spec.ts` (B06-B09); `tests/unit/auth/test_invite_service.py::test_password_policy_rejects_weak` |
| C01 | Session bootstrap | `apps/web/e2e/auth/session.spec.ts` (C01); `tests/unit/api/test_auth_router.py` |
| C02/C03 | Idle and absolute expiry | `tests/unit/auth/test_session_service.py::test_absolute_expiry_disarms_trading_by_revoking`; `::test_order_entry_refused_while_idle_locked_regardless_of_client`; `tests/security/auth/test_session_abuse.py::test_ac_ses_04_refresh_cannot_extend_absolute_lifetime` (UI half: manual M1) |
| C04-C06 | Step-up required, grant, expiry | `tests/unit/auth/test_step_up_b16.py::test_grace_expiry_sends_elevation_deadline_back_to_normal`; `tests/unit/auth/test_step_up.py::test_dangerous_action_requires_step_up`; `apps/web/e2e/auth/stepup.spec.ts` |
| C07 | Refresh rotation | `tests/unit/auth/test_session_service.py::test_refresh_rotates_the_token_and_revokes_the_old_session`; `tests/security/auth/test_session_abuse.py::test_ac_ses_02_every_refresh_issues_new_id_and_token` |
| C08 | TOTP verify latency | manual M4 (perf evidence: `docs/qa/perf/e09-auth-perf-report.md`) |
| C09 | Tampered or missing cookie | `tests/security/auth/test_session_abuse.py::test_ac_ses_07_forged_access_token_rejected`; `apps/web/e2e/auth/session.spec.ts` (C09) |
| D01-D03 | Sessions list, revoke, sign-out everywhere | `tests/unit/auth/test_session_service.py::test_sign_out_everywhere_revokes_all_but_can_exclude_current`; `tests/unit/api/test_sessions_router.py`; `tests/security/auth/test_csrf_cookie_abuse.py::test_ac_csrf_05_idor_cannot_revoke_other_users_session` |
| D04 | Owner TOTP reset | `tests/unit/auth/test_step_up.py::test_owner_reset_revokes_sessions_without_oms_effects_or_secret`; `::test_owner_cannot_reset_self` |
| D05/D06 | Grant revoke / disable mid-session closes sockets | `tests/contract/rbac/test_scope_and_ws.py::test_in_flight_subscription_gets_revoked_when_the_grant_is_withdrawn`; `tests/unit/ws/test_revocation.py::test_revoke_sends_bye_and_closes_4401_only_for_that_session`; `tests/chaos/auth/test_auth_chaos.py::test_s4_revocation_storm_every_socket_gets_bye_4401` |
| E01 | Invite creation | `tests/unit/auth/test_invite_service.py::test_create_returns_high_entropy_token_stored_only_as_hash`; `tests/unit/api/test_invites_router.py` |
| E02-E04 | Redeem, single use, expiry | `tests/unit/auth/test_invite_service.py::test_invite_accepted_end_to_end_activates_user`, `::test_token_reuse_rejected`, `::test_expired_token_rejected_after_72h`, `::test_concurrent_redemptions_exactly_one_wins`; `apps/web/e2e/auth/onboarding.spec.ts` |
| E05 | Onboarding checklist | `tests/unit/api/test_onboarding_checklist.py`; `tests/unit/api/test_onboarding_create_app_e2e.py` |
| E06/E07 | Viewer and cross-account denial | `tests/contract/rbac/test_scope_and_ws.py::test_valid_capability_but_non_granted_account_is_403_nothing_mutated_and_audited`; `tests/security/auth/test_authz_abuse.py::test_ac_authz_02_account_id_tampering_denied_without_grant`; `apps/web/e2e/auth/denied.spec.ts` |
| E08 | Tailscale-only reachability | manual M5 (deployment level; no automated test) |
| E09 | Every route has a capability declaration | `tests/contract/rbac/test_route_matrix.py::test_undeclared_served_route_fails_the_build`; `tests/unit/api/test_deny_by_default.py` |
| Audit | Append-only, chain, redaction, never drops | `tests/unit/audit/test_wal.py`, `test_writer_never_drops.py`, `test_query_verify.py`, `test_redact_credentials.py`; every denial audited: `tests/security/auth/test_authz_abuse.py::test_ac_authz_07_every_denial_is_audited` |
| Fail closed | Postgres outage, gateway restart, session expiry under load | `tests/chaos/auth/test_auth_chaos.py` S1, S3, S5 (S1b real restart: needs docker, skipped without) |

## B. Manual steps (run on a staging deploy)
| Id | Step | Pass when |
|---|---|---|
| M1 | Idle-lock and session-expiry screens (C02/C03 UI half): idle past the configured timeout, then unlock with password | Screen appears, data feed stays on, unlock works. Blocked on #1640 until SCR-005/112 are built |
| M2 | Real-browser cookie behaviour: sign in on two contexts, sign out everywhere, reload both | Both land on sign-in; no stale shell |
| M3 | Standalone TOTP enrolment and recovery-code screen (B01-B05) | Codes shown once; reload does not show them. Blocked on #1640 (SCR-003 not built) |
| M4 | Time 20 consecutive TOTP verifies on staging | p95 within the SCR-002 budget in `docs/plan/14-screens-catalogue.md` |
| M5 | From outside the tailnet, try to reach the API (E08) | Connection refused or timeout |
| M6 | Keyboard-only pass of login, step-up dialog, invite wizard | Every control reachable with visible focus; no trap |
| M7 | Re-run the four charters in `docs/qa/charters/` against staging with a browser and record real debriefs | Debriefs updated; anomalies filed |

## C. Gaps and deferrals (each cites an open issue)
- Server-side E2E clock for step-up and session expiry: #2086.
- Session screens RTL/axe/Playwright, SCR-002/003/005/112 cases: #1640.
- CSRF double-submit token negative test: #2090.
- Rules-manager grant isolation test: #2094; owner check shape: #2096.
- k6 Argon2 timing header: #2097.
- No pytest marker/tag for this pack yet, no `e2e-auth` CI lane, no cold execution by a second person: not done.
- No explicit test for "role revoked during an in-flight step-up-gated action, audit order preserved" and none for "password change during live step-up": recommend follow-up tickets (not filed by this PR).
