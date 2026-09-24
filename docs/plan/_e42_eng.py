# -*- coding: utf-8 -*-
"""E42 engineering tickets (Spike, Tasks, Stories)."""
from _e42_lib import t, REF, DOD_ENG, A11Y_ADMIN, PERF_NOTE

NA_A11Y = "## Accessibility notes\nN/A — backend/API ticket with no UI surface. The consuming UI stories (E42-S01..S07) carry the WCAG 2.2 AA obligations; this ticket must however return machine-readable error codes (`step_up_required`, `forbidden`, `conflict`, `precondition_failed`, `rate_limited`) and human-readable `detail` strings so the UI can render an accessible, specific message instead of a generic failure."

SEC_ADMIN = """## Security notes
Data classification: **Confidential** (user identities, role grants, session metadata, audit payloads, operational posture). Threats from `docs/plan/04-security-program.md` §5.7 Area 7:
- **D1 Elevation of privilege (Critical)** — a hidden admin screen whose API stays callable. Control **SR-017**: every route authorises server-side from the RBAC policy-decision point built in E09; UI hiding is cosmetic. E42-X02's role x route matrix test is the regression.
- **D2 Tampering (High)** — flags used to enable live trading without review. Control **SR-025**: step-up re-auth (≤5 min elevated token) on every dangerous mutation; `trading.live_enabled` additionally gated by the E44 readiness gate.
- **D3 Information disclosure (Medium)** — audit payloads exposed to a non-owner. Control **SR-067**: role-scoped audit projections applied in the projection layer, raw `before_state`/`after_state` owner-only. **SR-005**: no secret, key, token or password hash is ever serialised into a response or an audit payload.
- **D4 Tampering (High)** — risk configuration changed silently. Control **SR-065**: before/after diff in every audit event.
- **D5 Elevation of privilege (High)** — owner-only mutation reachable through a shared self-service handler. Control **SR-026**: distinct endpoints for self-service vs administrative mutation; no `user_id` parameter on self-service routes.
- **D6 Denial of service (Low)** — the last owner is deleted or demoted. Control **SR-055**: at least one enabled Owner must always exist; enforced in the service layer and by a DB-level check, returning `409 conflict`.
Review label `security` required; Security engineer review is a merge gate for this ticket."""

OBS_ADMIN = """## Observability
- Structured log fields on every admin request: `request_id`, `actor_user_id`, `actor_role`, `route`, `admin_token_age_s`, `step_up_used`, `outcome`, `duration_ms`. Never log payload bodies for audit or flag routes (SR-005).
- Prometheus metrics: `cv_admin_request_duration_seconds{route,outcome}` (histogram), `cv_admin_forbidden_total{route,role}` (counter — a non-zero rate on an unexpected role is an alerting signal for D1), `cv_admin_stepup_challenges_total{action,result}`.
- Audit events per `21-database-schema.md` §3.10.1 with `before_state`/`after_state` and `severity`.
- Grafana: the "Admin & security" dashboard panel set added in E04 gains rows for this ticket's metrics; an alert fires on `cv_admin_forbidden_total` from a non-owner role at >5/min."""

T = []

