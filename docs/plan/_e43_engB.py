# -*- coding: utf-8 -*-
"""E43 engineering part B: T07-T12, K01, S01-S02."""
import json, io, os

T = []
def t(**k):
    k.setdefault("phase", "P4 Backtesting & Scripting")
    k.setdefault("milestone", "R4 Live enablement")
    T.append({kk: k[kk] for kk in ["key","kind","title","labels","component","phase","sprint",
        "priority","perspective","risk","estimate","parent","blocked_by","milestone","body"]})

DOD = """## Definition of Done
- [ ] Acceptance criteria verified by an automated test or a recorded procedure.
- [ ] Coverage threshold met for touched packages (>= 85% backend/engine, >= 80% frontend; M2/M18/M19 >= 90%).
- [ ] `docs/plan/04-security-program.md` SR traceability and `docs/plan/03-testing-strategy.md` SR-150 table updated.
- [ ] SAST/SCA/secrets scans clean or triaged with a section 16.2 exception carrying an expiry.
- [ ] Security engineer review comment posted (mandatory for `area/auth-rbac`).
- [ ] QA sign-off comment with pass/fail per scenario.
- [ ] Demo or before/after evidence recorded.
- [ ] PR(s) merged via the merge queue with 2 approvals incl. a code-owner; required checks green.
"""

t(key="E43-T07", kind="Task",
  title="Generate, sign and publish SBOMs for backend, web bundle and desktop app",
  labels=["type/chore","area/auth-rbac","priority/p1","security"],
  component="infra", sprint="Sprint 20", priority="P1 High", perspective="Ops",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-T05","E43-T02"],
  body="""## Context
SR-133 requires a CycloneDX SBOM for **the backend, the web bundle and the Electron app** on every release, attached to the release artefacts, with SBOM diffs reviewed between releases; a missing SBOM blocks release (`docs/plan/04-security-program.md` section 12.1). SR-137 requires that release container images and desktop artefacts are built in CI - never from a developer machine - and that images are signed with cosign plus a provenance attestation; an unsigned image blocks deploy.

R4 is the first release that ships to prod (live), so this is the release where "blocks release" becomes real. The SBOM is also the artefact that makes a future CVE answerable in minutes rather than days: when an advisory lands against a transitive package after `1.0.0` is live, the SBOM diff tells the Owner whether the running build contains it.

## Scope / Deliverables
- **SBOM generation** (Syft/CycloneDX) for three artefacts, run in CI against the frozen graph from E43-T05:
  1. backend image (`services/api`),
  2. web bundle (`apps/web` production build),
  3. Electron desktop artefact (`apps/desktop`, including its bundled Chromium/Node runtime versions).
- Attach each SBOM to the release artefacts; publish alongside the tag.
- **SBOM diff job**: compare against the previous release's SBOM and produce a human-readable added/removed/version-changed report, posted to the release ticket; a new component appearing without a corresponding SR-135 justification is flagged for review.
- **Signing** (SR-137): cosign-sign the container image with a provenance attestation; verify the signature in the deploy path so an unsigned image cannot be deployed. Record the key custody model (keyless/OIDC preferred).
- **Desktop artefact signing status**: record whether code signing is operational (SR-115); if not, assert that auto-update remains disabled and updates are manual, and file the follow-up.
- **Release gate wiring**: `sbom` and `cosign-verify` become blocking steps in the release workflow; document them in `docs/plan/07-release-and-prr.md` release checklist and in `docs/plan/04-security-program.md` section 12.3.
- Store SBOMs where the Owner can retrieve them without a developer (documented path in the runbooks).

## Out of scope
- Vulnerability triage itself (E43-T05); container image hardening (E43-T05); the pen-test evidence pack (E43-X07, which references these artefacts).

## Acceptance criteria
```gherkin
Scenario: All three SBOMs are produced and attached
  Given a release build at the freeze tag
  When the release workflow completes
  Then a CycloneDX SBOM exists for the backend image, the web bundle and the desktop artefact
  And each is attached to the release artefacts and retrievable from the documented path

Scenario: Missing SBOM blocks the release
  Given SBOM generation fails or produces an empty document for any artefact
  When the release workflow runs
  Then the release is blocked with a message naming the artefact

Scenario: Unsigned image cannot deploy
  Given a container image without a valid cosign signature and provenance attestation
  When the deploy path runs
  Then verification fails and deployment is refused

Scenario: SBOM diff surfaces an unjustified new dependency
  Given a new runtime component appears relative to the previous release SBOM
  Then the diff report lists it and flags the absence of an SR-135 justification for review
```

## Technical notes / design
- CycloneDX JSON, schema version pinned; include component `purl`, version, license and hashes so the document is usable for both CVE matching and license audit.
- The desktop SBOM must capture the bundled Chromium and Node versions explicitly, because those are the components most likely to carry a High CVE and the least likely to appear in a JS lockfile.
- cosign keyless (OIDC) signing preferred (SR-141 prefers OIDC federation over long-lived tokens); if a key is used, it lives as an environment secret with protection rules and required reviewers.
- Verification runs in the deploy script under `infra/scripts/`, not only in CI, so a manual deploy is equally gated.

## Test plan
- **CI**: SBOM generation job for each artefact with an assertion on component count > 0 and schema validity; a fixture run with generation disabled asserting the release gate fails.
- **Integration**: cosign verify against a correctly signed image (pass) and a tampered image (fail).
- **Manual**: Owner retrieves an SBOM from the documented path without developer assistance (part of the PRR walkthrough).
- Coverage target: N/A (pipeline artefact); the gate behaviour is the tested surface.

## Security notes
Threats (`04-security-program.md` section 6.13): supply-chain substitution of a release artefact, and inability to answer "are we affected?" after a disclosure. Controls: SBOM per artefact, signed images with provenance, verification in the deploy path, diff review. Data classification: SBOMs are not secret but do disclose the dependency graph - store them with the release artefacts under the same access control as the repository, not publicly. Security review required.

## Accessibility notes
N/A - no UI surface. (The documented retrieval path must be plain text instructions usable without a GUI.)

## Performance notes
SBOM generation and signing add to release-pipeline duration only; budget <= 5 minutes added to the release workflow, recorded on the ticket.

## Observability
Metric `cv_sbom_published_info{artefact,release}` and `cv_release_signature_verified{result}`. A release without a published SBOM is visible as a missing series, which the PRR checklist checks.

""" + DOD + """
## Dependencies
- **E43-T05** supplies the frozen, license-clean dependency graph the SBOM describes.
- **E43-T02** supplies the hardened, assertion-gated desktop artefact being described and (conditionally) signed.

## Branch
`chore/e43-security-sbom-signing`. PR size guidance: (1) SBOM generation + attachment, (2) diff job, (3) cosign signing + deploy-path verification.

## References
- `docs/plan/04-security-program.md` SR-115, SR-133, SR-135, SR-137, sections 12.1, 12.3.
- `docs/plan/07-release-and-prr.md` (release checklist, PRR gates).
- `docs/plan/20-architecture.md` section 8.3 build, artefacts and release.
- ADR-0013 CI pipeline.""")

