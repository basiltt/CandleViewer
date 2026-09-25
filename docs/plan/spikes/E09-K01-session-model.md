# E09-K01 spike findings: session model reconciliation

Spike ticket E09-K01 (issue #134). Decision recorded in
`docs/plan/27-adrs/ADR-0017-session-access-token-and-revocation-model.md`. This note is the
"written reconciliation note listing every edit needed to `21-database-schema.md` §3.1.4 and
`24-internal-schemas.md` §15.1 so the two agree" required by the ticket's Scope/Deliverables and
by the Gherkin scenario "The two schema documents are made to agree".

**Not shippable.** This spike branch is archived, not merged (ticket DoD). Follow-up edits to the
two normative documents below must be filed as review items / a small edit PR against **E09-T01**
(and any behavioural piece against **E09-S03**) — this note enumerates them, it does not apply them.

## Field-level divergences and resolutions

| Field | `21-database-schema.md` §3.1.4 (`sessions` table) | `24-internal-schemas.md` §15.1 (`Session` model) | Resolution (binding for E09-T01) |
|---|---|---|---|
| Absolute lifetime | `expires_at`, "Absolute 12 h" | `expires_at: TsUs # 12 h absolute` | **Agree already.** No edit. |
| Idle lifetime | `last_seen_at` + comment "Idle timeout 30 min" (no separate column — idle deadline is *computed* as `last_seen_at + 30min`) | separate stored field `idle_expires_at: TsUs` | **Resolve to computed, not stored** (matches the DB table, which has no `idle_expires_at` column). Edit `24-internal-schemas.md`: replace `idle_expires_at: TsUs` with a `@property idle_expires_at` derived from `last_seen_at`, OR add `last_seen_at` to the DB-facing `Session` DTO and drop the stored idle field from the wire model, whichever the E09-T01 author prefers — either is acceptable as long as only one of {stored idle deadline, computed from last_seen_at} exists. Recording two independent idle clocks (DB vs API model) risks them drifting under a paused/replayed session; the DB row is authoritative.
| Refresh lifetime | Not modelled as a column at all — refresh liveness *is* `sessions.revoked_at IS NULL` (rotation walk); there is no independent 7-day field | `refresh_expires_at: TsUs # 7 d` | **Add an explicit absolute refresh ceiling.** The DB table currently has no cap on how long a *rotation family* can keep renewing itself (only the per-token `access_token_jti`/`expires_at` and the walk-on-reuse). Per this spike's ADR-0017, add `sessions.refresh_expires_at timestamptz NOT NULL` seeded at family creation (`root.expires_at + 7 days`, propagated unchanged on every rotation in the family, not reset per rotation) to `21-database-schema.md` §3.1.4, and keep `24-internal-schemas.md`'s field as-is (already correct) — the DB was missing the column, not the model.
| Step-up representation | `mfa_satisfied_at timestamptz` (nullable, "Step-up freshness window (15 min)") | `elevated_until: TsUs | None # step-up window for dangerous actions` **and** `mfa_satisfied: bool` (two fields) | **Single source of truth: `mfa_satisfied_at`.** Per ADR-0017 and the B16 statechart contract note (`24-internal-schemas.md` §15.1 itself says `elevated_until` is "derived from the elevation region rather than stored independently"), drop both `elevated_until` and `mfa_satisfied: bool` from the `Session` Pydantic model in `24-internal-schemas.md` and replace with `mfa_satisfied_at: TsUs | None`, with `elevated_until` computed as a property (`mfa_satisfied_at + timedelta(minutes=15)` when set) wherever the API needs to expose it. This makes the wire model match the DB column 1:1.
| Access-token identity | `access_token_jti uuid` (nullable) — named "jti" but is described as "Latest access token id for revocation", i.e. an opaque handle, not a JWT claim | No equivalent field on `Session` at all | **Rename and add.** Per ADR-0017 (opaque access token, not JWT), rename `sessions.access_token_jti` to `sessions.access_token_id` in `21-database-schema.md` (the `jti` name presumes a JWT claim that this ADR rejects; keep the column, just rename it — no migration needed until E09-T01 since no code exists yet) and add a matching `access_token_id: UUID | None` field to the `Session` model in `24-internal-schemas.md` §15.1, or (preferred, see ADR-0017 §1) split it into its own `access_tokens` table keyed by the opaque handle with a FK to `session_id`, so a session can rotate its access token every 11 minutes without rewriting the `sessions` row each time. Either shape is acceptable; the two documents must pick the same one.
| `is_electron`, `tailscale_node`, `device_label`, `ip`, `user_agent` | Present, typed | Not modelled on `Session` at all (no PII/telemetry fields) | **Not a real divergence** — `24-internal-schemas.md`'s `Session` is the API/runtime-facing DTO; these fields are appropriately DB-only (or exposed via a separate `listMySessions` response shape per line 3674) and should **not** be added to the internal-schemas `Session` model. No edit; note the intentional scope difference explicitly so a future reviewer doesn't "fix" it into an actual divergence.
| `revoked_reason` enum values | `logout / rotated / password_change / admin_revoke / mfa_reset / rotation_reuse` | Not modelled (only `revoked_at: TsUs | None`) | **Add `revoked_reason` to the `Session` model** as `Literal["logout","rotated","password_change","admin_revoke","mfa_reset","rotation_reuse"] | None`, matching the DB enum, so `listMySessions`/`revokeMySession` can surface *why* a session ended without a second lookup. |

## Summary of edits required (for the E09-T01 author)

1. `21-database-schema.md` §3.1.4: add `sessions.refresh_expires_at`; rename `access_token_jti` →
   `access_token_id` (or extract an `access_tokens` table per ADR-0017 §1).
2. `24-internal-schemas.md` §15.1: replace `idle_expires_at` with a computed property (or promote
   `last_seen_at` into the DTO); replace `elevated_until` + `mfa_satisfied: bool` with a single
   `mfa_satisfied_at: TsUs | None` (computed `elevated_until` property); add `access_token_id` and
   `revoked_reason` fields to match the DB row.
3. Both documents already agree on the 12 h absolute lifetime — leave untouched.
4. No change needed to the PII-only DB columns (`ip`, `user_agent`, `device_label`, `is_electron`,
   `tailscale_node`) — they are intentionally DB-only, not part of the runtime `Session` DTO.

## Evidence

All six Gherkin scenarios in the ticket are exercised by
`docs/plan/spikes/E09-K01-harness/test_harness.py` (6 passed):

- `test_revocation_is_effective_immediately_next_check` — revoke+check well under the 5 s budget
  (US-ONB-009).
- `test_lookup_p50_p99_under_budget` — p99 lookup << 2 ms decision threshold (opaque handle wins).
- `test_ws_reauth_cadence_at_most_once_per_ten_minutes` — 20 connections, 1 simulated hour, exactly
  one re-auth per 10 minutes, zero reconnects triggered by refresh.
- `test_rotated_token_reuse_kills_entire_family` — reuse of a rotated token revokes the whole chain
  and emits `auth.refresh_reuse_detected` at `critical`.
- `test_rotation_family_walk_cost_at_10k_rows` — 10,000-row chain revoked in one O(depth) walk, well
  under 5 s.
- `test_access_token_ttl_matches_adr_decision` — pins the 11-minute TTL the cadence test assumes.

## Deferred

A real Postgres-backed latency measurement was not run: `services/api` does not exist yet
(pre-`INFRA-001`/`E03`) and docker is not available in this environment. The in-memory harness
measures the same O(1)-lookup / O(depth)-walk algorithmic shape the real schema would have under a
primary-key/hash index, which is what the ticket's decision criterion (p99 < 2 ms) is actually
gating on, but this is explicitly *not* a Postgres benchmark. E09-T01/S03 should re-run an
equivalent measurement against a seeded Postgres instance before the numbers here are treated as
a production SLO.

## Risk register

No new risk beyond what `32-risk-register.md` already tracks for session/auth (owner review of
`docs/plan/32-risk-register.md` deferred to the owner per the ticket's DoD "if a new risk
surfaced" — none did; the reconciliation above closes an existing ambiguity rather than opening a
new one).
