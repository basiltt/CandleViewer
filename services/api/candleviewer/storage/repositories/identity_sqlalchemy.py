"""SQL identity read path for `/auth/session` and `/auth/mfa/verify` (QA #1658).

Implements the `IdentityProvider` shape `api/sessions.py` expects: the
OpenAPI `User` object plus `SessionInfo.permissions`/`account_scope`, read
from the E09-T01 tables (`users`, `user_roles`, `roles`, `role_permissions`,
`permissions`, `user_account_access`). Static, parameterised SQL only.
Never selects `password_hash` or any SECRET-classified column.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_USER_SQL = sa.text("""
    SELECT u.id::text AS id, u.username::text AS username, u.email::text AS email,
           u.display_name, u.status::text AS status, u.mfa_required,
           u.last_login_at, u.created_at, u.updated_at,
           COALESCE((SELECT array_agg(DISTINCT r.name::text ORDER BY r.name::text)
                     FROM user_roles ur JOIN roles r ON r.id = ur.role_id
                     WHERE ur.user_id = u.id
                       AND (ur.expires_at IS NULL OR ur.expires_at > now())),
                    ARRAY[]::text[]) AS roles,
           EXISTS (SELECT 1 FROM mfa_methods m WHERE m.user_id = u.id
                   AND m.confirmed_at IS NOT NULL AND m.revoked_at IS NULL) AS mfa_enabled
    FROM users u
    WHERE u.id = CAST(:id AS uuid) AND u.deleted_at IS NULL
    """)
_PERMS_SQL = sa.text("""
    SELECT DISTINCT p.code FROM users u
    JOIN user_roles ur ON ur.user_id = u.id AND (ur.expires_at IS NULL OR ur.expires_at > now())
    JOIN role_permissions rp ON rp.role_id = ur.role_id
    JOIN permissions p ON p.id = rp.permission_id
    WHERE u.id = CAST(:id AS uuid) ORDER BY p.code
    """)
_SCOPE_SQL = sa.text(
    "SELECT exchange_account_id::text FROM user_account_access "
    "WHERE user_id = CAST(:id AS uuid) AND can_view ORDER BY 1"
)


def _iso(value: Any) -> str | None:
    return None if value is None else str(value.isoformat())


class SqlAlchemyIdentityProvider:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def user(self, user_id: str) -> dict[str, Any]:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_USER_SQL, {"id": user_id})).first()
        if row is None:
            raise LookupError("unknown user")
        m = row._mapping
        return {
            "id": m["id"],
            "username": m["username"],
            "email": m["email"],
            "display_name": m["display_name"],
            "roles": list(m["roles"] or ()),
            "status": m["status"],
            "mfa_enabled": bool(m["mfa_enabled"]),
            "mfa_required": bool(m["mfa_required"]),
            "last_login_at": _iso(m["last_login_at"]),
            "created_at": _iso(m["created_at"]),
            "updated_at": _iso(m["updated_at"]),
        }

    async def session_info(self, user_id: str) -> dict[str, Any]:
        async with self._relational.unit_of_work() as uow:
            perms = (await uow.session.execute(_PERMS_SQL, {"id": user_id})).all()
            scope = (await uow.session.execute(_SCOPE_SQL, {"id": user_id})).all()
        return {
            "permissions": [str(r[0]) for r in perms],
            "account_scope": [str(r[0]) for r in scope],
        }