t(key="E43-T08", kind="Task",
  title="Authenticated OWASP ZAP full scan against staging with triage",
  labels=["type/chore","area/auth-rbac","priority/p0","security","qa"],
  component="infra", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=3, parent="E43",
  blocked_by=["E43-T01","E43-T03","E43-T04","E43-T09"],
  body="""## Context
`docs/plan/04-security-program.md` section 12.1 requires OWASP ZAP baseline **and authenticated full scan** against a running app in an ephemeral environment, nightly and pre-release, with new High alerts blocking the release and baseline Mediums triaged. R4 needs the full scan executed deliberately and triaged **before** the pen-test window opens on 2027-07-05, so that the tester's days are spent on logic and authorisation flaws rather than on findings an automated scanner would have caught for free.

An authenticated scan of this application is not trivial: it must log in with password + TOTP, hold a server-side session, carry a rotating double-submit CSRF token, respect `SameSite=Strict` and an `Origin` allowlist, and must be prevented from firing destructive requests at the OMS. Getting that harness right is most of the work.

## Scope / Deliverables
- **Scan harness**: a ZAP authentication script that performs password + TOTP login against the staging demo environment using a dedicated scanner identity per role (Owner, Manager, Viewer), maintains the session cookie, extracts and re-sends the CSRF token, sets an allowlisted `Origin`, and detects logged-out state so the scan re-authenticates rather than silently scanning as anonymous.
- **Scope and exclusions**: scan the full authenticated surface of `/api/v1` and the web app. Exclude destructive operations from **active** attack (order placement/amend/cancel, kill-switch activation, user deletion, retention purge, audit export) - these are covered by the pen-test and by targeted negative tests instead; the exclusion list is explicit, justified and recorded, not a wildcard.
- **Passive + active scan** with the full rule set; run per role so that authorisation-relevant differences surface.
- **Triage**: every High and Medium alert triaged with a disposition (true positive -> ticket with a regression test; false positive -> recorded justification plus a ZAP rule tuning entry). The tuning file is committed so future runs are comparable.
- **CI wiring**: nightly baseline scan plus a pre-release authenticated full scan, both publishing reports as artefacts; new High alerts block the release (already required by section 12.1).
- **Report**: the pre-freeze full-scan report archived as an input to the pen-test brief and to E43-X07's evidence pack.

## Out of scope
- The manual pen-test itself (E43-X02); load/DoS testing (E43-Q04); the negative-test E2E suite (E43-Q03).

## Acceptance criteria
```gherkin
Scenario: The scan is genuinely authenticated
  Given the ZAP authenticated full scan runs as the Owner scanner identity
  Then the scan log shows authenticated responses for protected routes
  And the run asserts that fewer than a configured threshold of requests received the unauthenticated redirect or 401
  And the session is re-established automatically if it is invalidated mid-scan

Scenario: No new High alerts before the freeze
  Given the pre-freeze authenticated full scan
  Then there are zero new High alerts relative to the tuned baseline
  And every Medium alert has a recorded disposition

Scenario: Destructive operations are not fired
  Given the exclusion list
  When the active scan runs
  Then no order is placed, amended or cancelled, no user is deleted, the kill switch is not activated and no retention purge is triggered
  And the staging OMS records no scanner-originated orders

Scenario: A regression is caught nightly
  Given a change that reintroduces a previously fixed alert
  When the nightly scan runs
  Then the alert reappears in the report and the release gate blocks the next release
```

## Technical notes / design
- TOTP for the scanner identity is generated by the harness from a dedicated seed stored as an environment-protected CI secret; the identity has no live capability and exists only in staging (SR-140: no production credentials in CI).
- CSRF handling: a ZAP HTTP sender script reads the double-submit cookie and injects the `X-CSRF-Token` header on every state-changing request; if E43-T03 rotates the token, the script re-reads it after each response.
- Per-role runs use separate contexts so that "access to a route" differences between roles show up as alerts rather than being averaged away.
- Reports: HTML for humans, JSON for the diff/gate; both attached to the run and to the evidence pack.

## Test plan
- **Harness self-test**: a canary route that is only reachable when authenticated; the run fails if the canary is not reached.
- **Negative control**: a deliberately vulnerable canary endpoint in a non-shipped test profile, asserting the scanner detects it (so a silent misconfiguration cannot masquerade as a clean result).
- **Integration**: run against staging pre-freeze; compare against the tuned baseline.
- **Verification of exclusions**: assert the staging OMS order table contains no rows attributable to the scanner identity after a run.
- Coverage target: N/A; the artefact is the report plus the tuning file.

## Security notes
Threats: the scan itself is a privileged actor - a misconfigured active scan against a trading application could place or cancel orders, so the exclusion list is a safety control, not a convenience. The scanner identity is a real credential and is scoped, environment-protected and rotated after the R4 window. Findings feed the pen-test brief. Security review mandatory.

## Accessibility notes
N/A - no UI surface. (ZAP alerts touching form labelling are cross-checked against E43-Q05's axe-core audit rather than fixed here.)

## Performance notes
The full authenticated scan runs against staging only and must not run against prod; it is expected to saturate staging, so it is scheduled outside any concurrent load test (E43-Q04) to keep both results interpretable.

## Observability
Metric `cv_zap_alerts_total{risk,rule}` published per run; the report artefact retained per release. A rising Medium count is a code-health signal even when nothing blocks.

""" + DOD + """
## Dependencies
- **E43-T01** (CSP), **E43-T03** (session/CSRF - the harness depends on the final token model), **E43-T04** (rate limiting - the scan must be allowlisted or throttled so lockout does not abort the run), **E43-T09** (RBAC declarations - per-role contexts depend on them).

## Branch
`chore/e43-security-zap-fullscan`. PR size guidance: (1) auth + CSRF harness, (2) scope/exclusions + per-role contexts, (3) CI wiring + tuning file.

## References
- `docs/plan/04-security-program.md` sections 12.1, 12.3, 13.2, 13.4.
- `docs/plan/03-testing-strategy.md` (security testing layer).
- `docs/plan/22-api-openapi.yaml`; `docs/plan/23-ws-protocol.md`.""")

