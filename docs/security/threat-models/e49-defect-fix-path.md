# E49 — STRIDE threat model: the defect-fix and hotfix path, and its test tooling

Version 1.0 · 2026-10-04 · Ticket E49-X01 · Owner: Security engineer · Co-owner: Architect · Approver: basiltt (Owner)
Classification: **Internal/Confidential** — enumerates weaknesses; stays in the private repository, never included in
any artefact leaving the tailnet. E48's GA readiness pack references it by path only.

Format follows `docs/security/threat-models/e09-auth-rbac.md` and `docs/plan/threat-models/E05-design-system.md`.
Feature-epic threat surfaces (E09 auth, E08 exchange, E16 recorder, ...) are referenced, not re-modelled.

## 1. Scope and assets

E49's risk is the **process** by which many fixes reach the GA candidate under time pressure, plus tooling it adds.

| ID | Boundary / asset | Notes |
|---|---|---|
| TB-F1 | Fix PR -> merge queue (normal and hotfix lane, `01-sdlc-and-branching.md` §7/§8) | approvals, required checks |
| TB-F2 | Triage automation (E49-T01) and its write-scoped token | issue state, sign-off comments, SLA labels |
| TB-F3 | Test-only machinery: state-injection harness (E49-Q04), regression pack accounts (E49-Q01) | control-bypass capability by design |
| TB-F4 | Evidence artefacts: bug bodies, charter recordings, Playwright traces, HARs, screen-reader recordings, design-QA screenshots, SCR-156 diagnostics bundle | may capture secrets |
| TB-F5 | Accepted-risk register and expiry (E49-T03), design-QA exceptions (E49-D*) | decider/date integrity |
| TB-F6 | S26 change freeze | policy, not code |

Inherited always-security list (`02-definition-of-ready-done.md` §8): auth/RBAC, OMS order placement, API-key
storage, withdrawal settings, fan-out native-SL invariant. Any burn-down PR touching these is `security`-labelled
whether or not the label was applied.

## 2. Data classification per artefact

| Artefact | Class | Scrubbing control (mandatory before attach/publish) |
|---|---|---|
| Bug body / comments | Internal; may hold pasted secrets | E49-T01 intake secret-scan (gitleaks patterns) rejects/redacts; reporter template forbids keys/balances |
| Charter recordings (E49-Q02) | Confidential | run against demo env with seeded accounts only; recording blanked on key-entry screens; reviewed before retention |
| Playwright traces / videos / HARs (E49-Q01) | Confidential | tracing config strips `Authorization`, `Cookie`, `X-BAPI-*`, TOTP fields; CI step scans trace zip with secret scanner and fails the job on hit; retention 14 days |
| Screen-reader recordings (E49-Q03) | Confidential | demo accounts only; masked secrets must not appear in the accessibility tree (see T-I5) |
| Design-QA screenshots (E49-D*) | Internal | fixture data only; account ids/balances are synthetic |
| SCR-156 diagnostics bundle | Confidential | server-side redaction allow-list (fields are opt-in, not opt-out); bundle verified against redaction tests before inclusion in a bug |
| This model | Internal | private repo only |

Rule: **no artefact is generated against live credentials.** Live-account evidence is described in words, not attached.

## 3. STRIDE threats

Owners are roles (`33-raci.md`). "Verified by" is the ticket that checks the control; abuse cases (§4) are executed
by **E49-X02**. Detective signals are listed in §7.

### 3.1 Spoofing

| ID | Threat | Control | Implemented / verified by | Owner |
|---|---|---|---|---|
| T-S1 | Triage automation token used (or stolen) to forge issue state, sign-off comments or Done transitions | Token is least-privilege, scoped to issues/projects of this repo, no PR-approve or merge scope; sign-off comments must come from a human CODEOWNER login (automation comments carry a distinct bot marker and never satisfy a sign-off check); token rotated at GA cut | E49-T01 / E49-X02 (AC-1) | Security engineer |
| T-S2 | A regression-pack test account reused with elevated privileges (Owner-role test user used for Manager-scoped checks, so RBAC regressions pass falsely) | One fixed account per role, roles asserted at test start; accounts exist only in seeded demo stack and are rejected by production config; no shared password between roles | E49-Q01 / E49-X02 (AC-2) | QA lead |
| T-S3 | Agent-authored PR impersonates a reviewer or claims "approved by Security" in its body | `pr-metadata` requires approvals from the GitHub review API, never body text; agents never approve (CLAUDE.md §9) | existing C-9.1 `pr-metadata` / E49-X02 | Architect |

### 3.2 Tampering

