# E07 — Implementation-level STRIDE threat model: recorder data & storage

- Ticket: `E07-X01` (issue #172) · Classification: **Internal** (no live hostnames, deployed ports, or credentials below)
- Status: **Draft for Security Engineer + Architect review**
- Scope: what E07 actually builds at R0 end — QuestDB hot tier, Parquet/DuckDB cold tier, the Postgres
  relational surface E07-T02 adds (recorder/retention tables, `cv_ro`/`cv_app`/`cv_owner` roles), the
  exporter/manifest, the compactor, the retention reaper, and the Alembic migration path for those tables.
- Out of scope (per ticket): auth/RBAC modelling (E09), exchange-boundary threats (E08), key management /
  envelope encryption (E27/E09 — this model only asserts no key material reaches the storage tier E07 builds).
- Planning-level baseline: `docs/plan/04-security-program.md` §5.8 (Area 8, threats S1–S6). This document
  is the implementation-level companion; §1 below reconciles every planning threat against the real design.

## 1. Assets, actors, trust boundaries in scope

**Assets** (ids from `04-security-program.md` §3):

- **A-10** recorded market data — QuestDB (hot, `CV_RECORDER_HOT_DAYS` default 7) and Parquet (cold,
  `CV_RECORDER_RETENTION_DAYS` default 30, pinned = forever), per ADR-0003.
- **A-12** journal & analytics surface exposed through the DuckDB view layer over Parquet plus the
  `cv_ro` read-only Postgres role.
- **A-13** backups (Postgres dumps, Parquet archives, config) on the local encrypted volume + off-box target.
- New (this ticket): the relational privilege surface E07-T02 creates — `cv_app` (read/write, no DDL),
  `cv_owner` (DDL + migrations), `cv_ro` (read-only, analytics/DuckDB attachment) — and the recorder
  tables (`recorded_symbols`, `recording_sessions`, `recording_gaps`, `retention_policies`,
  `replay_sessions`, migration `0007_recorder`).

**Trust boundaries touched**:

- **TB-3** host → WSL/docker-compose network (loopback binds only; no `0.0.0.0`; SR-047).
- **TB-6** live data → backups (encryption at rest with a separate backup key; SR-090..SR-095).
- **New internal boundary** (this ticket names it **TB-3a**): the analytics path (DuckDB attaching Postgres
  read-only via `cv_ro`, reading Parquet directly) vs the ledger of record (Postgres via `cv_app`/`cv_owner`).
  DuckDB's Postgres attachment is read-only at the role level, not just by convention: `cv_ro` has no
  `INSERT`/`UPDATE`/`DELETE`/`DDL` grants, enforced by the `0002_rbac_seed`-style grant migration and a
  privilege-introspection test (`\du`/`information_schema.role_table_grants` assertion) added in E07-T02.

**Actors** (ids from `04-security-program.md` §3):

- **AC-07** recorder/ingestion worker — machine identity, medium trust, holds no user credentials, writes
  ILP to QuestDB and Parquet/manifest files; cannot reach Postgres OMS tables.
- **AC-12** LAN network adversary — anything that can reach the docker-compose network segment (TB-3),
  e.g. a compromised container or a device on the same LAN if a bind is ever misconfigured.
- **AC-01/AC-02** Owner/Manager — reach storage only through admin endpoints (export, replay, retention
  config), never directly; RBAC enforcement of those endpoints is E09's model, referenced not re-derived.

## 2. Per-element STRIDE enumeration

Format matches `04-security-program.md` §5.8 for continuity (T id, STRIDE, Threat, L, I, Risk,
Mitigations with SR ids, Residual). New/re-rated threats use the `S1x` series so they merge cleanly into
§5.8 without renumbering S1–S6.

### 2.1 ILP write path (recorder → QuestDB)

| T   | STRIDE            | Threat                                                                                                                                | L   | I   | Risk           | Mitigations                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Residual |
| --- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------- | --- | --- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| S1  | Tampering         | Silent corruption of Parquet archives makes replay/backtests wrong                                                                    | M   | M   | Medium         | **Confirmed as planning-rated.** SR-094 per-file checksum manifest verified on read and by a weekly scrub job. Implementation detail (abuse case 6, §3): the manifest entry is written in the same batch as the file it describes, by the same writer, so a corrupted disk that flips bits in the data file after the fact is caught (checksum mismatch), but a compromised writer that corrupts both together is not — see §3.6 for the accepted-risk reasoning. | Low      |
| S10 | Denial of service | ILP client on the recorder floods QuestDB faster than it can flush, causing unbounded WAL growth on the same volume as hot query data | M   | H   | **High** (new) | SR-096 disk-budget guard extended: the ILP writer is rate-limited to the recorder's configured symbol/depth budget (no user input reaches this path — AC-07 only); QuestDB `cairo.max.uncommitted.rows`/commit-lag configured conservatively; disk-usage alert at 75%, automatic recording pause at 90% applies here too, not just to Parquet growth                                                                                                              | Low      |
| S11 | Repudiation       | ILP has no per-row authentication; a rogue process on the TB-3 network could inject fabricated rows attributed to the recorder        | L   | M   | Low (new)      | QuestDB ILP endpoint is loopback/WSL-internal only (SR-047, TB-3); no other process is granted network reach to the ILP port; `recording_sessions` rows are the audited record of what the recorder itself believes it wrote, so a divergence is detectable by session/gap reconciliation (`recording_gaps`) even though ILP itself is unauthenticated                                                                                                            | Low      |

### 2.2 PGWire read path (query layer → QuestDB)

| T   | STRIDE                 | Threat                                                                                                              | L   | I   | Risk         | Mitigations                                                                                                                                                                                                             | Residual |
| --- | ---------------------- | ------------------------------------------------------------------------------------------------------------------- | --- | --- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| S12 | Information disclosure | A backend module other than the storage repository layer opens a direct PGWire connection and bypasses scope checks | L   | M   | Low (new)    | ADR-0003 binding rule: all storage access goes through `services/api/candleviewer/storage/` repository interfaces; import-linter boundary (CONSTITUTION §3) forbids other modules importing the QuestDB driver directly | Low      |
| S13 | Elevation of privilege | PGWire credentials for the query role are broad enough to run DDL against QuestDB                                   | L   | H   | Medium (new) | The query-path role used over PGWire is read-only at the QuestDB permission level (no `CREATE`/`DROP`/`ALTER`); DDL only via the recorder's own bootstrap, run once at startup by AC-07                                 | Low      |

### 2.3 Exporter + manifest

| T   | STRIDE                 | Threat                                                                                                   | L   | I   | Risk      | Mitigations                                                                                                                                                                                                                                                                                                                                                                                                     | Residual |
| --- | ---------------------- | -------------------------------------------------------------------------------------------------------- | --- | --- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| S3  | Elevation of privilege | Replay/export endpoint used to read arbitrary filesystem paths                                           | M   | H   | **High**  | **Confirmed as planning-rated.** SR-097 no user-supplied paths; dataset ids resolved through a registry keyed by `(symbol, date, env)`, not a path string; path-traversal tests include symlinked partition directories (abuse case 3, §3.3) — the registry resolves to a canonical path under `CV_COLD_ROOT` and rejects any resolution that escapes it via `os.path.realpath` comparison, not string matching | Low      |
| S4  | Information disclosure | Journal exports contain account identifiers shared across managers                                       | M   | M   | Medium    | **Confirmed as planning-rated.** SR-098 export scoping by role + explicit "includes account data" confirmation; every export request is checked against the requesting Manager's `user_account_access` grants before the dataset registry is consulted (abuse case 1, §3.1)                                                                                                                                     | Low      |
| S14 | Tampering              | Exported dataset's manifest is regenerated from a stale checksum after a partition is silently rewritten | L   | M   | Low (new) | Parquet partitions are append-only/immutable per ADR-0003 and `60-database-migrations.md`-equivalent storage rule (never rewrite historical partitions in place); the exporter refuses to serve a dataset whose on-disk mtime postdates its manifest entry without a corresponding manifest regeneration event in the audit log                                                                                 | Low      |

### 2.4 Compactor

| T   | STRIDE            | Threat                                                                                                                                              | L   | I   | Risk         | Mitigations                                                                                                                                                                                                                                                                                        | Residual |
| --- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | --- | --- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| S15 | Tampering         | Compaction merges partitions and drops rows on a crash mid-write, leaving a gap invisible to the manifest                                           | M   | M   | Medium (new) | Compactor writes to a temp partition and atomically renames on success (`os.replace`/equivalent), never in-place; a crash leaves the temp file orphaned, not a corrupted target; the manifest is updated only after the rename succeeds; `recording_gaps` reconciliation is the detection backstop | Low      |
| S16 | Denial of service | Compaction runs concurrently with export/replay reads on the same partition and starves them of I/O, or an in-flight rename is read as partial data | L   | L   | Low (new)    | Atomic rename means readers see either the old or the new partition, never a partial one; compaction is scheduled off-peak and rate-limited so it does not compete with the trading path for I/O (ties into S10's disk/I/O budget)                                                                 | Low      |

### 2.5 DuckDB view layer + Postgres attachment

| T   | STRIDE                 | Threat                                                                                                                                                                                     | L   | I   | Risk           | Mitigations                                                                                                                                                                                                                                                                                                                                                      | Residual |
| --- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --- | --- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| S17 | Elevation of privilege | DuckDB's Postgres attachment (used for cross-tier analytics joins) is opened with `cv_app`/`cv_owner` credentials instead of `cv_ro`, giving the analytics path write access to the ledger | M   | H   | **High** (new) | TB-3a (§1) is enforced structurally: the DuckDB attachment configuration is hard-coded to `cv_ro` in the analytics module, never operator-configurable per query; E07-T02 ships a privilege-introspection test asserting `cv_ro` has zero write/DDL grants, and a contract test that the analytics module's connection string never contains `cv_app`/`cv_owner` | Low      |
| S18 | Information disclosure | A DuckDB view exposes S-class or P2-class Postgres columns (per `21-database-schema.md` §12) to the analytics/export path                                                                  | M   | H   | **High** (new) | Views are built by explicit column projection, never `SELECT *`, mirroring the Semgrep rule in §12 of the schema doc; the recorder/retention tables E07 creates hold no S-class columns (see §5 below), so this risk is bounded to E07-T02's view definitions, checked in that ticket's PR                                                                       | Low      |

### 2.6 Retention reaper

| T   | STRIDE                 | Threat                                                                                                                                                  | L   | I   | Risk                                 | Mitigations                                                                                                                                                                                                                                                                                                                                                                                                                  | Residual |
| --- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | --- | --- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| S5  | Tampering              | Retention job deletes pinned data                                                                                                                       | L   | M   | Low                                  | **Confirmed as planning-rated.** SR-099 pin flag honoured; dry-run report before destructive runs; deletions audited (abuse case 4, §3.4)                                                                                                                                                                                                                                                                                    | Low      |
| S19 | Elevation of privilege | A Manager (not just the Owner) can change global retention policy and set `hot_days=0`, destroying the recording for everyone, not just their own scope | M   | H   | **High** (new — hand-off to E07-T05) | Retention-policy mutation is Owner-only (mirrors SR-055's "role changes are owner-only" pattern); every retention-policy change is a distinct audited action (actor, before/after) separate from the deletion it later triggers; the reaper itself performs export-verified-before-drop (§4) so even an Owner-authorised destructive policy change cannot destroy unreplicated data without a prior successful backup/export | Low      |
| S2  | Denial of service      | Unbounded recording fills the disk, taking the backend (and trading) down                                                                               | H   | H   | **Critical**                         | **Confirmed as planning-rated.** SR-096 disk-budget guard: retention 30 d default, per-symbol caps, alert at 75%, automatic recording pause at 90%; trading path must not share the fillable volume (abuse case 5, §3.5)                                                                                                                                                                                                     | Low      |

### 2.7 Alembic migration path (recorder/retention tables, `0007_recorder`)

| T   | STRIDE    | Threat                                                                                                                            | L   | I                                  | Risk                                 | Mitigations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Residual |
| --- | --------- | --------------------------------------------------------------------------------------------------------------------------------- | --- | ---------------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| S20 | Tampering | A migration authored under E07 drops or rewrites an audited table (e.g. `recording_sessions`, or any future audit-adjacent table) | L   | **Critical**-impact if it occurred | **High** (new — hand-off to E07-T02) | CODEOWNERS on `backend/db/**`-equivalent path (`services/api/candleviewer/migrations/`, mirrored per repo layout) requires the data-owner approval in addition to the standard two (`21-database-schema.md` §9.3 rule 13); migrations are forward-only, never edit an applied revision (C-5.4, rule 9); the deploy pipeline's `pre_migration` backup (rule 8) means any destructive migration is recoverable from the immediately-preceding backup even if review fails to catch it (abuse case 7, §3.7) | Low      |

### 2.8 Data-store network binds

| T   | STRIDE                 | Threat                                                                                                                                                | L   | I   | Risk         | Mitigations                                                                                                                                                                                                                                                                                                                                                      | Residual |
| --- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | --- | --- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| S6  | Information disclosure | QuestDB/DuckDB consoles exposed without auth                                                                                                          | M   | H   | **High**     | **Confirmed as planning-rated.** SR-048 no data-store port published to the host; console disabled or loopback-bound with credentials (abuse case 2, §3.2)                                                                                                                                                                                                       | Low      |
| S21 | Information disclosure | Postgres itself (not just QuestDB's HTTP console) is published to `0.0.0.0` by a compose misconfiguration, exposing `cv_owner` credentials to the LAN | L   | H   | Medium (new) | Same TB-3 control as S6, generalised: SR-047's startup `ss`/`netstat` healthcheck asserts every data-store bind (QuestDB PGWire/HTTP/ILP, Postgres, DuckDB has none) is loopback/WSL-internal, not just QuestDB's console; this is a healthcheck assertion added in E07-T02/T03, not a new SR — it is the existing SR-047 applied to all three stores explicitly | Low      |

## 3. Abuse cases (adversary narratives, each with a concrete test and an owner)

1. **"As a Manager with `recording:read`, I enumerate another user's symbols and infer their strategy."**
   Targets S4. Test: integration test in **E07-Q01** — Manager A requests an export for a symbol/date range
   only Manager B has `user_account_access` for; assert 403 and an audit entry for the denied attempt.
2. **"As anything that can reach the host, I open the QuestDB HTTP console and read the tape."**
   Targets S6/S21. Test: chaos scenario in **E07-Q04** — attempt an unauthenticated HTTP GET against every
   published compose port from outside the WSL-internal network; assert connection refused/timeout for
   all data-store ports.
3. **"As a caller of any read endpoint, I supply a dataset id that resolves outside `CV_COLD_ROOT`, including via a symlinked partition directory."**
   Targets S3. Test: unit + integration in **E07-Q01** — dataset registry resolution test with a symlink
   planted inside a partition directory pointing outside `CV_COLD_ROOT`; assert rejection before any file
   read is attempted.
4. **"As a user who can change retention, I set `hot_days=0` globally and destroy the recording."**
   Targets S5/S19. Test: **E07-Q01** — non-Owner role attempts the policy mutation (403); Owner performs
   it and the reaper's dry-run report is asserted to run and be logged before any deletion executes.
5. **"As a process on the box, I fill the recording volume and take trading down with it."**
   Targets S2/S10. Test: **E07-Q04** chaos — synthetic writer fills the recording volume toward 90%;
   assert the automatic pause fires and the trading path (on a separate volume/mount) is unaffected.
6. **"As a corrupted disk, I return a Parquet file whose checksum still matches its stale manifest entry."**
   Targets S1/S14. Test: **E07-Q04** chaos — bit-flip a data file without touching its manifest entry;
   assert the weekly scrub job (SR-094) flags the mismatch. See §3.6 below for the manifest-binding caveat.
7. **"As a migration author, I ship a revision that drops an audited table."**
   Targets S20. Test: **E07-X02** (control verification) — CI-style check that a migration touching an
   audited table without the data-owner CODEOWNER approval is blocked; manual procedure: attempt to merge
   such a PR on a scratch repo and confirm the required-review gate holds.

**§3.6 manifest-file binding — reasoning recorded for the reviewer**: the checksum manifest entry is
integrity, not authenticity — it proves the file has not changed since the manifest was written, not that
the manifest-writer was honest. This is **accepted at this threat level**: the adversary model for A-10 in
this area is disk/media corruption (S1) and a non-privileged process filling or racing the filesystem
(S10/S15/S16), not a privileged attacker with write access to both the data file and its manifest entry —
that actor already has the access needed to fabricate market history regardless of the manifest, and is
out of scope for this area (a compromised recorder process is an AC-07 trust-level question, not a
storage-tier control gap). If a future epic (R3 journal exports, replay endpoints exposed more broadly —
see §6) widens who can write into the cold tier, this reasoning must be revisited.

## 4. Constraint hand-off to E07-T05 (retention/reaper implementation)

E07-T05 **must** implement the reaper's control flow in this order, each step gated on the previous
succeeding, traceable to the SR ids below:

1. **Alert before delete** — disk-threshold and pending-deletion alerts fire before any destructive action
   is taken (SR-096).
2. **Dry-run first** — every retention run produces a dry-run report (what would be deleted, sizes, pin
   status) that is persisted and available for review before the destructive run is permitted (SR-099).
3. **Pins honoured** — the pin flag on `recorded_symbols`/dataset rows is checked immediately before each
   individual deletion, not just at dry-run time, closing the window where a pin set between dry-run and
   execution would otherwise be ignored (SR-099).
4. **Export verified before drop** — if a retention policy or manual action would remove the only copy of
   a dataset, the reaper requires a successful, checksum-verified export/backup to complete first (SR-094
   for the checksum, SR-099 for the pin/audit linkage); this is the control that makes S19 (Owner-approved
   global `hot_days=0`) safe even when authorised.
5. **Deletion audited** — every deletion (individual file, partition, or bulk retention sweep) writes an
   audit record before the filesystem/DB delete is acknowledged as complete (SR-099, C-2.9 pattern).

A reviewer verifying E07-T05 traces each of the five steps above to its SR id and confirms the ordering is
enforced in code (not just documented), per the ticket's acceptance criteria.

## 5. Data classification confirmation (E07 revisions)

Per `21-database-schema.md` §12, every column created by E07's migration (`0007_recorder`:
`recorded_symbols`, `recording_sessions`, `recording_gaps`, `retention_policies`, `replay_sessions`) is
reviewed against the classification levels (P0/P1/P2/S):

| Table                | Columns (representative)                                        | Class                                                                                                                                    | Reasoning                                                                  |
| -------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `recorded_symbols`   | symbol, exchange, env, pin flag                                 | P0                                                                                                                                       | Instrument/config identifiers, no personal or secret data                  |
| `recording_sessions` | started_at, ended_at, status, gap counts                        | P0                                                                                                                                       | Operational telemetry                                                      |
| `recording_gaps`     | symbol, range, reason                                           | P0                                                                                                                                       | Operational telemetry                                                      |
| `retention_policies` | hot_days, retention_days, pinned, changed_by (FK to `users.id`) | P0, except `changed_by` which is a reference — the identifying data lives in `users` (already classified P1 in §12), not duplicated here | No new P1/P2/S surface; `changed_by` joins to an existing classified table |
| `replay_sessions`    | requested_by (FK), symbol, date range, status                   | P0, `requested_by` as above                                                                                                              | Same reasoning                                                             |

**Conclusion**: E07's recorder/retention schema introduces **no new P1, P2, or S-class columns**. No key
material, credentials, or PII is created by this migration set, consistent with this ticket's out-of-scope
statement on key management. This satisfies the ticket's Definition-of-Done item on data classification
and needs no new row added to §12 of `21-database-schema.md`.

## 6. R3 forward-looking warnings

Recorded here so later epics inherit the warning rather than rediscovering it (per this ticket's technical
notes):

- **Journal exports (R3)** will broaden who can pull data through the exporter (§2.3); re-check S3/S4/S14
  against whatever new export surface ships — the dataset-registry and role-scoping controls must extend,
  not be bypassed by a new endpoint.
- **Replay endpoints (R3)** exposed more broadly reopen the manifest-authenticity caveat in §3.6: if replay
  becomes reachable by a lower-trust actor than AC-07/AC-01/AC-02 today, the "corruption not a privileged
  attacker" adversary model must be re-derived, not assumed to still hold.

## 7. Residual-risk table (rollup)

| Threat id                              | Area                                                | Residual (post-mitigation)                                                                        | Sign-off needed?                                                                                                               |
| -------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| S1, S2, S3, S4, S5, S6                 | Confirmed at planning-level rating                  | Low (S2/S3/S6 start High/Critical, mitigated to Low)                                              | No — matches §5.8 baseline                                                                                                     |
| S10, S11, S12, S13, S14, S15, S16, S21 | New, implementation-level                           | Low                                                                                               | No                                                                                                                             |
| S17, S18                               | New — DuckDB/Postgres attachment privilege boundary | Low, contingent on E07-T02 shipping the `cv_ro` grant test named in §2.5                          | **Yes** — tracked as a High-rated threat until E07-T02's privilege-introspection test lands; not accepted silently (see below) |
| S19, S20                               | New — hand-off constraints to E07-T05/E07-T02       | Low, contingent on the ordered control flow (§4) and CODEOWNERS gate (§2.7) shipping as specified | **Yes** — same contingency pattern as S17/S18                                                                                  |

**No threat in this model is left rated High or Critical without a named mitigating control and an owning
ticket.** S17/S18/S19/S20 are rated Low _after_ mitigation, but that mitigation is implemented by tickets
this one blocks or informs (E07-T02, E07-T05) rather than by this ticket itself — per this ticket's DoD,
those are flagged for the Owner's attention at Security Review (§8) as "mitigation contingent on named
ticket", not left untriaged. If E07-T02/T05 ship without the named control, the threat reverts to its
pre-mitigation High rating and must be re-triaged at that PR's security review.

## 8. Traceability: abuse case → test → ticket

| Abuse case (§3)                                       | Targets | Test                                                                | Owning ticket |
| ----------------------------------------------------- | ------- | ------------------------------------------------------------------- | ------------- |
| 1. Manager enumerates another manager's symbols       | S4      | Integration: export scope-check denial + audit                      | E07-Q01       |
| 2. Unauthenticated console access                     | S6, S21 | Chaos: port-reachability sweep from outside TB-3                    | E07-Q04       |
| 3. Path traversal via dataset id / symlink            | S3      | Unit + integration: registry resolution rejects escape              | E07-Q01       |
| 4. Global `hot_days=0` by non-Owner / pin-window race | S5, S19 | Integration: RBAC denial + dry-run-before-destructive assertion     | E07-Q01       |
| 5. Disk-fill DoS                                      | S2, S10 | Chaos: synthetic fill to 90%, assert pause + trading-path isolation | E07-Q04       |
| 6. Stale-manifest corruption                          | S1, S14 | Chaos: bit-flip data file, assert scrub-job detection               | E07-Q04       |
| 7. Migration drops an audited table                   | S20     | Control verification: CODEOWNER-gate + forward-only enforcement     | E07-X02       |

### 8.1 Control-to-ticket map

Every E07-* ticket appears here; a missing row is a model defect (enforced by GOV-008,
`scripts/check_threat_model_ticket_map.py`). A ticket with no control says so explicitly.

| Ticket  | Obligation                                                                                                                                                                                                                   |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| E07-X01 | Self-row: this model (S1-S21, abuse cases 1-7, §4 hand-off to E07-T05); no runtime control                                                                                                                                   |
| E07-X02 | Verifies SR-047/048/090-099 and adds SAST/DAST rules (raw-SQL Semgrep, path-traversal probe); abuse case 7                                                                                                                   |
| E07-T01 | M10 storage package: repository Protocols are the only storage access path (no direct SQL/ILP elsewhere); import-linter contract; in-memory fakes. Supports S3/S4 scoping at the registry boundary                           |
| E07-T02 | Postgres tier: `cv_app`/`cv_ro` privilege split and privilege-introspection test (S17/S18), forward-only/CODEOWNERS migration gate (S20), SR-047 bind healthcheck for Postgres (S21), explicit-projection DuckDB views       |
| E07-T03 | QuestDB tier: ILP writer rate limit and never-drop/typed errors (S10, SR-096), loopback-only ILP/PGWire/HTTP (S11, SR-047/048, S6), SQL identifier guards, SR-047 healthcheck (S21)                                          |
| E07-T04 | Parquet cold tier: per-file SHA-256 manifest written with the file, verified on read and by weekly scrub (S1, SR-094); registry-resolved canonical paths under `CV_COLD_ROOT` (S3, SR-097); role-scoped exports (S4, SR-098) |
| E07-T05 | Retention reaper: implements the five ordered steps of §4 (alert before delete SR-096; dry-run SR-099; pin re-check per deletion; export verified before drop SR-094/099; deletion audited) - S2, S5, S19                    |
| E07-T06 | No control; ADR-0008 hot-tier decision consumes K01 measurements and preserves the TB-3 / SR-047 constraints of ADR-0003                                                                                                     |
| E07-K01 | No control; benchmark spike on recorded fixtures only, no network or secrets; informs T06                                                                                                                                    |
| E07-D01 | No control; operator content model for StorageUsage telemetry, exposes aggregate usage only (no paths, S3)                                                                                                                   |
| E07-D02 | No control; verifies the shipped StorageUsage payload against D01 (no path or account leakage, S3/S4)                                                                                                                        |
| E07-Q01 | Verifies abuse cases 1, 3, 4: export scope denial (S4), path-escape rejection (S3), RBAC and dry-run-before-destructive (S5/S19)                                                                                             |
| E07-Q02 | No control; exploratory charters on tier boundaries, pin-during-reaper races (S5/S19) and export idempotency (S1)                                                                                                            |
| E07-Q03 | No control; performance harness for ILP ingest, query shapes and export throughput; exercises S10 flood limits, records baselines only                                                                                       |
| E07-Q04 | Verifies abuse cases 2, 5, 6: port-reachability sweep (S6/S21), disk-fill pause at 90% (S2/S10), bit-flip scrub detection (S1/S14)                                                                                           |

## 9. Definition of Done cross-check

- [x] Model document drafted — pending Security Engineer + Architect review (governance C-10.1 v1.1.0:
      independent agent reviews via PR; per this sprint's agent-delivery adaptations, human sign-off is
      represented by the required PR reviews, not blocked on here).
- [x] `04-security-program.md` §5.8 updated with new/re-rated threats (S10–S21) — see accompanying diff.
- [x] Abuse-case → test traceability table complete (§8), every case owned by a named ticket.
- [x] Constraints handed to E07-T05 before implementation starts (§4) — this ticket blocks E07-T05.
- [x] High/Critical threats (S2, S3, S6 baseline; S17/S18/S19/S20 new) each mitigated by a named control
      and owning ticket, or explicitly flagged contingent-on-ticket per §7 — none left untriaged.
- [x] Data classification confirmed for every column E07's `0007_recorder` migration creates (§5) — no new
      P1/P2/S columns.
- [ ] Findings presented at a Security Review — scheduled as part of this PR's review cycle.
