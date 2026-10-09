"""Align the `audit:read` role grants with 04-security-program.md §7.2.1 (#2083)

Revision ID: 0016_audit_read_grants
Revises: 0015_rules_arm_live_permission

`docs/plan/04-security-program.md` §7.2.1/§7.2.2 rows 49/49a and SR-067 are the
authoritative contract for `audit:read`: Owner (raw), Manager (own events,
redacted at request time by `candleviewer.audit.access`), Viewer none. The 0001
seed assigned the permission to `viewer` instead of `manager`; this fix-forward
revision moves the grant (C-5.4: 0001 is immutable). Data-only, idempotent.

Downgrade restores the 0001 grants exactly.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016_audit_read_grants"
down_revision: str | None = "0015_rules_arm_live_permission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_REVOKE_VIEWER)
    op.execute(_GRANT.format(role="manager"))


def downgrade() -> None:
    op.execute(_REVOKE.format(role="manager"))
    op.execute(_GRANT.format(role="viewer"))


_GRANT = """
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = '{role}' AND p.code = 'audit:read'
ON CONFLICT DO NOTHING;
"""

_REVOKE = """
DELETE FROM role_permissions
WHERE role_id IN (SELECT id FROM roles WHERE name = '{role}')
  AND permission_id IN (SELECT id FROM permissions WHERE code = 'audit:read');
"""

_REVOKE_VIEWER = _REVOKE.format(role="viewer")
