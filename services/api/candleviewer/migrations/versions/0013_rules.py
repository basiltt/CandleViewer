"""rules: rules, rule_versions, rule_runs, rule_events with retention guard (E35-T02)

Revision ID: 0013_rules
Revises: 0012_onboarding_dismissals
Create Date: 2026-10-04

Purely additive (C-5.1). DDL mirrors `docs/plan/21-database-schema.md`
Sec.3.4.1-3.4.3 verbatim, with two documented gaps:

* `exchange_accounts` (E27) and `trade_groups` (E34) do not exist yet, so
  `rules.scope_account_id`, `rule_runs.scope_account_id` and
  `rule_runs.trade_group_id` are created WITHOUT their foreign keys (same
  pattern as 0001's `user_account_access`); the owning tickets add
  `ALTER TABLE ... ADD CONSTRAINT` in their own revisions. No `depends_on`
  is possible for tables that are not in any revision yet.
* `trg_re_append` calls `rule_events_forbid_mutation()` (a sibling of the
  shared `forbid_mutation()`): UPDATE is always refused for every role. A
  DELETE is refused unless it is the FK cascade of an already-deleted parent
  `rule_runs` row (parent no longer visible), so a direct
  `DELETE FROM rule_events` fails for every role including the table owner
  and the app role: there is no GUC or role bypass. Parent deletion is itself
  guarded by `trg_rr_evidence` (matched/error runs younger than 24 months
  cannot be deleted), so only the retention prune of unmatched noise, or a
  rule delete whose runs are all unmatched, cascades to events.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_rules"
down_revision: str | None = "0012_onboarding_dismissals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_ENUMS_SQL)
    op.execute(_RULES_SQL)
    op.execute(_VERSIONS_SQL)
    op.execute(_RUNS_SQL)
    op.execute(_EVENTS_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_ENUMS_SQL = """
CREATE TYPE rule_scope AS ENUM ('global','account','symbol','position','trade_group');
CREATE TYPE rule_mode AS ENUM ('disabled','simulate','armed');
CREATE TYPE rule_run_status AS ENUM ('running','ok','error','aborted','throttled');
"""

_RULES_SQL = """
CREATE TABLE rules (
  id                 uuid PRIMARY KEY,
  name               text NOT NULL,
  description        text NOT NULL DEFAULT '',
  owner_user_id      uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  scope              rule_scope NOT NULL DEFAULT 'global',
  scope_account_id   uuid,
  scope_symbol       symbol_code,
  mode               rule_mode NOT NULL DEFAULT 'disabled',
  active_version_id  uuid,
  editor             text NOT NULL DEFAULT 'form',
  priority           smallint NOT NULL DEFAULT 100,
  eval_interval_ms   integer NOT NULL DEFAULT 250,
  cooldown_seconds   integer NOT NULL DEFAULT 0,
  max_fires_per_day  integer,
  max_fires_per_hour integer,
  requires_confirmation boolean NOT NULL DEFAULT false,
  armed_at           timestamptz,
  armed_by           uuid REFERENCES users(id) ON DELETE SET NULL,
  disabled_reason    text,
  last_fired_at      timestamptz,
  fire_count         bigint NOT NULL DEFAULT 0,
  error_count        bigint NOT NULL DEFAULT 0,
  created_by         uuid REFERENCES users(id) ON DELETE SET NULL,
  updated_by         uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  deleted_at         timestamptz,
  CONSTRAINT rule_editor    CHECK (editor IN ('form','graph')),
  CONSTRAINT rule_interval  CHECK (eval_interval_ms BETWEEN 50 AND 3600000),
  CONSTRAINT rule_cooldown  CHECK (cooldown_seconds BETWEEN 0 AND 86400),
  CONSTRAINT rule_prio      CHECK (priority BETWEEN 0 AND 1000),
  CONSTRAINT rule_scope_acct CHECK (scope <> 'account' OR scope_account_id IS NOT NULL),
  CONSTRAINT rule_scope_sym  CHECK (scope <> 'symbol'  OR scope_symbol IS NOT NULL),
  CONSTRAINT rule_armed_shape CHECK (mode <> 'armed'
    OR (armed_at IS NOT NULL AND armed_by IS NOT NULL AND active_version_id IS NOT NULL)),
  CONSTRAINT rule_fires_pos  CHECK ((max_fires_per_day IS NULL OR max_fires_per_day > 0)
                                AND (max_fires_per_hour IS NULL OR max_fires_per_hour > 0))
);
CREATE UNIQUE INDEX ux_rules_name ON rules (owner_user_id, lower(name)) WHERE deleted_at IS NULL;
CREATE INDEX ix_rules_active   ON rules (mode, priority)
  WHERE mode <> 'disabled' AND deleted_at IS NULL;