# ---------------------------------------------------------------- K01
T.append(t(
    "E42-K01", "Spike",
    "Spike: audit-log search and hash-chain verification at 10M rows",
    ["type/spike", "priority/p1", "perf", "security"],
    "api", "Sprint 15", "P1 High", "Architecture", "R15 Data lifecycle", 2, "E42",
    ["E09"],
    """## Context
`US-ADMIN-009` (`docs/plan/11-user-stories.md` §26) sets a hard NFR: *"search over 10 million entries returns the first page in ≤2 s"*, and SCR-135 (`docs/plan/14-screens-catalogue.md` §10) tightens that to a ≤400 ms p95 filter round-trip. `US-ADMIN-008` additionally requires on-demand verification of the SHA-256 hash chain defined by the `audit_chain()` trigger in `docs/plan/21-database-schema.md` §3.10.1, and `audit_log` is retained **indefinitely** — so the table only ever grows. Verification is inherently sequential (each row hashes the previous row's `entry_hash`), which is exactly the shape that does not scale naively.

Before E42-T02 commits to an implementation we must know: which query shapes the existing indexes (`ix_audit_time`, `ix_audit_actor`, `ix_audit_action`, `ix_audit_object`, `ix_audit_sev`) actually serve at 10 M rows; whether the free-text `q` parameter of `GET /admin/audit` needs a GIN/`tsvector` index or a trigram index on `before_state`/`after_state`; whether cursor pagination on `(event_ts DESC, id DESC)` stays stable; and how `/admin/audit/verify` can meet a usable wall-clock time (incremental verification anchored on `audit_checkpoints`, or parallel segment verification, or both).

## Scope / Deliverables
- A reproducible generator that seeds a throwaway Postgres with **10 M** realistic `audit_log` rows (mixed `action`, `actor_user_id`, `object_kind`, `severity`, `env`, realistic `before_state`/`after_state` JSONB sizes), plus a 1 M-row variant for CI, committed at `tools/bench/audit_seed.py`.
- Measured `EXPLAIN (ANALYZE, BUFFERS)` for each filter combination exposed by `GET /api/v1/admin/audit` (`actor_user_id`, `action`, `subject_type`, `subject_id`, `outcome`, `severity`, `ip`, `q`, time range) singly and in the three most likely combinations.
- A decision on the free-text `q` implementation: GIN on a generated `tsvector`, `pg_trgm`, or restricting `q` to indexed columns.
- A decision on `/admin/audit/verify` strategy: full walk vs checkpoint-anchored incremental walk over `audit_checkpoints` vs parallel segment verification, with measured wall-clock at 10 M rows and a stated worst case.
- A measured answer for the tampered-row case (roadmap §7.3 exit criterion 12): how long until the first divergence is reported, and whether the reported position is exact.
- **ADR-0022 "Audit-log query and chain-verification strategy"** in `docs/plan/27-adrs/` recording the decision, the numbers and the rejected options.
- Follow-up tickets filed (index migration, verify endpoint shape) and linked into E42-T02.

## Out of scope
- Production implementation of the endpoints — that is E42-T02. Any code here is a throwaway benchmark branch unless explicitly promoted.
- Changing the `audit_chain()` trigger or the chain algorithm itself (owned by E09; a change proposal may be a spike outcome but not a spike deliverable).
- Cold-storage/archival of audit rows to Parquet — out of scope for R3; note it as a finding if the numbers demand it.

## Acceptance criteria
```gherkin
Scenario: Filter latency characterised
  Given a Postgres instance seeded with 10,000,000 audit_log rows
  When each documented filter combination of GET /api/v1/admin/audit is executed 20 times warm
  Then p50/p95/p99 latency and the chosen plan are recorded per combination in the ADR
  And every combination either meets the 400 ms p95 budget or has a named index change that makes it meet it

Scenario: Verification strategy chosen with evidence
  When the candidate verification strategies are run over the 10 M-row fixture
  Then the wall-clock time and peak memory of each is recorded
  And ADR-0022 states the chosen strategy, the measured worst case, and the reason the others were rejected

Scenario: Tamper detection proven
  Given one row in the middle of the 10 M-row fixture has its after_state altered directly in the database
  When the chosen verification strategy runs
  Then it reports a chain break at exactly that row id
  And it does not report any false break before or after it

Scenario: Timebox respected (failure path)
  Given the 5-working-day timebox expires before every question is answered
  Then the ADR is still written, recording which questions are answered, which are open, and the conservative default chosen for E42-T02
  And the open questions become their own follow-up tickets rather than silent assumptions
```

## Technical notes / design
- Timebox: **5 working days**, agreed with the Architect. Decision criteria stated up front: if the checkpoint-anchored incremental walk verifies the *last 24 h* in <5 s and a full 10 M walk in <10 min, incremental is chosen for the interactive endpoint and full-walk becomes the nightly `cv-audit-verify` job; if not, parallel segment verification (verify segments between consecutive `audit_checkpoints` rows concurrently, then verify the checkpoint spine) is chosen.
- Seed realism matters: skew `event_ts` to business hours, make ~2% of rows `severity IN ('error','critical')`, make `before_state`/`after_state` 200 B–4 KB JSONB, and use ~10 distinct actors and ~40 distinct `action` values, matching the action list in `21-database-schema.md` §3.10.1.
- Cursor pagination must be tested for stability under concurrent inserts (the chain serialises inserts via `pg_advisory_xact_lock(hashtext('audit_log'))`, so `id` is monotonic — confirm that a `(event_ts, id)` keyset cursor cannot skip or duplicate).
- Record the raw numbers as a committed CSV next to the ADR so later regressions can be compared rather than re-argued.

## Test plan
- N/A as production tests; the spike's evidence *is* its output. However the seed generator gets a smoke test (`pytest tools/bench/test_audit_seed.py`) asserting it produces a valid chain (each row's `prev_hash` equals the previous row's `entry_hash`), because an invalid fixture would invalidate every measurement.
- The chosen index set is handed to E42-T02 as a migration with a contract test on query plans (`EXPLAIN` asserts index usage, not seq scan) so the finding cannot silently rot.

""" + SEC_ADMIN + "\n\n" + NA_A11Y + """

## Performance notes
Targets under test: audit first page ≤2 s at 10 M rows (US-ADMIN-009 NFR), ≤400 ms p95 filter round-trip (SCR-135), and the general rule from `docs/plan/06-performance-and-load-standard.md` that no admin screen may add more than 1% load to the running system. Benchmarks run on the reference dev hardware profile documented in `06-performance-and-load-standard.md`, single-node Postgres in docker compose (WSL Ubuntu), with results stated per hardware profile so a VPS re-measurement is comparable.

""" + OBS_ADMIN + """

## Definition of Done
- [ ] Every question in Scope answered with recorded evidence (query plans, timing tables, CSV of raw runs) attached to the ticket.
- [ ] **ADR-0022** written in `docs/plan/27-adrs/` — even if the decision is "defer with a conservative default", per `02-definition-of-ready-done.md` §5.2.
- [ ] Follow-up tickets filed and linked from E42-T02 with the findings as context.
- [ ] Spike branch explicitly marked throwaway, or the seed generator promoted under normal Task DoD (it is intended to be promoted — it is reused by E42-Q03).
- [ ] Findings presented at Sprint Review / Architecture review.
- [ ] `docs/plan/32-risk-register.md` updated under **R15 Data lifecycle** with the measured audit-growth and verification cost.

## Dependencies
- `E09` — owns the `audit_log` table, the `audit_chain()` trigger and the `audit_checkpoints` writer. Without the real schema and trigger in place the fixture would not reproduce production chain semantics.

## Branch
`spike/admin-screens-audit-scale` (throwaway except the promoted seed generator). PR size: the promoted generator only, ≤300 LOC.

""" + REF))

