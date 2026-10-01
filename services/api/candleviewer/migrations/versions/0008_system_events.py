"""system_events: operational/health event rows (E04-T04)

Revision ID: 0008_system_events
Revises: 0007_sessions_idle_timeout
Create Date: 2026-10-01

Creates `system_events` per `docs/plan/21-database-schema.md` section 3.10.2.
Additive (C-5.1). `exchange_account_id` has no FK yet: `exchange_accounts` is
created by E27, which adds the constraint (same pattern as migration 0001).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_system_events"
down_revision: str | None = "0007_sessions_idle_timeout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_SQL = """
CREATE TABLE system_events (
  id            bigserial PRIMARY KEY,
  component     text NOT NULL,
  kind          text NOT NULL,
  severity      severity NOT NULL DEFAULT 'info',
  symbol        symbol_code,
  exchange_account_id uuid,
  message       text NOT NULL,
  details       jsonb NOT NULL DEFAULT '{}'::jsonb,
  ret_code      text,
  correlation_id uuid,
  resolved_at   timestamptz,
  resolved_by   uuid REFERENCES users(id) ON DELETE SET NULL,
  event_ts      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT se_component CHECK (component IN ('ingestion','book_engine','bars','orderflow','oms','rules','recorder','replay','api','ws','db','exchange','auth','backup'))
);
CREATE INDEX ix_se_time      ON system_events (event_ts DESC);
CREATE INDEX ix_se_sev_open  ON system_events (severity, event_ts DESC) WHERE resolved_at IS NULL;
CREATE INDEX ix_se_component ON system_events (component, event_ts DESC);
CREATE INDEX ix_se_symbol    ON system_events (symbol, event_ts DESC) WHERE symbol IS NOT NULL;
"""

_DOWNGRADE_SQL = "DROP TABLE IF EXISTS system_events;"


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
