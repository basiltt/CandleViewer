# E09-X02 — Abuse-case catalogue: auth, session, RBAC (partial delivery)

- Ticket: E09-X02 (#298). Threat source: `docs/security/threat-models/e09-auth-rbac.md` (E09-X01).
- Method: white-box, in-process, fixed clock, in-memory fakes, no network. Automated cases live in
  `services/api/tests/security/auth/` and are permanent regressions.
- **Scope of this PR:** the durable service-level subset only. Rows marked **NOT RUN** have no observed
  result yet and are NOT claimed as defended; they remain open on #298 (so this PR uses `Refs`).
- Rule ids (verified present in `CONSTITUTION.md`): C-2.9 (audit), C-2.12 and C-12.4 (server-side RBAC),
  C-2.18 (bounded/off-loop work), C-12.6 (redaction), C-13.7 (deterministic tests, no sleeps/network).
- Verdict key: DEFENDED (attack failed as designed) · DESIGN-DECISION (accepted behaviour, confirm) ·
  FINDING · NOT RUN.
- Escalation result: **no privilege escalation found** by any executed case.

## Mutation check (DoD)

Each control was disabled on the scratch worktree and the named case failed, then reverted:

| Control disabled | Failing case |
|---|---|
| `consume_recovery_code` result ignored | AC-MFA-03 |
| refresh-reuse branch (`revoked_reason == "rotated"`) | AC-SES-03 |
| TOTP `record_time_step` replay guard | AC-MFA-01 |
| `_origin_ok` allow-list check | AC-CSRF-01 |
| CSRF `tokens_match` / `bound_to` compare (#2090, monkeypatched always-true) | AC-CSRF-07 (`test_mutation_disabling_compare_is_caught`) |
| `grant is None or not can_view` account check | AC-AUTHZ-02 |

## Cases

| Id | Threat / control | Precondition · capability | Steps | Expected | Observed | Verdict |
|---|---|---|---|---|---|---|
| AC-CRED-01 | U1 SR-011 | Captured hash; offline | Parse Argon2id header of stored hash, compare to `password_algo_params` and floor (m>=65536,t>=3) | Params in force meet floor, column matches hash | Matches (m=65536,t=3,p=4). Against the **in-memory fake** row; real DB row not queried | DEFENDED (DB check NOT RUN) |
| AC-CRED-02 | U1 pepper | Captured hash only | Verify with empty pepper | Fails | Fails | DEFENDED |
| AC-CRED-03 | U28 SR-015 C-2.18 | One IP, 40 usernames | Stuff login | Rejected before Argon2id after cap | 5 verifies, 35 cheap rejects | DEFENDED |
| AC-CRED-04 | U1 SR-016 | Many IPs, one account | 8 bad logins from distinct IPs | Account locks; right password refused | Locked at 5 | DEFENDED |
| AC-CRED-05 | U27 | Lockout DoS | Lock, advance clock 16 min | Lock is time-bounded | Login succeeds | DEFENDED (owner alert NOT RUN) |
| AC-ENUM-01 | U8 SR-014 | Unauthenticated | Unknown vs wrong password | Same type and message | Identical | DEFENDED |
| AC-ENUM-02 | U8 | Disabled user | Wrong then right password | Disabled only revealed after correct password | As designed | DESIGN-DECISION (documented trade-off) |
| AC-ENUM-03 | U8 SR-014 | Same host | 500 samples/arm, 10 warm-up dropped, interleaved, gc off; ratio-of-medians + Mann-Whitney | Indistinguishable | Passed (`@pytest.mark.perf`, opt-in via `CV_RUN_PERF=1`, ~55 s; prints n, ratio, z). Raw samples not persisted | DEFENDED |
| AC-SES-01 | U6 SR-013 | Pre-login id planted | Present as access token / session id | Rejected; new ids per mint | Rejected, ids differ | DEFENDED (audit row on attempt NOT RUN) |
| AC-SES-02 | SR-013 | Valid session | Refresh | New id, refresh and access token | New | DEFENDED |
| AC-SES-03 | refresh reuse | Stolen old refresh token | Replay after rotation | Family revoked incl. successor | Revoked | DEFENDED |
| AC-SES-04 | SR-013 | Valid session | Refresh | Absolute expiry not extended | Unchanged | DEFENDED |
| AC-SES-05 | U5 | Expired access token | Use after TTL | Rejected | Rejected | DEFENDED |
| AC-SES-06 | U5 | Stolen access token, other IP/UA | Present token | Sessions are not bound to IP/UA | Accepted; detection only via refresh reuse | **DESIGN-DECISION to confirm** (Architect/Owner; residual risk: bearer theft undetected until refresh) |
| AC-SES-07 | forged token | Garbage/oversize tokens | Present | Rejected | Rejected | DEFENDED |
| AC-CSRF-01 | TB-4 | Cross-site page | Cookie refresh with no / foreign / `null` Origin | 403, token not burned | 403, session intact | DEFENDED |
| AC-CSRF-02 | TB-4 | Empty allow-list | Any origin | 403 (fail closed) | 403 | DEFENDED |
| AC-CSRF-03 | SR-012 | Header spoof | `X-Forwarded-Proto: http` | Cookie stays HttpOnly+Secure+SameSite=Strict | Flags present | DEFENDED |
| AC-CSRF-04 | TB-4 | Cookie only, no bearer | logout / revoke session | 401 | 401 | DEFENDED |
| AC-CSRF-05 | O1/O7 | Attacker session | Revoke / list victim session | 403/404, not listed | Refused | DEFENDED |
| AC-CSRF-06 | O2 SR-041/SR-152 | Cross-site page, no `X-CSRF-Token` | Any state-changing request (cookie or bearer) | 403 `csrf_token_invalid`, `auth.csrf_refused` audited, no state change | 403, session intact | DEFENDED — fixed by PR #TBD (#2090) |
| AC-CSRF-07 | O2 SR-041/SR-152 | Header ≠ `cv_csrf` cookie | State-changing request | 403, audited | 403 | DEFENDED — fixed by PR #TBD (#2090) |
| AC-CSRF-08 | O2 SR-041 | Token minted for another session | Present it with own bearer | 403 (token bound to session) | 403 | DEFENDED — fixed by PR #TBD (#2090) |
| AC-CSRF-09 | SR-041 rotation | Valid session | Login / refresh | New `cv_csrf` (not HttpOnly, Secure, SameSite=Strict); old token refused | Rotated, old refused | DEFENDED — fixed by PR #TBD (#2090) |
| AC-MFA-01 | U11 SR-021 | Captured code | Replay same step; older step in skew | Rejected | MfaCodeReused | DEFENDED |
| AC-MFA-02 | U2 SR-015 | Brute force | Wrong codes | Locked at cap (5), even right code refused | Locked | DEFENDED |
| AC-MFA-03 | U9 SR-022 | Used recovery code | Reuse | Rejected | Rejected | DEFENDED |
| AC-MFA-04 | U9 SR-022 | Old code set | Use after regeneration | Rejected, new set works | As expected | DEFENDED |
| AC-MFA-05 | race | 8 concurrent verifies / recoveries | gather | Exactly one succeeds | One | DEFENDED (fake repo; DB atomicity NOT RUN) |
| AC-MFA-06 | cross-user | Attacker's valid code on victim's challenge | verify | Rejected | Rejected | DEFENDED |
| AC-MFA-07 | uniform errors | Unknown / expired challenge | verify | Same error | MfaChallengeInvalid | DEFENDED |
| AC-AUTHZ-01 | D1 U3 C-12.4 | Manager/Viewer | Every permission not in their seed | Deny | All denied | DEFENDED (live HTTP route sweep NOT RUN) |
| AC-AUTHZ-02 | O1 U31 SR-050 | Manager | Foreign `account_id` | ACCOUNT_NOT_GRANTED | Denied | DEFENDED |
| AC-AUTHZ-03 | U30 SR-057 | Missing scope id | decide | OBJECT_REQUIRED | Denied | DEFENDED |
| AC-AUTHZ-04 | U31 | view-only / frozen / no-trade grants | decide with requires_trade | Denied with distinct reasons | As expected | DEFENDED |
| AC-AUTHZ-05 | U4 SR-055 | Forged role | Build snapshot | ValueError | ValueError | DEFENDED (role-change route NOT RUN) |
| AC-AUTHZ-06 | U32 | Demoted manager | New snapshot | Denied | Denied | DEFENDED (live-session refresh path NOT RUN) |
| AC-AUTHZ-07 | U19 C-2.9 | Viewer | Denied action | `rbac.denied` audit | Emitted | DEFENDED |
| AC-STEP-01 | U18 SR-025 | Elevated session | Other session / other action class / forged class name | StepUpRequired | Refused | DEFENDED |
| AC-STEP-02 | U18 | Grace window | Replay same code to extend window | Refused, window not extended | Refused | DEFENDED |
| AC-STEP-03 | U18 | Other user's TOTP code | step_up | StepUpCodeInvalid | Refused | DEFENDED |
| AC-STEP-04 | U18 | Unknown session | step_up | StepUpRequired | Refused | DEFENDED |
| AC-INV-01..04 | U12 SR-027 | Guessing, expired, reused, owner role | invite service | Uniform reject; owner not invitable | As expected | DEFENDED (fake repo) |

## NOT RUN (no observed result; open on #298)

| Area | Cases | Why |
|---|---|---|
| WS attacks | pre-`auth_ok` subscribe; `auth` frame replay; socket across revocation; topic injection (U13) | Needs gateway harness; not attempted here |
| Audit attacks | UPDATE/DELETE as app role, trigger drop, crafted migration, chain verifier, silent-action (U14, U17, U19, U20) | Needs real Postgres roles; integration stack not available to this run |
| Real DB checks | Argon2id params from DB row; atomic MFA/recovery consume; lockout owner alert (SR-016) | Fakes only here |
| HTTP RBAC sweep | Every admin/owner route as Manager/Viewer; body/query/path account_id; list probes; self-service `user_id` (D5); role change with live session | Needs full app wiring |
| CSRF token negative test | SR-152 "CSRF token absent/invalid" | Blocked by #2090 (no double-submit token exists) |
| Invite over HTTP | Acceptance by different identity; pre-elevated invite (SR-027) via API | Not attempted |
| Observability | Which metric/audit row/alert each attack triggers | Not recorded |

## Findings

- **F-1 (design gap, STRIDE: Tampering/CSRF, severity Medium, owner: Architect; tracked as #2090,
  a real deviation from SR-041):** the issue and X01 assume a CSRF double-submit token. No such token exists in `candleviewer/auth/` or `api/`; the only
  CSRF controls are SameSite=Strict plus the Origin allow-list on cookie refresh (AC-CSRF-01/02/04).
  State-changing routes require a bearer header, which is not ambient. Residual risk acceptable only if
  that stays true; needs confirmation. Maps to TB-4.
  **Status: fixed by PR #TBD (#2090)** — SR-041 double-submit token (`cv_csrf` cookie +
  `X-CSRF-Token` header, session-bound, rotated at login/refresh) enforced on every state-changing
  request, with the Origin allow-list kept (AC-CSRF-06..09). Live once the middleware is wired in
  `app.py` (pending shared-hotspot ack).
- **F-2 (design decision, Low-Medium):** AC-SES-06 above.
- No P0/P1 finding. `docs/plan/32-risk-register.md` and sign-off comment are not done in this PR.
