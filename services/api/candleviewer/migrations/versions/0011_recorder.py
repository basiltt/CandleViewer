"""recorder: recorded_symbols, recording_sessions, recording_gaps, retention_policies (E16-T01)

Revision ID: 0011_recorder
Revises: 0010_user_invites
Create Date: 2026-10-02

Purely additive (C-5.1). DDL mirrors `docs/plan/21-database-schema.md`
Sec.3.6.1-3.6.3. The ticket calls this `0007_recorder`; 0007-0010 were taken
by earlier tickets, so the next free number is used (single linear history).
`stream_kind` had no earlier owner, so it is created here with the other
recorder enums.

Seeds one `scope='default'` retention row per `stream_kind` from the Sec.7
matrix. `engine_metrics` (the only `drop` row) is not a `stream_kind`, so no
seed row exists for it.

Grants: DELETE/TRUNCATE is revoked from `cv_app`/`cv_ro` on
`recording_sessions` and `recording_gaps` - deleting gap metadata would hide
a gap (ADR-0015 Sec.7). Guarded because the roles are created by
`infra/scripts/pg_bootstrap.sql`, not by migrations.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_recorder"
down_revision: str | None = "0010_user_invites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_ENUMS_SQL)
    op.execute(_TABLES_SQL)
    op.execute(_SEED_SQL)
    op.execute(_GRANTS_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_ENUM_GUARD = "CREATE TYPE {n} AS ENUM ({v});" + chr(10)

# Static literals only (no caller data); `.format` just avoids repeating the guard.
_ENUMS_SQL = "".join(
    _ENUM_GUARD.format(n=n, v=v)
    for n, v in (
        (
            "stream_kind",
            "'trades','orderbook_delta','orderbook_snapshot','tickers','klines',"
            "'liquidations','open_interest','funding'",
        ),
        (
            "record_reason",
            "'manual','chart_open','position_open','rule_dependency','alert_dependency'",
        ),
        (
            "recording_state",
            "'idle','starting','recording','degraded','stopping','stopped','error'",
        ),
        ("retention_action", "'drop','archive_parquet','downsample','pin'"),
    )
)

_TABLES_SQL = """
CREATE TABLE recorded_symbols (
  id                uuid PRIMARY KEY,
  symbol            symbol_code NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
  env               exchange_env NOT NULL DEFAULT 'live',
  reason            record_reason NOT NULL DEFAULT 'manual',
  reason_refs       jsonb NOT NULL DEFAULT '[]'::jsonb,
  streams           stream_kind[] NOT NULL DEFAULT '{trades,orderbook_delta,tickers,liquidations}',
  orderbook_depth   smallint NOT NULL DEFAULT 200,
  pinned            boolean NOT NULL DEFAULT false,
  retention_days    integer,
  priority          smallint NOT NULL DEFAULT 100,
  added_by          uuid REFERENCES users(id) ON DELETE SET NULL,
  auto_added_at     timestamptz,
  first_recorded_at timestamptz,
  last_recorded_at  timestamptz,
  bytes_estimate    bigint NOT NULL DEFAULT 0,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  removed_at        timestamptz,
  CONSTRAINT rs_depth     CHECK (orderbook_depth IN (1,50,200,500)),
  CONSTRAINT rs_retention CHECK (retention_days IS NULL OR retention_days BETWEEN 1 AND 3650),
  CONSTRAINT rs_streams   CHECK (array_length(streams,1) >= 1),
  CONSTRAINT rs_autoshape CHECK (reason = 'manual' OR auto_added_at IS NOT NULL)
);
CREATE UNIQUE INDEX ux_rs_symbol ON recorded_symbols (symbol, env) WHERE removed_at IS NULL;
CREATE INDEX ix_rs_pinned ON recorded_symbols (symbol) WHERE pinned AND removed_at IS NULL;
CREATE INDEX ix_rs_auto ON recorded_symbols (reason)
  WHERE removed_at IS NULL AND reason <> 'manual';

