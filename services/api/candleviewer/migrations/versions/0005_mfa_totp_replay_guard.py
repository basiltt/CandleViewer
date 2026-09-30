"""mfa_methods.last_accepted_time_step: TOTP replay guard (E09-S02)

Revision ID: 0005_mfa_totp_replay_guard
Revises: 0004_instruments
Create Date: 2026-09-30

`0001_identity_rbac_sessions_mfa.py` shipped `mfa_methods` without a column
to remember the last accepted TOTP time-step per method, so there was no way
to reject a replayed code within the same (or an earlier) step window — the
ticket's "Reused code is rejected" acceptance criterion needs a persisted
high-water mark that `MfaRepository.record_time_step()` compare-and-sets
atomically (see `candleviewer/auth/mfa_repository.py`'s docstring). Purely
additive (C-5.1): one nullable `bigint` column, no backfill needed since
existing rows have never accepted a code.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_mfa_totp_replay_guard"
down_revision: str | None = "0004_instruments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_UPGRADE_SQL = """
ALTER TABLE mfa_methods ADD COLUMN last_accepted_time_step bigint;
COMMENT ON COLUMN mfa_methods.last_accepted_time_step IS
  'Highest RFC 6238 time-step accepted so far for this method; a step <= this
   value is a replay and must be rejected (ticket E09-S02 "Reused code is
   rejected"). NULL means no code has ever been accepted.';
"""

_DOWNGRADE_SQL = """
ALTER TABLE mfa_methods DROP COLUMN last_accepted_time_step;
"""