| ID | Threat | Control | Implemented / verified by | Owner |
|---|---|---|---|---|
| T-T1 | Fix merged without required approvals under schedule pressure | Branch protection + `enforce_admins`, 2 approvals, merge queue; no schedule exemption; board drift detection (E01-Q02) | E01-T07/T08, E49-X02 (AC-3) | Architect |
| T-T2 | Hotfix path used to bypass the merge queue or checks | Hotfix lane is expedited ordering only: second reviewer and all required checks are never waived (`01-sdlc` §8); `hotfix/*` branch must target a prod tag and carries an incident note | E49-X02 (AC-4) | Architect |
| T-T3 | A failing regression test weakened, skipped or deleted instead of fixing the defect | CI gate rejects `.skip/.only/xfail`, lowered coverage or moved bench baselines (AGENTS.md §8); a diff that modifies an existing assertion needs reviewer note "assertion change justified" | E49-Q01 / E49-X02 (AC-5) | Reviewer / QA lead |
| T-T4 | "Cosmetic" copy fix alters a safety warning (SL, kill switch, live-enable, withdrawal text) | Safety strings registered in the copy spec (E49-D03); any diff touching them is `security`-labelled and needs Security engineer approval; golden-string test | E49-D03, E49-S06 / E49-X02 (AC-6) | Security engineer |
| T-T5 | Incomplete fix: one instance of an RBAC or SL bypass closed, siblings left (also EoP) | Related-exposure review (checklist item 3); negative-authorisation test per route/topic in the family | E49-S01/S02 / E49-X02 (AC-7) | Security engineer |
| T-T6 | Fix-forward edits an applied migration or `machine_hashes.lock` out of order | Existing hooks and CI single-head check (C-5.3/C-5.4) | existing gates | Architect |

### 3.3 Repudiation

| ID | Threat | Control | Implemented / verified by | Owner |
|---|---|---|---|---|
| T-R1 | Accepted risk re-decided or extended with no named decider or date | Register entry requires decider, date and expiry; expired entries fail CI (E49-T03) | E49-T03 / E49-X02 | Security engineer |
| T-R2 | Bug closed with no guard test and no recorded exemption reason | Closure requires linked guard test or `no-guard-reason` field with approver; metric `bugs_closed_without_guard_total` must stay 0 | E49-T01 / E49-X02 | QA lead |
| T-R3 | Design-QA exception recorded with no owner | Ledger row requires owner and expiry; ledger lint | E49-D01 | Design lead |
| T-R4 | Emergency fix merged with no incident note | Hotfix PR template requires incident-note link; merge-forward checked same day | `01-sdlc` §8 / E49-X02 | Release manager |

### 3.4 Information disclosure

| ID | Threat | Control | Implemented / verified by | Owner |
|---|---|---|---|---|
| T-I1 | Bug bodies, charter recordings, traces, HARs, SR recordings, design screenshots capture keys, tokens, balances or live account ids | Per-artefact scrubbing in §2; CI trace scan; demo-only evidence rule | E49-T01, E49-Q01-Q03 / E49-X02 (AC-8) | Security engineer |
| T-I2 | 403/404 copy rewrite reveals existence of admin resources (distinguishable responses) | Unauthorised and non-existent resources return an identical body and status class for non-owners; copy lint | E49-S06 / E49-X02 (AC-9) | Security engineer |
| T-I3 | Error-message rewrite exposes internal detail (stack, SQL, hostnames, ids) | Errors map to RFC 7807 with stable codes only at the HTTP edge; snapshot test for each rewritten string | E49-S06 / E49-X02 (AC-10) | Backend lead |
| T-I4 | SCR-156 diagnostics bundle contains unscrubbed data | Allow-list redaction; test that seeds secrets and asserts absence | E49-S05 / E49-X02 (AC-11) | Security engineer |
| T-I5 | Assistive technology exposes masked secret values via the accessibility tree | Masked fields use no `value`/`aria-label` containing the secret; AT test hand-off | E49-Q03 / E49-X02 (AC-12) | Frontend lead |

### 3.5 Denial of service

| ID | Threat | Control | Implemented / verified by | Owner |
|---|---|---|---|---|
| T-D1 | A fix regresses the rate-limit governor or reconnect backoff, causing self-inflicted exchange throttling (RSK-013) | Governor and backoff tests are mandatory checks on burn-down PRs touching those modules; E46 budget checks; stop/cancel/SL reserve test unchanged | E46 / E49-X02 (AC-13) | Backend lead |
| T-D2 | Change freeze blocks a genuine P0 fix | Freeze admits P0/P1 via the hotfix review path (§6); unavailable-approver rule | §6 / E49-X02 (AC-14) | Release manager |
| T-D3 | Triage automation SLA job floods issues or board (self-DoS of the process) | Rate-limited, idempotent updates; dry-run mode | E49-T01 | QA lead |