CREATE TABLE recording_sessions (
  id                  uuid PRIMARY KEY,
  recorded_symbol_id  uuid NOT NULL REFERENCES recorded_symbols(id) ON DELETE CASCADE,
  symbol              symbol_code NOT NULL,
  state               recording_state NOT NULL DEFAULT 'starting',
  streams             stream_kind[] NOT NULL,
  orderbook_depth     smallint NOT NULL,
  ws_endpoint         text NOT NULL,
  started_at          timestamptz NOT NULL DEFAULT now(),
  ended_at            timestamptz,
  first_event_ts      timestamptz,
  last_event_ts       timestamptz,
  messages_received   bigint NOT NULL DEFAULT 0,
  messages_dropped    bigint NOT NULL DEFAULT 0,
  bytes_written       bigint NOT NULL DEFAULT 0,
  reconnect_count     integer NOT NULL DEFAULT 0,
  snapshot_count      integer NOT NULL DEFAULT 0,
  degraded_seconds    integer NOT NULL DEFAULT 0,
  end_reason          text,
  error_message       text,
  CONSTRAINT recs_counts CHECK (messages_received >= 0 AND messages_dropped >= 0),
  CONSTRAINT recs_window CHECK (ended_at IS NULL OR ended_at >= started_at)
);
CREATE INDEX ix_recs_symbol_time ON recording_sessions (symbol, started_at DESC);
CREATE INDEX ix_recs_live ON recording_sessions (symbol)
  WHERE state IN ('starting','recording','degraded');

CREATE TABLE recording_gaps (
  id                   bigserial PRIMARY KEY,
  recording_session_id uuid NOT NULL REFERENCES recording_sessions(id) ON DELETE CASCADE,
  symbol               symbol_code NOT NULL,
  stream               stream_kind NOT NULL,
  gap_start            timestamptz NOT NULL,
  gap_end              timestamptz NOT NULL,
  cause                text NOT NULL,
  backfilled           boolean NOT NULL DEFAULT false,
  backfill_source      text,
  CONSTRAINT rg_window CHECK (gap_end > gap_start),
  CONSTRAINT rg_cause  CHECK (cause IN
    ('ws_disconnect','backpressure_drop','process_restart','seq_jump','exchange_outage'))
);
CREATE INDEX ix_rg_symbol_time ON recording_gaps (symbol, gap_start DESC);

CREATE TABLE retention_policies (
  id             uuid PRIMARY KEY,
  scope          text NOT NULL,
  symbol         symbol_code,
  stream         stream_kind NOT NULL,
  retain_days    integer NOT NULL DEFAULT 30,
  action         retention_action NOT NULL DEFAULT 'archive_parquet',
  downsample_to  text,
  archive_path   text,
  max_disk_gb    integer,
  enabled        boolean NOT NULL DEFAULT true,
  last_run_at    timestamptz,
  last_run_deleted_rows bigint NOT NULL DEFAULT 0,
  created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT rp_scope     CHECK (scope IN ('default','symbol')),
  CONSTRAINT rp_symshape  CHECK ((scope = 'symbol') = (symbol IS NOT NULL)),
  CONSTRAINT rp_days      CHECK (retain_days BETWEEN 1 AND 3650),
  CONSTRAINT rp_downshape CHECK (action <> 'downsample' OR downsample_to IS NOT NULL),
  CONSTRAINT rp_disk      CHECK (max_disk_gb IS NULL OR max_disk_gb > 0)
);
CREATE UNIQUE INDEX ux_rp_default ON retention_policies (stream) WHERE scope = 'default';
CREATE UNIQUE INDEX ux_rp_symbol  ON retention_policies (symbol, stream) WHERE scope = 'symbol';
"""

# 21-database-schema.md Sec.7 hot-tier horizons, one row per stream_kind.
_SEED_SQL = """
INSERT INTO retention_policies (id, scope, stream, retain_days, action)
SELECT gen_random_uuid(), 'default', v.stream::stream_kind, v.days, 'archive_parquet'
FROM (VALUES
  ('trades', 30), ('orderbook_delta', 7), ('orderbook_snapshot', 30), ('tickers', 30),
  ('klines', 90), ('liquidations', 90), ('open_interest', 90), ('funding', 365)
) AS v(stream, days);
"""

_GRANTS_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN
    EXECUTE 'REVOKE DELETE, TRUNCATE ON recording_sessions FROM cv_app';
    EXECUTE 'REVOKE DELETE, TRUNCATE ON recording_gaps FROM cv_app';
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_ro') THEN
    EXECUTE 'REVOKE DELETE, TRUNCATE ON recording_sessions FROM cv_ro';
    EXECUTE 'REVOKE DELETE, TRUNCATE ON recording_gaps FROM cv_ro';
  END IF;
END
$BODY$;
"""

_DOWNGRADE_SQL = """
DROP TABLE IF EXISTS retention_policies;
DROP TABLE IF EXISTS recording_gaps;
DROP TABLE IF EXISTS recording_sessions;
DROP TABLE IF EXISTS recorded_symbols;
DROP TYPE IF EXISTS retention_action;
DROP TYPE IF EXISTS recording_state;
DROP TYPE IF EXISTS record_reason;
DROP TYPE IF EXISTS stream_kind;
"""
