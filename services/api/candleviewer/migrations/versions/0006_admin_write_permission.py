"""Seed the `admin:write` permission and grant it to `owner` (fix-forward)

Revision ID: 0006_admin_write_permission
Revises: 0005_mfa_totp_replay_guard
Create Date: 2026-10-01

PR #1637 added `x-rbac: admin:write` to `setLogLevelOverride` in
`docs/plan/22-api-openapi.yaml`, so `tools/rbac/generate.py` now emits 37
permission codes into `candleviewer/auth/rbac_seed.json`. The database
vocabulary is seeded by `0001_identity_rbac_sessions_mfa.py`, which is
immutable (C-5.4) and inserts only the original 36 codes. This revision fixes
forward: purely additive data (C-5.1), one permission row plus the `owner`
grant (0001 grants every permission to `owner`; `manager`/`viewer` do not hold
it per the seed). `ON CONFLICT DO NOTHING` keeps it a no-op on databases where
`db/seed.py` already upserted the code.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_admin_write_permission"
down_revision: str | None = "0005_mfa_totp_replay_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_UPGRADE_SQL = """
INSERT INTO permissions (id, code, domain, description, is_dangerous)
VALUES (gen_random_uuid(), 'admin:write', 'admin', '', false)
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = 'owner' AND p.code = 'admin:write'
ON CONFLICT DO NOTHING;
"""

_DOWNGRADE_SQL = """
DELETE FROM role_permissions
WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'admin:write');

DELETE FROM permissions WHERE code = 'admin:write';
"""
