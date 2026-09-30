"""sessions.idle_timeout_s: per-session idle-lock timeout (E09-S03)

Revision ID: 0006_sessions_idle_timeout
Revises: 0005_mfa_totp_replay_guard
Create Date: 2026-10-01

`SessionRecord.idle_timeout_s` (5-60 min, default 15 per the E09-S03 ticket)
had no column: `0001` shipped `sessions` without it, so the idle deadline
could not survive a restart. Purely additive (C-5.1): one NOT NULL column
with a constant default and a range CHECK, so no backfill or long lock.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_sessions_idle_timeout"
down_revision: str | None = "0005_mfa_totp_replay_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_UPGRADE_SQL = """
ALTER TABLE sessions ADD COLUMN idle_timeout_s integer NOT NULL DEFAULT 900;
ALTER TABLE sessions ADD CONSTRAINT sessions_idle_timeout_range
  CHECK (idle_timeout_s BETWEEN 300 AND 3600);
COMMENT ON COLUMN sessions.idle_timeout_s IS
  'Per-session idle-lock timeout in seconds (5-60 min, default 15); the idle deadline is last_seen_at + this.';
"""

_DOWNGRADE_SQL = """
ALTER TABLE sessions DROP CONSTRAINT sessions_idle_timeout_range;
ALTER TABLE sessions DROP COLUMN idle_timeout_s;
"""
