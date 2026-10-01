"""sessions step-up state: per-class elevation, strike count, read-only downgrade (E09-S04)

Revision ID: 0009_sessions_step_up_state
Revises: 0008_system_events
Create Date: 2026-10-01

The E09-S04 brief: "Elevation is stored on the session row keyed by action
class with its own expiry, never in a token claim, so it is revocable and
cannot be replayed on another session." Purely additive (C-5.1): two NOT NULL
columns with constant defaults and one nullable column, so no backfill and
no long lock. Revoking the row (`revoked_at`) ends the elevation with it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_sessions_step_up_state"
down_revision: str | None = "0008_system_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_UPGRADE_SQL = """
ALTER TABLE sessions ADD COLUMN step_up_elevations jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE sessions ADD COLUMN step_up_failures smallint NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN readonly_until timestamptz;
ALTER TABLE sessions ADD CONSTRAINT sessions_step_up_failures_range
  CHECK (step_up_failures BETWEEN 0 AND 3);
COMMENT ON COLUMN sessions.step_up_elevations IS
  'Step-up elevation per action class: {"<action_class>": "<expiry ISO-8601 UTC>"} (E09-S04).';
COMMENT ON COLUMN sessions.step_up_failures IS
  'Consecutive invalid step-up codes; 3 triggers the read-only downgrade (E09-S04).';
COMMENT ON COLUMN sessions.readonly_until IS
  'Read-only downgrade expiry after 3 failed step-up codes (E09-S04); NULL = writable.';
"""

_DOWNGRADE_SQL = """
ALTER TABLE sessions DROP CONSTRAINT sessions_step_up_failures_range;
ALTER TABLE sessions DROP COLUMN readonly_until;
ALTER TABLE sessions DROP COLUMN step_up_failures;
ALTER TABLE sessions DROP COLUMN step_up_elevations;
"""
