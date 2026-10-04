"""Seed the `rules:arm_live` dangerous permission and grant it to `owner` (E35-S01)

Revision ID: 0014_rules_arm_live_permission
Revises: 0013_rules

`PUT /rules/{id}/mode` (setRuleMode) now declares `rules:arm_live` in `x-rbac`
(docs/plan/22-api-openapi.yaml); arming a rule against the live environment needs
it plus a fresh step-up (21-database-schema.md 3.4.1). Purely additive data (C-5.1):
one `is_dangerous` permission row and the `owner` grant; managers do not hold it
(live arming is owner-only, schema doc 3.4 note). `ON CONFLICT DO NOTHING` keeps it a
no-op where `db/seed.py` already upserted the code.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_rules_arm_live_permission"
down_revision: str | None = "0013_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_UPGRADE_SQL = """
INSERT INTO permissions (id, code, domain, description, is_dangerous)
VALUES (gen_random_uuid(), 'rules:arm_live', 'rules', '', true)
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = 'owner' AND p.code = 'rules:arm_live'
ON CONFLICT DO NOTHING;
"""

_DOWNGRADE_SQL = """
DELETE FROM role_permissions
WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'rules:arm_live');

DELETE FROM permissions WHERE code = 'rules:arm_live';
"""
