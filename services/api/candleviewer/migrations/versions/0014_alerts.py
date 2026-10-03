"""alerts, alert_deliveries and outbox (E40-T01)

Revision ID: 0014_alerts
Revises: 0013_rules
Create Date: 2026-10-04

Purely additive (C-5.1). DDL mirrors `docs/plan/21-database-schema.md`
Sec.3.5 and Sec.3.10.4 (the register's `0009_alerts`; number 0009 was taken,
so it ships as 0014). Documented deviations:

* `exchange_accounts` (E27) does not exist yet, so `alerts.scope_account_id`
  is created WITHOUT its foreign key (same pattern as 0013); E27 adds it.
* `outbox` is not created by any earlier revision; it is created here
  (`IF NOT EXISTS`) exactly as Sec.3.10.4.
* `trg_ad_append` calls `alert_deliveries_forbid_delete()`, a sibling of the
  shared `forbid_mutation()`: DELETE is refused unless `session_user` is
  `cv_owner` (the retention job). UPDATE stays allowed (queued->sent->acked).
* Downgrade refuses (clear error) when `alerts`/`alert_deliveries`/`outbox`
  hold rows, and drops cleanly when empty.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_alerts"
down_revision: str | None = "0013_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_ENUMS_SQL)
    op.execute(_ALERTS_SQL)
    op.execute(_DELIVERIES_SQL)
    op.execute(_OUTBOX_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_ENUMS_SQL = """
CREATE TYPE alert_channel       AS ENUM ('in_app','email','webhook','push','desktop');
CREATE TYPE alert_trigger_mode  AS ENUM ('once','every_time','once_per_bar');
CREATE TYPE delivery_status     AS ENUM ('queued','sent','failed','suppressed','acked');
"""

_ALERTS_SQL = """
CREATE TABLE alerts (
  id             uuid PRIMARY KEY,
  owner_user_id  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name           text NOT NULL,
  symbol         symbol_code,
  scope_account_id uuid,
  condition_ir   jsonb NOT NULL,
  condition_hash sha256_hex NOT NULL,
  enabled        boolean NOT NULL DEFAULT true,
  trigger_mode   alert_trigger_mode NOT NULL DEFAULT 'once',
  cooldown_seconds integer NOT NULL DEFAULT 60,
  snoozed_until  timestamptz,
  expires_at     timestamptz,
  severity       severity NOT NULL DEFAULT 'info',
  channels       alert_channel[] NOT NULL DEFAULT '{in_app}',
  webhook_url_enc bytea,
  webhook_secret_enc bytea,
  message_template text NOT NULL DEFAULT '',
  last_fired_at  timestamptz,
  fire_count     bigint NOT NULL DEFAULT 0,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  CONSTRAINT al_cooldown CHECK (cooldown_seconds BETWEEN 0 AND 86400),
  CONSTRAINT al_channels CHECK (array_length(channels,1) BETWEEN 1 AND 5),
  CONSTRAINT al_webhook  CHECK (NOT ('webhook' = ANY(channels)) OR webhook_url_enc IS NOT NULL)
);
COMMENT ON COLUMN alerts.webhook_url_enc IS 'SECRET: envelope-encrypted; never selected into API DTOs';
COMMENT ON COLUMN alerts.webhook_secret_enc IS 'SECRET: envelope-encrypted HMAC key';
CREATE UNIQUE INDEX ux_alerts_name ON alerts (owner_user_id, lower(name)) WHERE deleted_at IS NULL;
CREATE INDEX ix_alerts_live   ON alerts (symbol) WHERE enabled AND deleted_at IS NULL;
CREATE INDEX ix_alerts_snooze ON alerts (snoozed_until) WHERE snoozed_until IS NOT NULL;
CREATE INDEX ix_alerts_expiry ON alerts (expires_at) WHERE expires_at IS NOT NULL AND deleted_at IS NULL;
"""

_DELIVERIES_SQL = """
CREATE TABLE alert_deliveries (
  id           bigserial PRIMARY KEY,
  alert_id     uuid NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
  user_id      uuid REFERENCES users(id) ON DELETE SET NULL,
  channel      alert_channel NOT NULL,
  status       delivery_status NOT NULL DEFAULT 'queued',
  title        text NOT NULL,
  body         text NOT NULL DEFAULT '',
  context      jsonb NOT NULL DEFAULT '{}'::jsonb,
  attempt      smallint NOT NULL DEFAULT 0,
  http_status  smallint,
  error_message text,
  queued_at    timestamptz NOT NULL DEFAULT now(),
  sent_at      timestamptz,
  acked_at     timestamptz,
  acked_by     uuid REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT ad_attempt CHECK (attempt BETWEEN 0 AND 10)
);
CREATE INDEX ix_ad_alert_time ON alert_deliveries (alert_id, queued_at DESC);
CREATE INDEX ix_ad_pending    ON alert_deliveries (queued_at) WHERE status = 'queued';
CREATE INDEX ix_ad_user_unack ON alert_deliveries (user_id, queued_at DESC)
  WHERE status = 'sent' AND acked_at IS NULL;

CREATE FUNCTION alert_deliveries_forbid_delete() RETURNS trigger LANGUAGE plpgsql AS $BODY$
BEGIN
  IF session_user = 'cv_owner' THEN
    RETURN OLD;  -- retention job only
  END IF;
  RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
END $BODY$;

CREATE TRIGGER trg_ad_append BEFORE DELETE ON alert_deliveries
  FOR EACH ROW EXECUTE FUNCTION alert_deliveries_forbid_delete();
"""

_OUTBOX_SQL = """
CREATE TABLE IF NOT EXISTS outbox (
  id            bigserial PRIMARY KEY,
  topic         text NOT NULL,
  dedup_key     text NOT NULL,
  payload       jsonb NOT NULL,
  available_at  timestamptz NOT NULL DEFAULT now(),
  attempts      smallint NOT NULL DEFAULT 0,
  max_attempts  smallint NOT NULL DEFAULT 8,
  locked_by     text,
  locked_until  timestamptz,
  processed_at  timestamptz,
  dead_at       timestamptz,
  last_error    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ob_attempts CHECK (attempts >= 0 AND attempts <= max_attempts + 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_outbox_dedup ON outbox (topic, dedup_key);
CREATE INDEX IF NOT EXISTS ix_outbox_ready ON outbox (available_at)
  WHERE processed_at IS NULL AND dead_at IS NULL;
"""

_DOWNGRADE_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM alerts) OR EXISTS (SELECT 1 FROM alert_deliveries)
     OR EXISTS (SELECT 1 FROM outbox) THEN
    RAISE EXCEPTION '0014_alerts downgrade refused: alerts/alert_deliveries/outbox hold data';
  END IF;
END $BODY$;
DROP TABLE IF EXISTS outbox;
DROP TRIGGER IF EXISTS trg_ad_append ON alert_deliveries;
DROP TABLE IF EXISTS alert_deliveries;
DROP FUNCTION IF EXISTS alert_deliveries_forbid_delete();
DROP TABLE IF EXISTS alerts;
DROP TYPE IF EXISTS delivery_status;
DROP TYPE IF EXISTS alert_trigger_mode;
DROP TYPE IF EXISTS alert_channel;
"""