### 3.6 Elevation of privilege

| ID | Threat | Control | Implemented / verified by | Owner |
|---|---|---|---|---|
| T-E1 | State-injection harness (E49-Q04) reaches a production build | (a) **production-build assertion**: CI greps the production bundle and Python wheel/image for harness symbols and fails on any hit; (b) **test-environment configuration gate**: harness hooks load only when `CV_ENV=test` AND an explicit non-default flag is set, and startup refuses (fail closed) if either is combined with `live`/`demo` credentials | E49-Q04 / E49-X02 (AC-15) | Architect |
| T-E2 | Test-environment server hooks enabled in production configuration | Production config schema rejects unknown/test keys; config-diff check in release PRR | E49-Q04 / E49-X02 (AC-16) | Architect |
| T-E3 | Incomplete RBAC fix (see T-T5) | Checklist items 2, 3 | E49-S01 / E49-X02 (AC-7) | Security engineer |
| T-E4 | A burn-down fix removes or bypasses the native SL on any order path | Every order path keeps an explicit native-SL assertion; orders without native SL counted and alerted at >0 | E49-S01 / E49-X02 (AC-17) | Backend lead |
| T-E5 | Triage token scope grows over time (permission creep) | Weekly scope drift check (E01-Q02 pattern) | E49-T01 | Security engineer |

## 4. Abuse cases (executable by E49-X02)

Each has a precondition, an action and an expected refusal or expected absence.

