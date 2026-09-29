"""append-only hash-chained audit_log + audit_checkpoints (E09-T02, M19)

Revision ID: 0003_audit_log
Revises: 0002_rbac_seed
Create Date: 2026-09-29

Creates, verbatim against `docs/plan/21-database-schema.md` Sec.3.10.1 and
the shared Sec.1.2/Sec.1.4 definitions this ticket is the first to need:
enums `exchange_env`, `audit_outcome`, `severity`; the shared
`forbid_mutation()` trigger function; the `audit_log` table with its
`au_action_fmt` CHECK, every listed index, the `audit_chain()` trigger
function (BEFORE INSERT — computes `prev_hash`/`entry_hash`, genesis
`prev_hash` = 64 zeros) and the `trg_audit_append` BEFORE UPDATE OR DELETE
trigger (`forbid_mutation()`); the `REVOKE UPDATE, DELETE ON audit_log FROM
cv_app, cv_ro` grant (defence-in-depth on top of the `pg_bootstrap.sql`
backstop added by E07-T02, which only fires when the table already exists —
this revision is the one that actually creates it); and `audit_checkpoints`.

The canonical serialisation hashed by `audit_chain()` matches
`21-database-schema.md` exactly (sorted-field concatenation order fixed by
the SQL below, not by this migration) and must never change without a
documented chain-break checkpoint (ticket "Technical notes / design").

Inserts are expected to be serialised by the writer taking
`pg_advisory_xact_lock(hashtext('audit_log'))` for the duration of the
insert (ticket "Technical notes"); this migration does not itself take that
lock (DDL only, one-time), but documents the requirement for
`candleviewer.audit.writer.AuditWriter`, the sole caller.

Out of scope for this revision: `system_events`, `backups`, `outbox`
(Sec.3.10.2-3.10.4) — those land with their owning epics.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_audit_log"
down_revision: str | None = "0002_rbac_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_UPGRADE_SQL = """
CREATE TYPE exchange_env  AS ENUM ('live','demo','testnet');
CREATE TYPE audit_outcome AS ENUM ('success','failure','denied');
CREATE TYPE severity      AS ENUM ('debug','info','warning','error','critical');

CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $BODY$
BEGIN RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME; END $BODY$;

CREATE TABLE audit_log (
  id            bigserial PRIMARY KEY,
  prev_hash     sha256_hex NOT NULL,
  entry_hash    sha256_hex NOT NULL UNIQUE,
  actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  actor_label   text NOT NULL,
  actor_ip      inet,
  session_id    uuid,
  action        text NOT NULL,
  object_kind   text,
  object_id     text,
  object_label  text,
  outcome       audit_outcome NOT NULL DEFAULT 'success',
  severity      severity NOT NULL DEFAULT 'info',
  reason        text,
  before_state  jsonb,
  after_state   jsonb,
  request_id    uuid,
  env           exchange_env,
  event_ts      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT au_action_fmt CHECK (action ~ '^[a-z0-9_]+([.][a-z0-9_]+){1,3}$')
);
CREATE INDEX ix_audit_time    ON audit_log (event_ts DESC);
CREATE INDEX ix_audit_actor   ON audit_log (actor_user_id, event_ts DESC);
CREATE INDEX ix_audit_action  ON audit_log (action, event_ts DESC);
CREATE INDEX ix_audit_object  ON audit_log (object_kind, object_id, event_ts DESC);
CREATE INDEX ix_audit_sev     ON audit_log (severity, event_ts DESC) WHERE severity IN ('error','critical');
COMMENT ON COLUMN audit_log.actor_ip IS 'PII: purge on account erase / retention job';
COMMENT ON COLUMN audit_log.before_state IS 'Redacted diff source — SECRET-classified fields must never appear here (candleviewer.audit.redact)';
COMMENT ON COLUMN audit_log.after_state IS 'Redacted diff source — SECRET-classified fields must never appear here (candleviewer.audit.redact)';

CREATE FUNCTION audit_chain() RETURNS trigger LANGUAGE plpgsql AS $BODY$
DECLARE last_hash sha256_hex;
BEGIN
  SELECT entry_hash INTO last_hash FROM audit_log ORDER BY id DESC LIMIT 1;
  NEW.prev_hash := COALESCE(last_hash, repeat('0',64));
  NEW.entry_hash := encode(digest(
      NEW.prev_hash
      || coalesce(NEW.actor_user_id::text,'') || NEW.actor_label
      || coalesce(NEW.actor_ip::text,'') || coalesce(NEW.session_id::text,'')
      || NEW.action || coalesce(NEW.object_kind,'') || coalesce(NEW.object_id,'')
      || NEW.outcome::text || NEW.severity::text || coalesce(NEW.reason,'')
      || coalesce(NEW.before_state::text,'') || coalesce(NEW.after_state::text,'')
      || coalesce(NEW.request_id::text,'') || coalesce(NEW.env::text,'')
      || to_char(NEW.event_ts AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.USOF'),
    'sha256'), 'hex');
  RETURN NEW;
END $BODY$;

CREATE TRIGGER trg_audit_chain BEFORE INSERT ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_chain();
CREATE TRIGGER trg_audit_append BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- Guarded: `cv_app`/`cv_ro` are cluster roles created by
-- `infra/scripts/pg_bootstrap.sql` (E07-T02), not by this migration. A
-- migration-only test database (this file's own integration test,
-- `tests/integration/auth/test_0001_identity_migration.py`'s testcontainers
-- pattern) has neither role, so an unconditional REVOKE would fail the
-- upgrade everywhere except a fully-bootstrapped cluster; skip when absent
-- rather than silently granting cv_app write access by never revoking it —
-- `pg_bootstrap.sql`'s own defensive REVOKE (Sec. "Audit tables get no
-- UPDATE/DELETE grant") still re-asserts this the moment both exist.
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN
    EXECUTE 'REVOKE UPDATE, DELETE ON audit_log FROM cv_app';
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_ro') THEN
    EXECUTE 'REVOKE UPDATE, DELETE ON audit_log FROM cv_ro';
  END IF;
END
$BODY$;

CREATE TABLE audit_checkpoints (
  id           uuid PRIMARY KEY,
  head_id      bigint NOT NULL,
  head_hash    sha256_hex NOT NULL,
  row_count    bigint NOT NULL,
  signed_by    text NOT NULL DEFAULT 'cv-audit-key-v1',
  signature    bytea,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (head_id)
);
"""

_DOWNGRADE_SQL = """
DROP TABLE IF EXISTS audit_checkpoints;
DROP TRIGGER IF EXISTS trg_audit_append ON audit_log;
DROP TRIGGER IF EXISTS trg_audit_chain ON audit_log;
DROP FUNCTION IF EXISTS audit_chain();
DROP TABLE IF EXISTS audit_log;
DROP FUNCTION IF EXISTS forbid_mutation();
DROP TYPE IF EXISTS severity;
DROP TYPE IF EXISTS audit_outcome;
DROP TYPE IF EXISTS exchange_env;
"""