CREATE INDEX ix_rules_symbol   ON rules (scope_symbol) WHERE scope_symbol IS NOT NULL;
CREATE INDEX ix_rules_account  ON rules (scope_account_id) WHERE scope_account_id IS NOT NULL;
"""

_VERSIONS_SQL = """
CREATE TABLE rule_versions (
  id             uuid PRIMARY KEY,
  rule_id        uuid NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
  version        integer NOT NULL,
  ir             jsonb NOT NULL,
  ir_hash        sha256_hex NOT NULL,
  graph_layout   jsonb,
  form_model     jsonb,
  compiler_version text NOT NULL,
  notes          text NOT NULL DEFAULT '',
  is_valid       boolean NOT NULL DEFAULT false,
  validation_errors jsonb,
  backtest_summary jsonb,
  created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (rule_id, version),
  UNIQUE (rule_id, ir_hash),
  CONSTRAINT rv_version_pos CHECK (version >= 1),
  CONSTRAINT rv_ir_obj      CHECK (jsonb_typeof(ir) = 'object' AND ir ? 'conditions' AND ir ? 'actions')
);
CREATE INDEX ix_rv_rule ON rule_versions (rule_id, version DESC);
ALTER TABLE rules ADD CONSTRAINT rules_active_version_fk
  FOREIGN KEY (active_version_id) REFERENCES rule_versions(id) ON DELETE RESTRICT;
"""

_RUNS_SQL = """
CREATE TABLE rule_runs (
  id               uuid PRIMARY KEY,
  rule_id          uuid NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
  rule_version_id  uuid NOT NULL REFERENCES rule_versions(id) ON DELETE RESTRICT,
  status           rule_run_status NOT NULL DEFAULT 'running',
  mode             rule_mode NOT NULL,
  trigger_reason   text NOT NULL,
  scope_account_id uuid,
  scope_symbol     symbol_code,
  input_snapshot   jsonb NOT NULL,
  matched          boolean NOT NULL DEFAULT false,
  actions_planned  jsonb,
  actions_executed jsonb,
  trade_group_id   uuid,
  error_code       text,
  error_message    text,
  duration_ms      integer,
  started_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz,
  CONSTRAINT rr_trigger  CHECK (trigger_reason IN
    ('tick','bar_close','fill','manual','schedule','position_change','alert')),
  CONSTRAINT rr_duration CHECK (duration_ms IS NULL OR duration_ms >= 0)
);
COMMENT ON COLUMN rule_runs.input_snapshot IS
  'financial/confidential: may hold equity, PnL and position size; never log at INFO';
CREATE INDEX ix_rr_rule_time ON rule_runs (rule_id, started_at DESC);
CREATE INDEX ix_rr_matched   ON rule_runs (rule_id, started_at DESC) WHERE matched;
CREATE INDEX ix_rr_errors    ON rule_runs (started_at DESC) WHERE status = 'error';
CREATE INDEX ix_rr_group     ON rule_runs (trade_group_id) WHERE trade_group_id IS NOT NULL;
"""

_EVENTS_SQL = """
CREATE TABLE rule_events (
  id           bigserial PRIMARY KEY,
  rule_run_id  uuid NOT NULL REFERENCES rule_runs(id) ON DELETE CASCADE,
  seq          integer NOT NULL,
  kind         text NOT NULL,
  node_ref     text,
  payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
  severity     severity NOT NULL DEFAULT 'info',
  event_ts     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (rule_run_id, seq),
  CONSTRAINT re_kind CHECK (kind IN
    ('condition_eval','action_start','action_ok','action_fail','throttled','log'))
);
CREATE INDEX ix_re_run  ON rule_events (rule_run_id, seq);
CREATE INDEX ix_re_time ON rule_events (event_ts DESC);

CREATE FUNCTION rule_events_forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $BODY$
BEGIN
  IF TG_OP = 'DELETE'
     AND NOT EXISTS (SELECT 1 FROM rule_runs WHERE id = OLD.rule_run_id) THEN
    RETURN OLD;  -- FK cascade from a deleted (guarded) parent run only
  END IF;
  RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
END $BODY$;

CREATE FUNCTION rule_runs_guard_evidence() RETURNS trigger LANGUAGE plpgsql AS $BODY$
BEGIN
  IF (OLD.matched OR OLD.status = 'error')
     AND OLD.started_at > now() - interval '24 months' THEN
    RAISE EXCEPTION 'table % evidence is append-only within retention', TG_TABLE_NAME;
  END IF;
  RETURN OLD;
END $BODY$;

CREATE TRIGGER trg_rr_evidence BEFORE DELETE ON rule_runs
  FOR EACH ROW EXECUTE FUNCTION rule_runs_guard_evidence();

CREATE TRIGGER trg_re_append BEFORE UPDATE OR DELETE ON rule_events
  FOR EACH ROW EXECUTE FUNCTION rule_events_forbid_mutation();
"""

_DOWNGRADE_SQL = """
DROP TABLE IF EXISTS rule_events;
DROP FUNCTION IF EXISTS rule_events_forbid_mutation();
DROP TABLE IF EXISTS rule_runs;
DROP FUNCTION IF EXISTS rule_runs_guard_evidence();
ALTER TABLE rules DROP CONSTRAINT IF EXISTS rules_active_version_fk;
DROP TABLE IF EXISTS rule_versions;
DROP TABLE IF EXISTS rules;
DROP TYPE IF EXISTS rule_run_status;
DROP TYPE IF EXISTS rule_mode;
DROP TYPE IF EXISTS rule_scope;
"""