# ---------------------------------------------------------------- T01
T.append(t(
    "E42-T01", "Task",
    "Build M21 admin aggregation API and the admin elevation/step-up middleware",
    ["type/tech", "priority/p0", "security"],
    "api", "Sprint 16", "P0 Critical", "Development", "None", 5, "E42",
    ["E09", "E42-X01"],
    """## Context
Module **M21 `admin`** (`docs/plan/20-architecture.md` §3.11 — `UserAdmin`, `FlagAdmin`, `HealthConsole`, `RecorderAdmin`) is the server side of every `/admin/*` screen. It owns almost no domain state; it *composes* state owned by M14 (OMS), M17 (risk), M2 (credentials), M4 (recorder), M19 (auth/RBAC/audit) and the metrics pipeline from E04. This ticket lays the module's foundation: the two aggregation endpoints (`GET /api/v1/admin/overview`, `GET /api/v1/admin/capacity`), the authorisation/elevation middleware that every other E42 route sits behind, and the partial-result contract that stops one slow subsystem from making the admin area unusable.

Two clocks govern access and they are frequently confused, so they are specified here once:
- **Admin-area token** — `docs/plan/12-sitemap.md` R-300: entering any `/admin/*` route requires an admin re-auth token no older than **15 minutes of activity**; SCR-149 is its UI. Audited as `admin.session_elevated` and `admin.area_entered`.
- **Step-up token** — `docs/plan/04-security-program.md` SR-025: a **≤5 minute** elevated token required *per dangerous mutation* (create/delete user, change role or grant, change a flag, export the audit log, restore a backup, disable the kill-switch). Issued by `POST /api/v1/auth/step-up`.
Neither is client-computable; both are server-issued and server-verified, and both are audited.

## Scope / Deliverables
- Python package `backend/src/cv/admin/` (module **M21**) with `router.py`, `service.py`, `elevation.py`, `aggregate.py`, wired into the FastAPI app.
- `GET /api/v1/admin/overview` (`operationId: getAdminOverview`) — the SCR-120 roll-up: users by role and pending invites, sub-account capacity, keys needing rotation, profiles missing risk caps, recorder symbol/disk/retention figures, health summary, flag counts, last backup, today's audit counts by severity.
- `GET /api/v1/admin/capacity` (`operationId: getCapacity`) — ingestion, storage and rate-budget headroom, plus the Bybit sub-account cap facts for US-ADMIN-014 (5 regular / 20 with Business KYC, tier an explicitly recorded fact, never inferred).
- **Elevation middleware**: a FastAPI dependency `require_admin_area()` (15 min token) and `require_step_up(action)` (5 min token), returning RFC-7807 problem responses with `code: step_up_required` including `required_ttl_s` and `challenge_url`, so the UI can raise SCR-149 or the step-up dialog without guessing.
- **Per-source aggregation contract**: each section of an aggregate response carries `{status: "ok"|"degraded"|"unavailable", as_of: <ts>, data|error}`; the endpoint has a global deadline (700 ms) and per-source timeouts (250 ms) and returns `200` with degraded sections rather than failing wholesale.
- Server-side authorisation on every route from the E09 policy-decision point, plus the `cv_admin_forbidden_total` metric.
- Audit emission helpers used by every later E42 route: `admin.area_entered`, `admin.session_elevated`, `admin.overview_viewed` (analytics only).
- OpenAPI additions/confirmations in `docs/plan/22-api-openapi.yaml` for the two endpoints and the shared `AdminSection` schema.

## Out of scope
- The screens themselves (E42-S01..S07).
- Audit query/verify/export (E42-T02), flags and maintenance (E42-T03), backups (E42-T04).
- The RBAC policy engine and session/TOTP machinery — owned by **E09**; this ticket consumes them and must not fork them.
- Changing the definitions of the numbers it aggregates (recorder figures stay E16's, risk figures stay E39's).

## Acceptance criteria
```gherkin
Scenario: Overview aggregates without blocking on the slowest source
  Given the recorder subsystem is unreachable and every other source is healthy
  When the owner calls GET /api/v1/admin/overview with a valid admin-area token
  Then the response is 200 within 800 ms
  And the recorder section has status "unavailable" with an error code and an as_of timestamp
  And every other section has status "ok" with its data

Scenario: Admin area requires a fresh admin token
  Given the caller's admin re-auth token is 16 minutes old
  When they call GET /api/v1/admin/overview
  Then the response is 401 with code "step_up_required" and the required TTL and challenge URL
  And an audit row is written with action "admin.area_entered", outcome "denied"

Scenario: A non-admin role is refused server-side, not merely hidden
  Given a user holding only the manager role, with a valid session and a valid step-up token
  When they call GET /api/v1/admin/overview and GET /api/v1/admin/capacity
  Then each returns 403 with code "forbidden"
  And no data from any admin projection appears in the response body
  And cv_admin_forbidden_total{route,role="manager"} increments
  And an audit row records the denied attempt

Scenario: Sub-account capacity is a recorded fact, never inferred
  Given the installation has not recorded a Business KYC tier
  When GET /api/v1/admin/capacity is called
  Then sub_account_cap is 5 and tier_source is "recorded_default"
  And the response never derives the cap from the observed number of accounts
```

## Technical notes / design
- **Aggregation.** `aggregate.py` exposes `gather_sections(sources: list[Source], deadline_ms=700, per_source_ms=250)` built on `asyncio.wait_for` per source inside a `TaskGroup`; a source that times out or raises yields `status="unavailable"` with a stable error code and never propagates. Sources are pure async callables registered by the owning module, so E16/E39/E27 add sections without editing M21.
- **Caching.** Overview sections are cached for 5 s keyed by `(section, actor_role)` — enough to stop a refresh storm, short enough that the screen is honest. Kill-switch state is **never** cached (`21-database-schema.md` §3.9: `is_killswitch` flags bypass caching and are re-read every 5 s).
- **Elevation.** Tokens are opaque server-side records, not JWT claims the client can inspect or extend. `require_step_up(action)` binds the token to the specific action string so a token minted for "export audit" cannot authorise "restore backup". Remaining TTL is returned in a response header (`X-Admin-Token-Expires-In`) so the admin chrome can show the countdown SCR-149 requires without polling.
- **Error codes** (shared by all of E42, consumed by the UI): `step_up_required`, `forbidden`, `conflict`, `precondition_failed`, `rate_limited`, `not_found`.
- Rate-limit admin mutation routes at 30/min/actor to bound the abuse surface, returning `rate_limited` with `Retry-After`.

## Test plan
- **Unit** (≥90% on `cv.admin`, security-relevant module policy from `30-release-roadmap.md` §8.4): section assembly with all-ok / one-degraded / all-degraded; deadline enforcement; cache TTL and the kill-switch cache bypass; step-up token action binding (token for action A rejected for action B); token expiry boundary at exactly 15:00 and 5:00; capacity tier resolution incl. the recorded-Business-KYC case; last-owner guard helper.
- **Contract**: both endpoints validated against `docs/plan/22-api-openapi.yaml` (schemathesis), incl. the `AdminSection` envelope and the problem-response shapes.
- **Integration**: against a seeded Postgres — overview with a real users/flags/backups/audit fixture; forced source failure via a fault-injecting fake; audit rows asserted for every denied and every elevated request.
- **Security**: the role x route matrix harness that E42-X02 owns is wired here for the two endpoints, so every later route inherits it automatically.
- **Perf**: overview p95 ≤800 ms with all sources healthy and ≤800 ms with two sources timing out (proving the deadline, not just the happy path).
- Fixtures: `tests/fixtures/admin/seed_small.sql`, and the fault-injecting source fake `tests/support/flaky_source.py`.

""" + SEC_ADMIN + "\n\n" + NA_A11Y + "\n\n" + PERF_NOTE + "\n\n" + OBS_ADMIN + "\n\n" + DOD_ENG + """

## Dependencies
- **E09** Auth, sessions, 2FA & RBAC — provides sessions, TOTP, `POST /auth/step-up`, the RBAC policy-decision point and the audit writer. Hard prerequisite: this ticket must not implement its own authorisation.
- **E42-X01** STRIDE threat model — the elevation model and the denied-path audit requirements are outputs of the threat model, so it is scheduled first.

## Branch
`feat/admin-screens-m21-core`. PR ≤400 LOC; split the elevation middleware and the aggregation framework into two PRs if the diff exceeds that.

""" + REF))