t(key="E43-T09", kind="Task",
  title="Complete RBAC capability declarations and matrix-driven authorisation coverage",
  labels=["type/chore","area/auth-rbac","priority/p0","security"],
  component="api", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=5, parent="E43", blocked_by=["E09","E43-X01"],
  body="""## Context
Authorisation is pen-test scope item 2 and the single most likely source of a High finding in a multi-user trading product: horizontal escalation (Manager A reaching Manager B's accounts) and vertical escalation (Manager reaching Owner functions) across **every route, WS topic and admin screen**, plus IDOR on account, order, rule, journal and audit objects, plus grant-revocation timing (`docs/plan/04-security-program.md` section 13.2 item 2).

Three requirements make this mechanically checkable rather than a matter of reviewer diligence: SR-017 (*every* HTTP route and WS topic MUST declare a required capability; a route registered without a declaration MUST fail application start-up - deny-by-default), SR-018 (a test enumerates all registered routes and topics and asserts the expected allow/deny outcome per role; adding a route without updating the matrix fails CI), and SR-151 (authorisation tests MUST be matrix-driven: role x route/topic x account-grant scenario). The Semgrep rules `cv-route-without-capability` and `cv-query-without-scope` back the same invariants at review time.

By R4 the route surface has grown through ten epics. This ticket proves the invariant holds across all of it, and closes the gaps it finds.

## Scope / Deliverables
- Enumerate every registered FastAPI route (`services/api/candleviewer/api/`) and every WS topic (`docs/plan/23-ws-protocol.md`) and assert a capability declaration exists; make a missing declaration a **start-up failure**, not a warning.
- Build/complete the **matrix test** (SR-018/SR-151): for each role (Owner, Manager, Viewer) x each route/topic x each grant scenario (granted account, non-granted account, no accounts, revoked-mid-session), assert the expected allow/deny outcome. The expected matrix is generated from `docs/plan/04-security-program.md` section 7.2 capability matrix and drift between code and doc fails CI.
- **Object-level authorisation (IDOR)**: for every account-scoped entity - orders, positions, trade groups, rules, journal entries, audit entries, keys, profiles, layouts - assert that a request for another user's object returns the same response as for a non-existent object (no existence oracle), and that `cv-query-without-scope` has no suppressions.
- **Grant-revocation timing**: revoking an account grant takes effect on the next request and terminates affected WS subscriptions; assert the bound, and assert that an in-flight order submitted before revocation is handled per the documented rule rather than silently accepted.
- **Self-service separation** (SR-026): self-service routes (own profile, own password, own TOTP) must not accept a target-user parameter; administrative mutation uses separate owner-only routes. Assert by enumeration.
- **WS authorisation** (pen-test item 6): unauthenticated subscribe, topic guessing and subscribing to another account's private topic all fail; the WS handshake performs the same `Origin` check as REST (with E43-T03).
- Update `docs/plan/04-security-program.md` section 7.2 and `docs/plan/23-ws-protocol.md` if the shipped reality diverged.

## Out of scope
- Changing the RBAC model itself (ADR-0010 is settled); session/CSRF (E43-T03); rate limiting (E43-T04).

## Acceptance criteria
```gherkin
Scenario: An undeclared route cannot start the application
  Given a route registered without a capability declaration
  When the application starts
  Then start-up fails naming the route and no server listens

Scenario: The matrix is exhaustive and drift fails CI
  Given the set of registered routes and WS topics
  When the matrix test runs
  Then every route and topic appears in the matrix for every role and grant scenario
  And a route added without a matrix entry fails the rbac-matrix check

Scenario: Horizontal escalation is impossible
  Given Manager A authenticated with a grant on account S1 only
  When A requests an order, position, rule, journal entry, audit entry or key belonging to account S2
  Then the response is identical to the response for a non-existent object
  And the denial is audited

Scenario: Vertical escalation is impossible
  Given a Manager session
  When any owner-only admin route or WS topic is requested
  Then the request is denied
  And no partial data is returned in the error body

Scenario: Revocation takes effect promptly
  Given a Manager with an active session and an open WS subscription to a granted account
  When the Owner revokes that grant
  Then the next REST request for that account is denied
  And the WS subscription is terminated with a reason frame within the documented bound

Scenario: Self-service routes cannot target another user
  Given a Manager session
  When a self-service route is called with a target-user parameter
  Then the parameter is rejected by schema validation, not silently ignored
```

## Technical notes / design
- Capability declaration is the `capability=` argument on the route decorator, mirrored by `x-rbac` in `docs/plan/22-api-openapi.yaml` (e.g. `/admin/security/summary` declares `permissions: [audit:read], scope: none`); a contract test asserts the code and the spec agree, so the OpenAPI document remains an accurate authorisation reference for the tester.
- Scope resolution goes through `ScopeResolver` (`docs/plan/20-architecture.md` section 3.10): user -> role -> allowed account ids -> allowed key ids, consulted by every REST route and WS subscription. Object-level checks must use the resolver, never an ad hoc query filter.
- No existence oracle: a denied object returns the same status and body shape as a missing object; a test asserts response equality including timing bucket.
- Revocation propagation: a revocation event invalidates cached scope and pushes a termination frame to affected subscriptions; the documented bound is expressed in the acceptance test as a concrete number of seconds taken from the WS protocol doc.
- Error codes: `E_FORBIDDEN` (uniform), `E_SCOPE_REVOKED` on the WS termination frame.

## Test plan
- **Contract**: route/topic enumeration vs capability declarations vs OpenAPI `x-rbac`; matrix generation from section 7.2.
- **Unit**: `ScopeResolver` decisions across grant scenarios incl. empty grants and revoked-mid-request.
- **Integration**: the full role x route x grant matrix executed against a seeded database with two managers, two sub-accounts and one viewer; IDOR probes on every entity type; revocation timing.
- **E2E**: WS unauthenticated subscribe, topic guessing, cross-account subscribe, revocation termination.
- **CI**: `rbac-matrix` as a required check.
- Coverage target: >= 90% on M18 authorisation modules.

## Security notes
Threats (`04-security-program.md` section 5.6, 5.7): elevation of privilege both horizontally and vertically; information disclosure through an existence oracle; stale authorisation after revocation. This is the highest-value hardening ticket in the epic - it is where a Critical finding would most plausibly land. Data classification: account-scoped financial data and audit records. Security review mandatory; E43-X04's abuse cases target this surface.

## Accessibility notes
Denial responses must produce a UI state that explains what happened without leaking whether the object exists; the copy is specified in E43-D03's handoff and verified by E43-Q05.

## Performance notes
Scope resolution is on every request: budget <= 3 ms p95, with the grant set cached per session and invalidated on revocation. The matrix test is large; it must run in CI within the pipeline duration budget - parallelise by role.

## Observability
Metrics `cv_authz_denials_total{role,route,reason}`, `cv_authz_revocation_propagation_seconds`. Audit events for every denial on an admin or order-path route (`04-security-program.md` section 8.2). A denial spike is an attack signal and feeds the SCR-137 posture panel.

""" + DOD + """
## Dependencies
- **E09** Auth, sessions, 2FA & RBAC (the `ScopeResolver` and capability machinery). **E43-X01** STRIDE refresh.
- Feeds **E43-T08** (per-role scan contexts) and **E43-X02** (the tester receives the matrix as a map of what *should* be enforced).

## Branch
`feat/e43-security-rbac-matrix`. PR size guidance: (1) declaration enforcement at start-up, (2) matrix generation + test, (3) IDOR + revocation fixes.

## References
- `docs/plan/04-security-program.md` SR-017, SR-018, SR-026, SR-050..SR-059, SR-151, sections 5.6, 5.7, 7.1, 7.2, 7.3, 13.2 item 2, 14.2.
- `docs/plan/20-architecture.md` section 3.10 `ScopeResolver`, section 3.12 gateway.
- `docs/plan/22-api-openapi.yaml` (`x-rbac`); `docs/plan/23-ws-protocol.md`.
- `docs/plan/21-database-schema.md` `user_roles`, `user_account_access`.
- ADR-0010 auth and RBAC.""")

