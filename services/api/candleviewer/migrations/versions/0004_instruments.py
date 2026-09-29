"""instrument catalogue: instruments + instrument_versions (E08-S01)

Revision ID: 0004_instruments
Revises: 0003_audit_log
Create Date: 2026-09-29

Creates, per `docs/plan/21-database-schema.md` Sec.3.3.9, the `instruments`
table (current-snapshot cache, one row per symbol) plus `instrument_versions`
(append-only history: a new row is written whenever a refresh detects a
metadata change, per ticket body "Tick size changes" scenario). The domain
`symbol_code` and enum `exchange_code` are shared, reviewed shapes
(`21-database-schema.md` Sec.1.2/1.3); this revision creates them since
`0001_identity_rbac_sessions_mfa.py` scoped only `sha256_hex`/`user_status`/
`role_name`/`mfa_method_kind` (out of scope note there: `exchange_accounts`/
`api_keys`/instruments were left to their owning epics).

Out of scope (ticket body): risk-limit tiers (E29's `fetch_risk_limits`
result is not persisted here — `InstrumentDetail.risk_limit_tiers` is served
live from the exchange adapter, not cached in Postgres, until E29 needs to).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_instruments"
down_revision: str | None = "0003_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_UPGRADE_SQL = """
-- nosemgrep: cv-adapter-isolation -- schema-level value domain (C-1.3 scopes
-- the whole product to Bybit only); not adapter logic.
CREATE TYPE exchange_code AS ENUM ('bybit'); -- nosemgrep: cv-adapter-isolation

CREATE DOMAIN symbol_code AS text CHECK (VALUE ~ '^[A-Z0-9]{4,20}$');

CREATE TABLE instruments (
  symbol               symbol_code PRIMARY KEY,
  exchange             exchange_code NOT NULL DEFAULT 'bybit', -- nosemgrep: cv-adapter-isolation
  category             text NOT NULL DEFAULT 'linear',
  base_coin            text NOT NULL,
  quote_coin           text NOT NULL DEFAULT 'USDT',
  settle_coin          text NOT NULL DEFAULT 'USDT',
  status               text NOT NULL,
  tick_size            numeric(38,18) NOT NULL,
  qty_step             numeric(38,18) NOT NULL,
  min_order_qty        numeric(38,18) NOT NULL,
  max_order_qty        numeric(38,18) NOT NULL,
  min_notional_value   numeric(38,18),
  max_leverage         numeric(10,2) NOT NULL,
  leverage_step        numeric(10,2) NOT NULL DEFAULT 0.01,
  price_scale          smallint NOT NULL DEFAULT 2,
  funding_interval_min integer NOT NULL DEFAULT 480,
  launch_ts            timestamptz,
  delivery_ts          timestamptz,
  metadata_version     integer NOT NULL DEFAULT 1,
  raw                  jsonb NOT NULL,
  refreshed_at         timestamptz NOT NULL DEFAULT now(),
  stale_since          timestamptz,
  CONSTRAINT inst_cat     CHECK (category = 'linear'),
  CONSTRAINT inst_quote   CHECK (quote_coin = 'USDT'),
  CONSTRAINT inst_ticks   CHECK (tick_size > 0 AND qty_step > 0),
  CONSTRAINT inst_qty_rng CHECK (max_order_qty >= min_order_qty),
  CONSTRAINT inst_version CHECK (metadata_version >= 1)
);
CREATE INDEX ix_instruments_status ON instruments (status);
COMMENT ON COLUMN instruments.raw IS
  'Full, unredacted instruments-info payload for this symbol, for audit and forward-compat fields.';

CREATE TABLE instrument_versions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol           symbol_code NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
  metadata_version integer NOT NULL,
  tick_size        numeric(38,18) NOT NULL,
  qty_step         numeric(38,18) NOT NULL,
  min_order_qty    numeric(38,18) NOT NULL,
  max_order_qty    numeric(38,18) NOT NULL,
  min_notional_value numeric(38,18),
  max_leverage     numeric(10,2) NOT NULL,
  leverage_step    numeric(10,2) NOT NULL,
  price_scale      smallint NOT NULL,
  funding_interval_min integer NOT NULL,
  status           text NOT NULL,
  changed_fields   text[] NOT NULL DEFAULT '{}',
  raw              jsonb NOT NULL,
  recorded_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT iv_version CHECK (metadata_version >= 1),
  CONSTRAINT iv_unique_version UNIQUE (symbol, metadata_version)
);
CREATE INDEX ix_instrument_versions_symbol ON instrument_versions (symbol, metadata_version DESC);
COMMENT ON COLUMN instrument_versions.changed_fields IS
  'Field names that differed from the immediately preceding version, for InstrumentUpdatedEvent.changed_fields.';
"""

_DOWNGRADE_SQL = """
DROP TABLE IF EXISTS instrument_versions;
DROP TABLE IF EXISTS instruments;

DROP DOMAIN IF EXISTS symbol_code;

DROP TYPE IF EXISTS exchange_code;
"""