# ---------------------------------------------------------------- T02
T.append(t(
    "E42-T02", "Task",
    "Implement audit query, chain verification and signed export endpoints",
    ["type/tech", "priority/p0", "security", "perf"],
    "api", "Sprint 16", "P0 Critical", "Development", "R15 Data lifecycle", 5, "E42",
    ["E42-K01", "E42-T01"],
    """## Context
US-ADMIN-008 and US-ADMIN-009 (`docs/plan/11-user-stories.md` §26) require the audit log to be *evidence*: append-only, hash-chained, verifiable, searchable over 10 M rows, role-scoped, and exportable as a signed artefact whose export is itself audited. The writer and the chain already exist — `docs/plan/21-database-schema.md` §3.10.1 defines `audit_log` with the `audit_chain()` BEFORE INSERT trigger, `forbid_mutation()` on UPDATE/DELETE, serialised inserts via `pg_advisory_xact_lock(hashtext('audit_log'))`, and `audit_checkpoints` with an Ed25519 signature over the head hash using a key held outside the database. E09 ships all of that.

This ticket builds the **read side**: `GET /api/v1/admin/audit` (`queryAuditLog`), `POST /api/v1/admin/audit/verify` (`verifyAuditChain`), `POST /api/v1/admin/audit/export` (`exportAuditLog`), plus the role-scoped projection layer that satisfies threat **D3**. Roadmap §7.3 exit criterion 12 makes the tampered-row test a release gate: *"audit hash-chain verification passes on a tampered-row test"*.

## Scope / Deliverables
- `GET /api/v1/admin/audit` with the documented filters — `actor_user_id`, `action`, `subject_type`, `subject_id`, `outcome`, `severity`, `ip`, `q` (free-text over the detail payload), time range — cursor-paginated on `(event_ts DESC, id DESC)`, returning `chain_verified` for the returned slice.
- `POST /api/v1/admin/audit/verify` — recomputes the chain over a range using the strategy chosen in **ADR-0022** (E42-K01) and reports the first divergence with its exact row id, or a clean result with the verified row count and the covering `audit_checkpoints` entries.
- `POST /api/v1/admin/audit/export` — asynchronous job producing signed NDJSON plus a detached signature over the file digest; returns a job id polled via `GET /api/v1/admin/jobs/{jobId}`; `download_url` populated on completion; the export emits its own audit row (`audit.record_exported`) *before* the file is readable.
- **Role-scoped projections** (SR-067, threat D3): owner sees raw `before_state`/`after_state`; manager and viewer see a redacted projection restricted to rows where they are the actor (`US-ADMIN-009`: *"Given I am a manager Then I see only entries describing my own actions, enforced server-side"*). Redaction lives in the projection layer, not in a template.
- Index migration implementing ADR-0022's decision (including the `q` implementation), with a plan-assertion contract test.
- `audit.record_viewed` emission for single-record reads (SCR-136: reading the audit log is itself on the record).
- OpenAPI confirmation/update for the three endpoints in `docs/plan/22-api-openapi.yaml`.

## Out of scope
- Writing audit rows — every producing module owns its own emission; E09 owns the writer and the trigger.
- The nightly `cv-audit-verify` job and its `critical` system event — owned by E04/E09 observability; this ticket exposes the same verification logic through an endpoint and must share the implementation rather than duplicating it.
- The audit browser UI (E42-S04).
- Archiving audit rows to Parquet/cold storage (noted as an R15 follow-up if K01's numbers demand it).

## Acceptance criteria
```gherkin
Scenario: Filtered search is fast and stably ordered
  Given an audit_log seeded with 10,000,000 rows
  When the owner queries GET /api/v1/admin/audit filtered by action "flags.change" and a 7-day range
  Then the first page returns within 2 s and subsequent warm pages within 400 ms p95
  And paging forward then backward returns exactly the same rows in the same order with no duplicates and no gaps
  And chain_verified is true for the returned slice

Scenario: A tampered row is detected at its exact position
  Given one audit_log row's after_state has been altered by a direct database write
  When POST /api/v1/admin/audit/verify runs over a range covering that row
  Then the response reports verified=false with the first divergent row id equal to the tampered row's id
  And a system_event with severity "critical" is raised
  And the verification attempt and its result are themselves audited

Scenario: A manager sees only their own actions, enforced server-side
  Given a manager with a valid admin session
  When they call GET /api/v1/admin/audit without any actor filter
  Then every returned row has actor_user_id equal to their own user id
  And before_state and after_state are absent or redacted on every row
  And explicitly passing actor_user_id of another user returns 403 forbidden rather than an empty list

Scenario: Export is step-up gated, signed and self-auditing
  Given the owner holds a step-up token minted for the action "audit.export"
  When they POST /api/v1/admin/audit/export for a filtered slice
  Then a job id is returned, and GET /api/v1/admin/jobs/{jobId} eventually reports completion with a download_url
  And the NDJSON bundle has a detached signature that verifies against the published public key
  And the bundle preserves the same redaction the caller's role would see interactively
  And an audit row for the export exists before the file becomes downloadable

Scenario: Mutation is impossible through any path (failure case)
  When an UPDATE or DELETE is attempted against audit_log by the application role
  Then the database refuses it via forbid_mutation()
  And the attempt is recorded
  And no API surface in this ticket exposes any write, patch or delete verb on audit_log
```

## Technical notes / design
- **Keyset pagination**, never OFFSET: `WHERE (event_ts, id) < (:cursor_ts, :cursor_id) ORDER BY event_ts DESC, id DESC LIMIT :n`. Cursors are opaque base64 of `(event_ts, id)` and are validated, not trusted.
- **`chain_verified` on a slice** is a cheap local check: for a contiguous page, assert each row's `prev_hash` equals the previous row's `entry_hash`. It is explicitly *not* a claim about the whole table — the response documents that, and the UI (E42-S04) must not present it as one.
- **Verification** reuses the canonical serialisation from `audit_chain()` exactly — field order, the `to_char(... 'YYYY-MM-DD"T"HH24:MI:SS.USOF')` timestamp format, and `coalesce('')` for nulls. Any drift between the trigger and the verifier produces false positives, so the serialisation is implemented once in `cv/audit/canonical.py` and covered by a golden-vector test against rows written by the real trigger.
- **Export signing**: Ed25519 with the same key family as `audit_checkpoints.signed_by` (`cv-audit-key-v1`), private key held outside the DB and outside the application config (loaded from the KEK-adjacent secret source established in E27). The bundle header records `key_id`, filter criteria, row count, head hash and generated-at.
- **Redaction map** is declarative: a per-`action` allowlist of payload fields visible to non-owner roles, defaulting to *nothing* — an unknown action redacts fully rather than leaking. A unit test asserts every action in the `21-database-schema.md` §3.10.1 must-audit list has an explicit entry.
- Export jobs are bounded: max 1 M rows or 500 MB per bundle, returning `precondition_failed` with the row count when exceeded, so a careless export cannot become a self-inflicted DoS.

## Test plan
- **Unit** (≥90%): canonical serialisation golden vectors; slice chain check incl. a deliberately broken slice; cursor encode/decode and rejection of a malformed cursor; redaction map defaulting-to-deny and per-role projections; export size guard; filter-to-SQL construction with parameterisation (no string interpolation anywhere near user input).
- **Contract**: all three endpoints and `GET /admin/jobs/{jobId}` against `22-api-openapi.yaml`.
- **Integration**: 1 M-row seeded fixture (from E42-K01's generator) — verify clean; verify with an injected tampered row asserting the exact id and the `critical` `system_event`; manager-scoped query asserting server-side scoping; export end-to-end with signature verification; concurrent-insert pagination stability.
- **Perf**: the K01 budgets re-run as a CI perf job at the 1 M-row scale with the 10 M-row run executed manually before the R3 gate; plan-assertion test that each filter uses its intended index.
- **Security**: SQLi attempts through every filter parameter and the `q` field; attempts to page into another actor's rows by crafting a cursor; attempt to fetch a completed export's `download_url` as a different user.
- Fixtures: `tests/fixtures/audit/1m_chain.sql.gz`, `tests/fixtures/audit/tampered_row.sql`.

""" + SEC_ADMIN + "\n\n" + NA_A11Y + "\n\n" + PERF_NOTE + "\n\n" + OBS_ADMIN + "\n\n" + DOD_ENG + """

## Dependencies
- **E42-K01** — ADR-0022 fixes the index set, the `q` strategy and the verification strategy; implementing before the spike lands would mean guessing at the 10 M-row shape.
- **E42-T01** — supplies the elevation middleware (export is step-up gated), the error-code vocabulary and the M21 router.
- **E09** — owns `audit_log`, the trigger, `audit_checkpoints` and the signing key handling.

## Branch
`feat/admin-screens-audit-api`. Three PRs: query+projections, verify, export+signing — each ≤400 LOC.

""" + REF))