t(key="E43-T10", kind="Task",
  title="Verify audit-chain integrity, append-only grants and off-box mirroring",
  labels=["type/chore","area/auth-rbac","priority/p0","security"],
  component="api", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=5, parent="E43", blocked_by=["E09","E42"],
  body="""## Context
Pen-test scope item 10 is *audit and non-repudiation*: attempts to modify, delete or forge audit entries and to break the hash chain undetected. The audit log is the mechanism by which the Owner can answer "who did this and when" (security objective O4) across a multi-manager, capital-affecting system, and R4's exit criteria require the chain verified and mirrored (`docs/plan/04-security-program.md` section 13.5).

Requirements: SR-060 (every security- and capital-relevant event recorded per the section 8.2 catalogue), SR-063 (hash chain `hash_n = SHA256(hash_{n-1} || canonical_json(entry_n))` with a deterministic canonical encoding - sorted keys, no whitespace, UTF-8, RFC 3339 microsecond timestamps, genesis = 32 zero bytes; head persisted in `audit_chain_head` and verified on start and nightly), SR-068 (mirrored off-box at least daily to an append-only target; mirror head compared with the local head, divergence raises a **P1** alert), SR-069 (entries never contain secrets, full API keys, session tokens or TOTP codes; payloads redacted through the SR-006 filter **before** hashing; retention indefinite). US-ADMIN-008 adds the database-level requirement: append-only enforced by the grant model (no `UPDATE`/`DELETE` grants), and an attempted mutation is itself recorded.

This ticket verifies all of that against the shipped system and closes gaps - it does not rebuild the audit log (E09/E42 built it).

## Scope / Deliverables
- **Grant model verification**: assert at the database level that the application role holds `INSERT` and `SELECT` on `audit_log` and **no** `UPDATE` or `DELETE`; assert the same for `audit_checkpoints` where applicable; a migration test asserts the grants survive migration.
- **Refused-mutation recording**: an attempted update or delete is refused by the grant model **and the attempt is itself recorded** (US-ADMIN-008 scenario "Immutability") - implement the trigger/exception path that turns a refused mutation into a new appended entry.
- **Chain verification**: implement/verify canonical JSON encoding exactly as specified; verify the chain on start-up and nightly; expose `POST /api/v1/admin/audit/verify` (already in `docs/plan/22-api-openapi.yaml`) returning the verification result **and the position of any break** (US-ADMIN-008 scenario "Integrity verification").
- **Off-box mirror** (SR-068): a daily append-only mirror job, a head comparison, and a P1 alert on divergence; document the mirror target and its access control in the runbooks.
- **Event-catalogue completeness**: audit against section 8.2 that every security- and capital-relevant event is actually written - specifically login events, key events, role/grant changes, limit changes, freeze, flag changes, environment switches, order actions and rule firings. Any missing event is added (backed by the `cv-audit-missing` Semgrep rule on mutation handlers).
- **Redaction before hashing**: a test proving the redaction filter runs before the hash is computed, so a redacted payload still verifies.
- **Export integrity** (US-ADMIN-009): `POST /api/v1/admin/audit/export` produces a signed file, the export itself is audited, and redaction is preserved in the export.
- **Performance**: `GET /api/v1/admin/audit` search over 10 million entries returns the first page in <= 2 s (US-ADMIN-009 NFR) - verified with a generated corpus.

## Out of scope
- The audit log UI (E42 owns SCR-135; E43-D02 adds the integrity states rendered by E43-S02's posture surface).
- Journal/analytics exports (E41).

## Acceptance criteria
```gherkin
Scenario: The database refuses mutation and records the attempt
  Given an attempt to UPDATE or DELETE a row in audit_log using the application role
  Then the database refuses the statement
  And a new audit entry recording the attempted mutation is appended

Scenario: A tampered entry is detected with its position
  Given an audit row is modified directly by a superuser out of band
  When the chain verification runs
  Then verification fails and reports the sequence number at which the chain breaks
  And the failure raises a P1 alert

Scenario: Redacted payloads still verify
  Given an event whose payload contained a secret-shaped value
  Then the stored payload is redacted
  And the chain verifies over the redacted canonical form

Scenario: The off-box mirror is compared daily
  Given the daily mirror job has run
  When the mirror head is compared with the local head
  Then equality is asserted and a divergence raises a P1 alert naming both heads

Scenario: Search at scale meets its budget
  Given ten million audit entries
  When a filtered search by actor, action type, account, severity and time range is executed
  Then the first page returns within two seconds with stable ordering

Scenario: Manager scope is enforced on the audit log
  Given a Manager session
  When the audit log is searched
  Then only entries describing that manager's own actions are returned, enforced server-side
```

## Technical notes / design
- Canonical JSON must be implemented once and shared by the writer, the verifier and the mirror comparator; a property test (Hypothesis) asserts encode/verify stability across key order, unicode, and timestamp precision.
- The genesis entry uses 32 zero bytes; `audit_chain_head` stores the current head and is updated in the same transaction as the insert, so a crash cannot leave head and tail disagreeing.
- Refused-mutation recording is implemented as a database rule/trigger that raises, combined with an application-side handler that appends the attempt entry; the trigger path must not itself be bypassable by the application role.
- Export signing uses the release signing identity or a dedicated audit-export key; the signature covers the redacted content and the filter parameters, so an export cannot be misrepresented as complete.
- Search performance: composite indexes on `(occurred_at, actor_id)`, `(action, occurred_at)` and an account-scoped partial index; keyset pagination for stable ordering.

## Test plan
- **Unit**: canonical encoder property tests; hash chain over synthetic sequences; redaction-before-hash ordering.
- **Integration**: grant assertions against a migrated database; out-of-band tamper detection; refused-mutation recording; mirror comparison incl. an injected divergence; manager-scoped search.
- **Contract**: `/admin/audit`, `/admin/audit/verify`, `/admin/audit/export` against `docs/plan/22-api-openapi.yaml`.
- **Perf**: 10M-entry corpus, first-page latency p95 <= 2 s; chain verification duration recorded and bounded so the nightly job completes.
- **Chaos-adjacent**: verification behaviour when the mirror target is unavailable (must alert, must not block writes).
- Coverage target: >= 90% on M19.

## Security notes
Threats (`04-security-program.md` section 5.7, plus K7/O5 repudiation rows in section 5.1/5.2): tampering with history to conceal an action, and repudiation of an order or a key change. Controls: grant model, hash chain, off-box mirror, redaction, signed exports. Data classification: audit payloads are sensitive metadata about financial actions and must never contain secrets (SR-069). Security review mandatory.

## Accessibility notes
The integrity-failure state is rendered on SCR-136 per E43-D02; this ticket must supply the break position and timestamp in the API response so the UI can state it in text rather than implying it with colour.

## Performance notes
Budgets: audit write adds <= 3 ms p95 to the originating request (it is in-transaction); search first page <= 2 s at 10M entries; nightly verification must complete within its window without starving the write path - verification reads in batches with a bounded rate.

## Observability
Metrics `cv_audit_chain_verify_status`, `cv_audit_chain_verify_duration_seconds`, `cv_audit_mirror_lag_seconds`, `cv_audit_write_failures_total`. Alerts: chain verification failure (P1), mirror divergence (P1), mirror lag beyond one day (P2).

""" + DOD + """
## Dependencies
- **E09** (audit writer, hash chain). **E42** (admin audit screens and endpoints).
- Feeds **E43-S02** (posture panel shows last chain verification) and **E43-X02** (pen-test scope item 10).

## Branch
`feat/e43-security-audit-integrity`. PR size guidance: (1) grants + refused-mutation recording, (2) canonical encoding + verification endpoint, (3) mirror + alerting, (4) search indexes + perf.

## References
- `docs/plan/04-security-program.md` SR-060..SR-069, sections 8.1, 8.2, 8.3, 13.2 item 10, 13.5.
- `docs/plan/11-user-stories.md` US-ADMIN-008, US-ADMIN-009.
- `docs/plan/21-database-schema.md` `audit_log`, `audit_checkpoints`.
- `docs/plan/22-api-openapi.yaml` `/admin/audit`, `/admin/audit/verify`, `/admin/audit/export`.
- `docs/plan/14-screens-catalogue.md` SCR-135, SCR-136.""")

