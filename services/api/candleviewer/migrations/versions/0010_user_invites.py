"""user_invites: single-use, hash-at-rest invite tokens (E09-S05)

Revision ID: 0010_user_invites
Revises: 0009_sessions_step_up_state
Create Date: 2026-10-02

Purely additive (C-5.1): one new table. Only the sha256 hex of the 256-bit
token is stored, so a database leak yields no usable link. `consumed_at` is
set by a conditional UPDATE (single-use under concurrency); `role` is bound
at creation and is the only source of the redeemed role.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_user_invites"
down_revision: str | None = "0009_sessions_step_up_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_UPGRADE_SQL = """
CREATE TABLE user_invites (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role        role_name NOT NULL,
  token_hash  text NOT NULL,
  invited_by  uuid REFERENCES users(id) ON DELETE SET NULL,
  expires_at  timestamptz NOT NULL,
  consumed_at timestamptz,
  pending_password_hash text,
  revoked_at  timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT user_invites_hash_fmt CHECK (char_length(token_hash) = 64),
  CONSTRAINT user_invites_expiry CHECK (expires_at > created_at)
);
CREATE UNIQUE INDEX ux_user_invites_token_hash ON user_invites (token_hash);
CREATE INDEX ix_user_invites_user ON user_invites (user_id);
COMMENT ON COLUMN user_invites.pending_password_hash IS
  'SECRET: Argon2id digest held until TOTP enrolment completes; moved to users.password_hash on activation (E09-S05).';
COMMENT ON COLUMN user_invites.token_hash IS
  'SECRET-DERIVED: sha256 hex of the one-time invite token; the raw token is never stored (E09-S05).';
"""

_DOWNGRADE_SQL = """
DROP TABLE user_invites;
"""