# ---------------------------------------------------------------- T03
T.append(t(
    "E42-T03", "Task",
    "Implement the feature-flag service, push propagation and maintenance mode",
    ["type/tech", "priority/p0", "security"],
    "api", "Sprint 16", "P0 Critical", "Development", "None", 3, "E42",
    ["E42-T01"],
    """## Context
US-ADMIN-007 (`docs/plan/11-user-stories.md` §26) requires runtime feature flags so the owner can shed load or disable a risky feature *without a deployment*: a change must reach all users within 10 s (SCR-145 tightens this to 2 s), safety-affecting flags require step-up authentication, and every flag's state, who changed it and when must be listed. The data model already exists — `docs/plan/21-database-schema.md` §3.9 defines `feature_flags` (with `kind`, `default_value`, `rollout_pct`, `variants`, `is_killswitch`, `expires_at`) and `feature_flag_overrides` (user- or role-scoped, exactly one target enforced by `ffo_target`), and fixes the resolution order: **user override → role override → percentage rollout (hash of `user_id||flag_key`) → default value**, with `is_killswitch` flags bypassing caching and re-read every 5 s.

Maintenance mode (SCR-148, R-356) is the same machinery applied to operations: a banner for all users, new orders blocked server-side within 200 ms, algos paused, recorder optionally kept running, with the explicit and non-negotiable statement that **native exchange stops remain active**.

The hard constraint from US-ADMIN-007's NFR: *"no flag may weaken a security control"*. A flag that could disable authentication, RBAC, audit writing or the native-SL invariant must not be representable.

## Scope / Deliverables
- `backend/src/cv/admin/flags.py` — resolution engine implementing the §3.9 order exactly, with a 5 s cache for normal flags and a hard no-cache path for `is_killswitch`.
- `GET /api/v1/admin/feature-flags` and `PUT /api/v1/admin/feature-flags/{flagKey}` per `docs/plan/22-api-openapi.yaml`, including per-flag change history projected from `audit_log` (`action = 'flags.change'`, `object_id = flagKey`).
- **Push propagation**: flag changes broadcast on the WS `system` topic (`cv://ws/v1/system.schema.json`, `docs/plan/23-ws-protocol.md`) as a delta with `kind: "feature_flags"`; the `system` snapshot already carries `feature_flags` and `kill_switch` (see §9.5 example frames) and must reflect the new state for any client connecting after the change.
- **Protected-flag registry**: a compile-time list of security controls that may never be flag-controlled (auth, RBAC enforcement, audit writing, native-SL invariant, withdrawal-permission check); attempting to create a flag whose key matches a protected control fails at creation and in CI.
- **Gate-blocked flags**: `trading.live_enabled` cannot be set true while the E44/PRR readiness gate is unsatisfied — `PUT` returns `precondition_failed` with the outstanding items enumerated (US-ADMIN-012 "Gate closed" scenario), independent of any UI disabling.
- **Dependent-rule check**: turning a flag off that an armed rule depends on returns the affected rule ids and requires an explicit `acknowledge_dependencies: true` (SCR-145 validation).
- **Maintenance mode** service: enter/exit with a scheduled window and a user-facing message; blocks order acceptance server-side within 200 ms; broadcasts on `system` within 2 s; audited as `maintenance.enabled|disabled`.
- `requires_reload` metadata per flag so the UI can offer a reload action instead of silently taking effect later.

## Out of scope
- The flags console and maintenance UI (E42-S05).
- The kill-switch *mechanism* — owned by **E39**; this ticket surfaces its state and exposes the administrative toggle through the flag surface, but the halting semantics ("stops new risk, does not force-close") and the global hotkey stay in E39.
- The live-enablement gate's criteria and attestation model — owned by **E44**; this ticket only consumes the gate's verdict.
- Client-side flag consumption plumbing in the web app shell (owned by E10/E42-S05 as applicable).

## Acceptance criteria
```gherkin
Scenario: Resolution order is exactly as specified
  Given a flag with default false, a role override true for managers, and a user override false for manager alex
  When the flag is resolved for alex, for another manager, and for a viewer
  Then alex resolves false, the other manager resolves true, and the viewer resolves false
  And a percentage-rollout flag resolves identically for the same user on every evaluation

Scenario: A change reaches every session within 2 seconds
  Given three connected sessions subscribed to the system topic
  When the owner PUTs a new value for a flag with a valid step-up token
  Then all three sessions receive a system delta with kind "feature_flags" within 2 s
  And a client connecting afterwards receives the new value in its system snapshot
  And one audit row with action "flags.change" records before_state and after_state

Scenario: Kill-switch state is never served stale
  Given the kill-switch flag is engaged
  When any consumer resolves it 1 second after the change
  Then the engaged value is returned
  And no cached value older than 5 s can ever be returned for a flag with is_killswitch true

Scenario: A flag cannot weaken a security control (failure case)
  When a flag is created whose key matches a protected control such as auth enforcement, RBAC checking, audit writing or the native-SL invariant
  Then creation is refused with code "forbidden" and a message naming the protected control
  And a CI check fails the build if such a key is added to the seed data

Scenario: Live enablement stays blocked until the gate is satisfied
  Given the pen-test sign-off is outstanding
  When the owner PUTs trading.live_enabled = true with a valid step-up token
  Then the response is 412 precondition_failed listing exactly the outstanding gate items
  And the flag value is unchanged
  And the refused attempt is audited with severity "warning"

Scenario: Maintenance mode blocks new orders and says what it does not do
  When the owner enables maintenance mode with a typed confirmation and a step-up token
  Then order acceptance is refused server-side within 200 ms
  And all sessions receive the maintenance notice within 2 s
  And the broadcast payload states that native exchange stop orders remain active
  And maintenance.enabled is audited with severity "warning"
```

## Technical notes / design
- **Percentage rollout** must be stable and privacy-preserving: `bucket = sha256(user_id || ':' || flag_key)[:8] % 100 < rollout_pct`. No randomness, no time input — a user's bucket may not flip between evaluations.
- **Cache**: an in-process TTL cache (5 s) keyed by `(flag_key, user_id, role_id)`, invalidated eagerly on the change broadcast so the practical propagation is well inside the 2 s budget; `is_killswitch` bypasses the cache entirely and reads through.
- **Broadcast**: the `system` topic is an always-on implicit subscription (`23-ws-protocol.md` §7 resubscribe priority: `system` first), so no client can miss a flag change by not having subscribed. The delta payload is `{"kind":"feature_flags","changed":{"<key>":<value>},"requires_reload":bool}`.
- **Step-up binding**: `require_step_up("flags.change")` from E42-T01; the token is bound to the action, and for `is_killswitch` flags *disabling* the kill-switch is the dangerous direction (SR-025 names "kill-switch disable" specifically) — enabling it must never be blocked by a slow auth path.
- **Expiry hygiene**: `expires_at` past due makes CI warn (flag debt), surfaced on the flags console as a stale-flag marker.
- Concurrency: `PUT` uses an ETag/`If-Match` on the flag row; a mismatch returns `precondition_failed` so two admins cannot silently clobber each other.

## Test plan
- **Unit** (≥90%): resolution order across all four levels; rollout bucket stability and distribution over 100k synthetic ids (±2% of target); kill-switch cache bypass; protected-flag registry rejection; dependent-rule detection; ETag conflict; maintenance-mode state machine incl. scheduled windows and re-entry.
- **Contract**: both flag endpoints against `22-api-openapi.yaml`; the `system` delta and snapshot against `cv://ws/v1/system.schema.json`.
- **Integration**: three live WS clients receiving the change within 2 s; a client connecting mid-change reading the new value from the snapshot; order acceptance refused within 200 ms of maintenance entry; audit rows asserted for every mutation and every refusal.
- **E2E** (in E42-Q02): toggle a flag and observe the feature disappear in a second browser session without a reload.
- **Chaos**: a client disconnected at the moment of the change reconnects and reconciles to the correct value from the snapshot (no stale flag survives a reconnect).
- Fixtures: `tests/fixtures/flags/seed_flags.sql` covering boolean, percentage, variant and kill-switch kinds.

""" + SEC_ADMIN + "\n\n" + NA_A11Y + "\n\n" + PERF_NOTE + "\n\n" + OBS_ADMIN + """
- Additional metrics for this ticket: `cv_flag_eval_total{flag,result}`, `cv_flag_change_propagation_seconds` (histogram, change-committed to last-session-acked), `cv_maintenance_mode_active` (gauge).

""" + DOD_ENG + """

## Dependencies
- **E42-T01** — elevation middleware, error codes, M21 router.
- **E39** Risk caps, lockouts & kill-switch — owns the kill-switch mechanism whose state this surfaces.
- **E44** Live-enablement gating — owns the readiness verdict consumed by the `trading.live_enabled` precondition (referenced as an epic-level dependency; if E44 has not landed, the gate reads "unsatisfied", which is the safe default).
- **E03/E10** WS transport for the `system` topic.

## Branch
`feat/admin-screens-flags`. Two PRs: resolution engine + endpoints, then maintenance mode.

""" + REF))