t(key="E43-K01", kind="Spike",
  title="Validate the Tailscale-only boundary assumption from off-tailnet",
  labels=["type/spike","area/auth-rbac","priority/p0","security"],
  component="infra", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-X01"],
  body="""## Context
The entire exposure model of CandleViewer rests on one assumption: **the application is reachable only over Tailscale**. `docs/plan/04-security-program.md` section 6.7 encodes it as SR-045 (Tailscale account with MFA, device approval, key expiry <= 90 days, quarterly device audit), SR-046 (least-privilege ACLs: `tag:manager` reaches only the app port on `tag:trading-host`; `tag:owner` additionally reaches admin/observability ports; no exit node, no subnet routes; ACL file version-controlled and reviewed), SR-047 (backend and all data stores bind loopback or WSL-internal only; a **start-up self-check enumerates listening sockets and refuses to start** on a non-loopback/non-tailnet bind; no Windows `portproxy` or UPnP mapping; verified quarterly by an external port scan from a non-tailnet host), SR-048 (data-store ports not published) and SR-049 (TLS between client and backend; HSTS; plain HTTP only on `127.0.0.1` for the host-local Electron shell).

The deployment is WSL Ubuntu on a Windows host (`docs/plan/20-architecture.md` section 8.1), which is precisely where this assumption is fragile: WSL port-forwarding, Windows Firewall profiles, `netsh portproxy` leftovers and Docker's own publish rules can each quietly expose a port to the LAN or the internet. RR-02 in section 16.1 already accepts that a Tailscale account compromise grants network reach - but only *given* that nothing else does.

Pen-test scope item 9 includes "exposure testing from off-tailnet" and the tester will assume this boundary holds. This spike verifies it empirically **before** the test, so that a boundary failure is fixed rather than discovered as a Critical finding.

## Questions to answer
1. From a host that is **not** on the tailnet (LAN neighbour, and a remote internet vantage point), what ports of the trading host are reachable? Specifically: the app port, Postgres, QuestDB HTTP console, Prometheus, Grafana, and the Docker daemon.
2. Does the SR-047 start-up self-check actually enumerate listening sockets correctly **inside WSL and on the Windows host**, and does it refuse to start on a non-loopback bind, including the case where Docker publishes a port to `0.0.0.0` on the Windows side while the container binds "correctly" inside?
3. Do the Tailscale ACLs enforce the SR-046 split in practice - can a `tag:manager` device reach an admin or observability port?
4. Is TLS actually terminated as specified (SR-049), with HSTS, and is plain HTTP available anywhere other than `127.0.0.1`?
5. Are there `netsh portproxy` entries, UPnP mappings, or Windows Firewall rules that expose anything?

## Timebox and decision criteria
**Timebox: 3 days**, agreed with the Architect. Decision criteria stated up front:
- If **any** unexpected port is reachable off-tailnet, this becomes a P0 Task in Sprint 20 and the pen-test brief is updated - the freeze does not proceed until it is closed.
- If the start-up self-check misses the Docker-publish case, the check is extended to enumerate Windows-side listeners (or the compose files are changed to bind explicitly to the tailnet/loopback address), decided by whichever is verifiable in CI.
- If the ACLs do not enforce the split, the ACL file is corrected and a regression procedure is added to the quarterly audit.
- If everything holds, the result is recorded as evidence in the R4 pack and the quarterly external scan procedure (SR-047) is documented as a recurring Chore.

This spike is explicitly **not** expected to produce production-shippable code beyond, at most, an extension to the self-check.

## Scope / Deliverables
- An external scan from two vantage points (LAN and internet) against the trading host, with full output archived.
- A review of `docker-compose.yml` and its `.dev`/`.vps` overrides (`infra/compose/`) for any `ports:` publish that reaches `0.0.0.0`.
- A Windows-side enumeration: `netstat`/`Get-NetTCPConnection`, `netsh interface portproxy show all`, firewall profile review, UPnP check on the router.
- A Tailscale ACL review against SR-046 plus a practical reachability test from a `tag:manager` device.
- A TLS/HSTS verification against the tailnet hostname.
- A written findings note with a comparison table (expected vs observed per port per vantage point) and a recommendation per question.
- **ADR entry** recording the decision (`docs/plan/27-adrs/`), even if the decision is "assumption holds, procedure documented" (required by `docs/plan/02-definition-of-ready-done.md` section 5.2).
- Follow-up tickets filed for whichever path is chosen.
- `docs/plan/32-risk-register.md` updated if a new risk is surfaced or RR-02's framing changes.

## Out of scope
- Testing the Tailscale vendor platform itself (out of scope per section 13.3 - configuration is in scope, the platform is not).
- Any change to the remote-access decision (Tailscale-only is a locked decision).

## Acceptance criteria
```gherkin
Scenario: Off-tailnet reachability is measured, not assumed
  Given scans from a LAN vantage point and an internet vantage point
  Then a table records, per port, whether it responded, and the output is archived

Scenario: The self-check is proven against the Docker-publish case
  Given a compose override that publishes a port to 0.0.0.0 on the Windows side
  When the application starts
  Then the start-up self-check refuses to start or hard-alerts, and the behaviour is recorded

Scenario: ACL split is demonstrated
  Given a device carrying tag:manager
  When it attempts to reach an admin or observability port on the trading host
  Then the connection is refused, demonstrated with captured output

Scenario: The spike ends in a decision
  Given the timebox expires or the questions are answered
  Then an ADR is merged recording the decision and follow-up tickets are filed
```

## Technical notes / design
- Scans must be authorised by the Owner in advance and run within an agreed window (mirrors the pen-test rules of engagement in section 13.4).
- The internet vantage point must not be a shared scanning service that would publish results; use a controlled host.
- The self-check extension, if built, enumerates listeners via the OS and compares against an allowlist of `127.0.0.1` and the tailnet address; it must handle IPv6 (`::1`, tailnet v6) explicitly, since an IPv6-only exposure is the classic miss.

## Test plan
Evidence-gathering rather than a test suite: archived scan output per vantage point; captured ACL test output; a reproducible self-check test added to the integration suite if the extension is built. If the self-check is extended, it carries unit tests for allowlist matching incl. IPv6 forms.

## Security notes
This spike touches the outermost trust boundary (B1/B2 in `docs/plan/20-architecture.md` section 2.2) and directly tests residual risks RR-02 and RR-03. Scan output may itself reveal exposure and is stored with the same access control as the security program doc, not in a public artefact. No credentials are used off-tailnet.

## Accessibility notes
N/A - no UI surface.

## Performance notes
Scanning must be rate-limited so it does not disrupt an active trading session; run in an agreed window with the Owner, and never during a live smoke test.

## Observability
If the self-check is extended, it emits `cv_listener_check{result}` at start-up and the quarterly scan result is recorded as `cv_external_scan_last_run_timestamp`.

## Definition of Done
- [ ] All five questions answered with archived evidence.
- [ ] ADR merged in `docs/plan/27-adrs/` recording the decision (including "assumption holds").
- [ ] Follow-up tickets filed for every gap, with the findings linked so implementers do not re-derive them.
- [ ] `docs/plan/32-risk-register.md` updated (RR-02/RR-03 reviewed).
- [ ] Findings presented at the Security Review and to the Architect.
- [ ] Spike code promoted (self-check extension) or explicitly marked throwaway.

## Dependencies
- **E43-X01** STRIDE refresh (network threat area re-scored before the scan is designed).
- Feeds **E43-X02**: the tester is given the boundary evidence so infrastructure time is spent on ACL logic rather than on discovery.

## Branch
`spike/e43-tailscale-boundary`. PR size guidance: findings note + ADR; any self-check extension as a separate small PR.

## References
- `docs/plan/04-security-program.md` SR-045..SR-049, sections 4, 5.10, 13.2 item 9, 16.1 (RR-02, RR-03).
- `docs/plan/20-architecture.md` section 2.2 trust boundaries, section 8.1 deployment.
- `docs/plan/32-risk-register.md`.""")

json.dump(T, io.open(os.path.join(os.path.dirname(__file__), "_e43_part4.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("part4", len(T))