| ID | Precondition | Action | Expected result | Control |
|---|---|---|---|---|
| AC-1 | Triage token available to the automation | Use it to post a "Security sign-off: approved" comment, approve a PR and merge | Sign-off check ignores the bot comment; approve/merge calls return 403 | T-S1 |
| AC-2 | Regression-pack seeded accounts | As the Manager test user, call an Owner-only route and an unassigned-account route | 403 for both; role assertion at test start passes | T-S2 |
| AC-3 | Open PR with 1 approval and a red required check | Attempt merge via UI/API as repo admin | Refused (enforce_admins, merge queue) | T-T1 |
| AC-4 | hotfix/* PR with a failing check | Request the expedited lane | Lane affects ordering only; merge refused until checks are green and the second reviewer approves | T-T2 |
| AC-5 | PR adding .skip, xfail, a lowered coverage threshold or an edited baseline | Open PR | CI fails; checklist item 6 blocks | T-T3 |
| AC-6 | PR editing a registered safety string (SL, kill switch, live-enable, withdrawal) | Open PR labelled type/chore only | security-review label enforced; golden-string test fails until Security approves | T-T4 |
| AC-7 | Fixed RBAC bypass on route R | Enumerate sibling routes/WS topics in the same module | Every sibling has a negative-authorisation test; forbidden-role and cross-account (IDOR) calls refused | T-T5, T-E3 |
| AC-8 | Test run with an Authorization header and X-BAPI-API-KEY canary | Produce trace, HAR and video; run scrub step | Canary absent from every uploaded artefact; CI scan fails if present | T-I1 |
| AC-9 | Existing admin resource and a non-existent one | Request both as a Manager | Identical status and body shape | T-I2 |
| AC-10 | Forced internal error (DB down) | Call the rewritten endpoint | Stable code only; no stack, SQL, host or id in body | T-I3 |
| AC-11 | Seeded secrets in app state | Generate the SCR-156 diagnostics bundle | Bundle contains none of the seeded values | T-I4 |
| AC-12 | Masked secret field rendered | Dump the accessibility tree | No secret value or substring present | T-I5 |
| AC-13 | Burn-down PR touching governor/backoff | Run governor and reconnect tests under 10006/10018 fixtures | Backoff with jitter holds; stop/cancel reserve intact | T-D1 |
| AC-14 | Freeze active, simulated P0 | Submit fix via hotfix path with approvers unavailable | Follows section 6 fallback; merge only after named approvals | T-D2 |
| AC-15 | Production build artefacts (web bundle, desktop app, API image) | Search for harness symbols/endpoints; start API with harness flag while CV_ENV is live or demo | No harness code found; startup refuses with explicit error | T-E1 |
| AC-16 | Production config containing a test-only key | Start the API | Config validation rejects it | T-E2 |
| AC-17 | Order path touched by a burn-down fix | Submit a position-opening order in tests | Native SL attached; unprotected-order counter stays 0 | T-E4 |

## 5. Burn-down PR control checklist (R5 train)

Reviewers apply this in addition to the PR template; the PR lists each item as done or N/A with a reason.

1. **Always-security clause:** touches auth/RBAC, OMS order placement, key storage, withdrawal settings or fan-out SL? Then `security-review` label and Security engineer approval, even if unlabelled (`02-definition-of-ready-done.md` section 8).
2. **Negative-authorisation tests** for every RBAC fix: forbidden role and cross-account case.
3. **Related-exposure review:** list sibling routes, topics and code paths with the same flaw; each fixed or ticketed.
4. **Artefact scrubbing:** any attached trace, HAR, screenshot or recording passes the scrubbing control in section 2.
5. **No weakening of safety copy:** registered safety strings unchanged unless Security approved.
6. **No weakened tests:** no skip/xfail, lowered threshold or moved baseline; changed assertions justified.
7. **Governor/backoff:** changes near rate limits or reconnect run their suites and E46 budget checks.
8. **Native SL assertion** present on any order path touched.
9. **Closure hygiene:** linked guard test or recorded exemption with approver.
10. **Error/403/404 copy:** no internal detail, no existence leak.
11. **Harness boundary:** no harness symbol imported outside test code.

## 6. Freeze policy security clause (S26)

- The freeze restricts *scope*, never *review*. "Urgent" never means "unreviewed".
- During the freeze only P0, and P1 with a documented GA-blocking rationale, may merge, via the hotfix review path of `01-sdlc-and-branching.md` section 8: expedited lane, all required checks, second reviewer not waived.
- Named approvers: one CODEOWNER for the path (Architect or delegate) plus the Security engineer when checklist item 1 applies; the Owner approves the freeze exception itself.
- **Approver unavailable:** the approver is paged directly; with no response in 2 hours the designated deputy in `33-raci.md` approves. If no eligible human is reachable the fix does not merge: mitigate operationally (kill switch, feature disabled) and escalate to the Owner. No approver is ever substituted by an agent or automation, and an author never approves their own PR.
- Every freeze merge carries the incident note and is merged forward to `main` the same day.

## 7. Detective signals

- `bugs_closed_without_guard_total` must stay 0 (E49-T01).
- Orders submitted without a native SL: counted, alert at > 0.
- `authz.denied` reviewed for spikes during burn-down (an over-correcting RBAC fix).
- Weekly triage-token scope drift check; harness-symbol scan on every release candidate.

## 8. Tabletop walkthrough

Performed as a heuristic walk-through by the implementing agent in the Security engineer / QA lead / engineer roles
(agent-delivery adaptation); the Owner reviews the output. Two scenarios, end to end:

1. **Rushed P0 fix during freeze**, touching an OMS path, with the Security engineer offline. Walk: hotfix branch,
   PR, checklist items 1, 6, 8, approver paging, 2 h fallback, deputy, expedited merge-queue lane, merge-forward and
   incident note. *Finding:* the fallback needed a time bound and an explicit "no agent substitutes" statement;
   both added to section 6.
2. **Playwright trace containing an Authorization header** attached to a bug. Walk: intake scan, CI trace scan,
   redaction, retention. *Finding:* free-form attachments were possible; section 2 now requires scrub-before-attach
   and a CI scan on trace archives, and live-account evidence is described, never attached.

Outcome: controls are usable under pressure; two wording gaps fixed; no unresolved control gaps.

## 9. Register impact

No new numbered risk is added (the register's count invariant, `32-risk-register.md` section 10.1.1, is untouched).
Threats map to existing entries: RSK-013 (T-D1), RSK-016 (T-E4), RSK-018 (T-I1, T-I4), RSK-020 (T-T5, T-E3, T-S2),
RSK-029 (T-T6), RSK-051 (T-S1, T-S3, T-T1, T-T2, T-R1 to T-R4). Harness escape (T-E1/T-E2) is covered by two
independent preventive gates and recorded under RSK-020/RSK-051. If E49-Q04 cannot land the production-build
assertion (AC-15) before the harness merges, raise a new entry (owner Security engineer, trigger: harness merged
without the AC-15 gate) rather than accept the gap. Any threat later found without a control is escalated as an
accepted risk with an expiry (`04-security-program.md`, E49-T03).

## 10. References

`04-security-program.md`, `02-definition-of-ready-done.md` 2.1/6.2/8, `01-sdlc-and-branching.md` 7/8,
`03-testing-strategy.md` 10/11.4, `32-risk-register.md`, `33-raci.md`, E49-T01, T03, Q01, Q03, Q04, X02.