# ---------------------------------------------------------------- T04
T.append(t(
    "E42-T04", "Task",
    "Implement backup listing, verification and gated restore endpoints",
    ["type/tech", "priority/p1", "security"],
    "api", "Sprint 17", "P1 High", "Development", "R15 Data lifecycle", 2, "E42",
    ["E42-T01"],
    """## Context
SCR-146 (`docs/plan/14-screens-catalogue.md` §10) specifies the backups and restore surface: a list with timestamp, scope, size, integrity-check result and retention; "run backup now" with progress; a restore flow gated by maintenance mode, typed confirmation and step-up; and an explicit statement of **what a restore does and does not recover** — market history is *not* restored from these backups. The `backups` table already exists (`docs/plan/21-database-schema.md` §3.10.3) with `kind`, `status`, `checksum_sha256`, `encrypted`, `covers_from`/`covers_to`, `wal_start_lsn`/`wal_end_lsn`, `verified_at`, `verify_method` (`restore_smoke` | `checksum` | `pg_verifybackup`), `restored_at`, `triggered_by` and `triggered_by_user`.

Restore is the single most destructive action the admin area exposes: it is step-up gated (SR-025 names backup restore explicitly), maintenance-gated, typed-confirmation gated, and audited at `critical` severity.

## Scope / Deliverables
- `GET /api/v1/admin/backups` — list with the columns SCR-146 requires, projecting from `backups`, including last-successful-backup age and a warning flag when it exceeds the configured threshold.
- `GET /api/v1/admin/backups/{backupId}` — detail including verification history and coverage window.
- `POST /api/v1/admin/backups` — run a backup now, returning a job id polled via `GET /api/v1/admin/jobs/{jobId}` with progress.
- `POST /api/v1/admin/backups/{backupId}/verify` — run the configured `verify_method`, writing `verified_at`/`verify_method`, and raising a `critical` `system_event` on failure.
- `POST /api/v1/admin/backups/{backupId}/restore` — the gated restore: requires an active maintenance mode, a step-up token bound to `backup.restore`, and a typed confirmation token echoing the backup id; audited as `backup.restore` with severity `critical`.
- A machine-readable **restore scope manifest** returned by the restore preview: exactly which datasets are covered (Postgres: users/roles/OMS/rules/journal/audit/config) and which are not (QuestDB tick/L2/bar history, Parquet cold storage), so the UI renders the statement from data rather than hard-coded copy.
- Download/export of a backup artefact is step-up gated and audited (SCR-146).

## Out of scope
- The backup *execution* machinery (pg_basebackup/WAL archiving, scheduling, off-box copy) — owned by **E04/infra**; this ticket triggers and reports it.
- The backups UI (E42-S07).
- Restoring QuestDB/Parquet market data — explicitly not covered by these backups; the manifest says so.
- Disaster-recovery runbook authoring — owned by E45; this ticket links to it.

## Acceptance criteria
```gherkin
Scenario: Restore requires every gate
  Given maintenance mode is not active
  When the owner posts a restore for a verified backup with a valid step-up token and a correct typed confirmation
  Then the response is 412 precondition_failed naming the missing maintenance-mode gate
  And no restore is started
  And the refused attempt is audited

Scenario: Restore proceeds when all gates are satisfied
  Given maintenance mode is active, the step-up token is bound to backup.restore, and the typed confirmation matches the backup id
  When the owner posts the restore
  Then a job id is returned and progress is observable via GET /api/v1/admin/jobs/{jobId}
  And an audit row with action "backup.restore", severity "critical" and the backup's identifying metadata is written before the restore begins

Scenario: Failed verification is a security-visible event
  Given a backup whose stored checksum_sha256 no longer matches the artefact
  When verification runs
  Then the result is recorded as failed with the method used
  And a system_event with severity "critical" is raised
  And the backup is marked unusable for restore until re-verified

Scenario: The restore scope is stated from data, not prose
  When the restore preview is requested
  Then the response enumerates the covered datasets and the explicitly-not-covered datasets
  And QuestDB tick, L2 and bar history and Parquet cold storage appear in the not-covered list
```

## Technical notes / design
- The typed confirmation is verified **server-side**: the client must send `confirmation` equal to the backup's short id; a mismatch returns `precondition_failed`. A client-only typed-confirm is theatre, not a control.
- Restore is a long-running job; the job record carries `phase` (`preflight` → `stopping_services` → `restoring` → `verifying` → `complete`) so the UI shows real progress rather than an indeterminate spinner.
- Preflight refuses a restore from a backup whose `status` is not `complete`, whose `verified_at` is null or older than the configured staleness window, or whose `encrypted` is true but whose `encryption_ref` cannot be resolved.
- Backup artefacts are encrypted at rest (`encrypted`, `encryption_ref`); no endpoint ever returns key material, and the download route streams through an authorised, time-limited, single-use URL.

## Test plan
- **Unit** (≥90%): gate composition (each of maintenance/step-up/typed-confirm missing in turn); preflight refusal matrix; last-backup-age warning threshold; manifest construction.
- **Contract**: all five routes plus `GET /admin/jobs/{jobId}` against `22-api-openapi.yaml`.
- **Integration**: against a docker-compose Postgres — run backup, verify, tamper with the artefact, re-verify and assert the `critical` `system_event`; full restore into a throwaway database asserting the restored row counts and that market-data stores are untouched.
- **Security**: attempt restore as a manager (403); attempt restore with a step-up token minted for a different action (401 `step_up_required`); attempt to reuse a download URL (refused).
- Fixtures: `tests/fixtures/backups/seed_backups.sql`, a 50 MB synthetic artefact, and a corrupted copy of it.

""" + SEC_ADMIN + "\n\n" + NA_A11Y + """

## Performance notes
- Backup list and detail are simple indexed reads: ≤300 ms p95.
- Verification and restore are jobs, never request-path work; the API returns within 300 ms with a job id and the work proceeds asynchronously with progress polling at ≤1 Hz (`06-performance-and-load-standard.md` — no admin polling loop tighter than 1 Hz).
- Running a backup must not degrade ingestion beyond the documented budget; the job runs at reduced I/O priority and the health screen shows it as an active job.

""" + OBS_ADMIN + """
- Additional metrics: `cv_backup_last_success_age_seconds` (gauge, alerting), `cv_backup_verify_total{result}`, `cv_backup_restore_total{result}`.

""" + DOD_ENG + """

## Dependencies
- **E42-T01** — elevation middleware, job polling conventions, error codes.
- **E42-T03** — maintenance mode, which is a precondition of restore.
- **E04** — owns the backup execution and scheduling machinery this ticket drives.

## Branch
`feat/admin-screens-backups-api`. Single PR ≤400 LOC.

""" + REF))

