"""onboarding_dismissals: per-user checklist dismissal flag (E09-S06)

Revision ID: 0012_onboarding_dismissals
Revises: 0011_recorder
Create Date: 2026-10-02

Purely additive (C-5.1). Server-side so a dismissed checklist stays gone on
every device; one row per user, no secrets or PII.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_onboarding_dismissals"
down_revision: str | None = "0011_recorder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_UPGRADE_SQL = """
CREATE TABLE onboarding_dismissals (
  user_id      uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  dismissed_at timestamptz NOT NULL DEFAULT now()
);
"""

_DOWNGRADE_SQL = """
DROP TABLE onboarding_dismissals;
"""