# ---------------------------------------------------------------- T05
T.append(t(
    "E42-T05", "Task",
    "Document the admin surface and amend ADR-0010 with the admin elevation model",
    ["type/docs", "priority/p2", "type/tech"],
    "docs", "Sprint 17", "P2 Medium", "Architecture", "None", 1, "E42",
    ["E42-T01", "E42-T02", "E42-T03"],
    """## Context
E42 introduces a governance surface whose rules are easy to misremember and dangerous to get wrong: two distinct elevation clocks (15 min admin-area token per `docs/plan/12-sitemap.md` R-300; 5 min per-action step-up token per SR-025), a protected-flag registry that no future flag may violate, a role-scoped audit projection model, and a restore-scope statement that must stay true as the storage layout evolves. `docs/plan/27-adrs/ADR-0010-auth-and-rbac.md` currently records the auth/RBAC decisions from E09 but predates the admin elevation model; without an amendment the next person to touch `/admin/*` will re-derive it, probably differently.

## Scope / Deliverables
- **Amend `docs/plan/27-adrs/ADR-0010-auth-and-rbac.md`** with a new decision section covering: the two-clock elevation model and why both exist; the per-action binding of step-up tokens; the rule that UI hiding is never the control (SR-017/D1); the distinct-endpoint rule for self-service vs administrative mutation (SR-026/D5); the last-owner invariant (SR-055/D6).
- Reconcile `docs/plan/22-api-openapi.yaml` with what was actually built across E42-T01..T04 (request/response schemas, the `AdminSection` envelope, the problem-response `code` vocabulary, job polling).
- Reconcile `docs/plan/23-ws-protocol.md` §9.5 `system` topic documentation with the `feature_flags`, `kill_switch` and maintenance delta shapes actually emitted.
- Add a short operator-facing page `docs/ops/admin-runbook.md`: entering the admin area, what step-up asks for and why, what maintenance mode does and does not do (native exchange stops stay active), how to read an audit-chain verification failure, how to run and verify a backup, and the break-glass path if the owner is locked out (SR-023) with the requirement that break-glass use is loudly surfaced afterwards.
- Update `docs/plan/14-screens-catalogue.md` SCR-120..149 entries wherever the built behaviour diverged from the catalogue.
- Update `docs/plan/32-risk-register.md` with the measured audit-growth figures from E42-K01 under **R15**.

## Out of scope
- Writing new ADRs for decisions owned elsewhere (ADR-0022 is E42-K01's deliverable; the kill-switch semantics belong to E39).
- End-user help content for non-admin screens.
- Any code change; this is a documentation reconciliation task.

## Acceptance criteria
```gherkin
Scenario: The elevation model is recorded once, authoritatively
  When a developer reads ADR-0010 after this ticket
  Then both elevation clocks, their TTLs, their audit actions and their failure responses are stated
  And the document names the exact list of actions that require step-up per SR-025

Scenario: The API document matches the running system
  When the contract test suite runs against the built endpoints
  Then it passes against the committed 22-api-openapi.yaml with no local overrides or skips

Scenario: The runbook answers the operator's questions without a developer
  Given an operator who has never used the admin area
  When they follow docs/ops/admin-runbook.md to verify the audit chain and run a backup
  Then they complete both tasks without consulting a developer, verified by one observed dry run recorded on the ticket

Scenario: Divergence is captured, not glossed over (edge case)
  Given a behaviour shipped differently from the screens catalogue
  Then the catalogue entry is amended and the amendment is called out in the PR description
```

## Technical notes / design
- ADR amendment follows the existing ADR format in `docs/plan/27-adrs/` (Status / Context / Decision / Consequences / Alternatives), added as a dated amendment section rather than a rewrite, so the original decision history stays legible.
- The runbook is deliberately operator-facing prose with copy-pasteable commands, not architecture; architecture stays in `20-architecture.md`.
- Doc-lint (markdown-lint + link checker already in CI) must pass; every internal link is relative and resolvable.

## Test plan
- Link checker and markdown-lint green in CI.
- The contract test suite is the executable assertion that the OpenAPI document matches reality — this ticket is not Done while it is red or skipped.
- One observed dry run of the runbook by someone who did not write it, recorded as a ticket comment.

## Security notes
Data classification: **Internal**. The runbook must contain **no secrets, no key material, no real audit payloads and no real usernames** — examples use placeholders. The break-glass section describes *that* the path exists and what happens afterwards (loud surfacing, mandatory audit, owner notification) without describing anything that would help an attacker use it. Security engineer reviews the break-glass and elevation sections before merge.

## Accessibility notes
N/A — documentation ticket with no UI surface. Markdown must still use proper heading hierarchy and tables with header rows so it is navigable with a screen reader.

## Performance notes
N/A — documentation only. The measured performance figures from E42-K01 and E42-Q03 are transcribed into the risk register and the ADR so future regressions have a baseline to be compared against.

## Observability
N/A — no runtime component. The runbook does document which Grafana dashboard and which alerts correspond to each admin subsystem, so the observability added by the other tickets is discoverable.

## Definition of Done
- [ ] ADR-0010 amended and reviewed by the Architect and the Security engineer.
- [ ] `22-api-openapi.yaml`, `23-ws-protocol.md`, `14-screens-catalogue.md` and `32-risk-register.md` reconciled with shipped behaviour.
- [ ] `docs/ops/admin-runbook.md` written and dry-run by someone other than the author.
- [ ] Doc-lint and link-check green; contract tests green with no skips.
- [ ] PR merged via the merge queue with 2 approvals including a code-owner.

## Dependencies
- **E42-T01, E42-T02, E42-T03** — the behaviour being documented must exist first; documenting a design rather than an implementation is how these documents rot.

## Branch
`docs/admin-screens-adr-and-runbook`. Single PR.

""" + REF))
