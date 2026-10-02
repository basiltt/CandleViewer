"""`SqlAlchemyInviteRepository` - Postgres `InviteRepository` (E09-S05).

Lives in M10 so `candleviewer.auth` never imports a storage driver (ADR-0003).
Static, parameterised SQL only. Single-use consumption and activation are
conditional UPDATE ... RETURNING statements, so concurrent redemptions cannot
both win. `user_account_access` is never written (a new user starts with zero
bindings; E27/E39 grant them). The raw token never reaches this layer.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_COLS = (
    "i.id::text AS id, i.user_id::text AS user_id, i.role::text AS role, "
    "u.username::text AS username, u.email::text AS email, u.display_name, "
    "u.status::text AS user_status, i.expires_at, i.consumed_at, i.revoked_at, "
    "i.created_at, i.pending_password_hash"
)
_FROM = "FROM user_invites i JOIN users u ON u.id = i.user_id AND u.deleted_at IS NULL"


def _sql(template: str) -> sa.TextClause:
    # Only the static column/from fragments above are substituted, never caller data.
    return sa.text(template.replace("@C@", _COLS).replace("@F@", _FROM))


_INSERT_USER = sa.text(
    "INSERT INTO users (id, email, username, display_name, password_hash, status, "
    "mfa_required, invited_by) VALUES (CAST(:id AS uuid), :email, :username, :dn, :ph, "
    "'invited', true, CAST(:by AS uuid))"
)
_INSERT_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id, granted_by) "
    "SELECT CAST(:id AS uuid), r.id, CAST(:by AS uuid) FROM roles r "
    "WHERE r.name = CAST(:role AS role_name)"
)
_INSERT_INVITE = sa.text(
    "INSERT INTO user_invites (id, user_id, role, token_hash, invited_by, expires_at, "
    "created_at) VALUES (CAST(:iid AS uuid), CAST(:id AS uuid), CAST(:role AS role_name), "
    ":th, CAST(:by AS uuid), :exp, :now)"
)
_INSERT_INVITE_NOW = sa.text(
    "INSERT INTO user_invites (id, user_id, role, token_hash, invited_by, expires_at) "
    "VALUES (CAST(:iid AS uuid), CAST(:id AS uuid), CAST(:role AS role_name), :th, "
    "CAST(:by AS uuid), :exp)"
)
_FIND = _sql("SELECT @C@ @F@ WHERE i.token_hash = :h")
_CONSUME = sa.text(
    "WITH c AS (UPDATE user_invites SET consumed_at = :now, pending_password_hash = :pp "
    "WHERE token_hash = :h AND consumed_at IS NULL AND revoked_at IS NULL "
    "AND expires_at > :now RETURNING id) SELECT id::text FROM c"
)
_ACTIVATE = sa.text(
    "UPDATE users SET password_hash = :ph, password_algo_params = CAST(:ap AS jsonb), "
    "password_changed_at = :now, status = 'active', updated_at = :now "
    "WHERE id = CAST(:id AS uuid) AND status = 'invited' RETURNING 1"
)
_CLEAR_PENDING = sa.text(
    "UPDATE user_invites SET pending_password_hash = NULL WHERE user_id = CAST(:id AS uuid)"
)
_REVOKE = sa.text(
    "UPDATE user_invites SET revoked_at = :now WHERE user_id = CAST(:id AS uuid) "
    "AND consumed_at IS NULL AND revoked_at IS NULL RETURNING 1"
)
_IS_INVITED = sa.text(
    "SELECT role::text AS role FROM user_invites i JOIN users u ON u.id = i.user_id "
    "WHERE u.id = CAST(:id AS uuid) AND u.status = 'invited' AND u.deleted_at IS NULL "
    "ORDER BY i.created_at DESC LIMIT 1"
)
_PENDING = _sql(
    "SELECT @C@ @F@ WHERE i.consumed_at IS NULL AND i.revoked_at IS NULL "
    "AND u.status = 'invited' ORDER BY i.created_at DESC"
)
_FIND_BY_ID = _sql("SELECT @C@ @F@ WHERE i.id = CAST(:iid AS uuid)")


class SqlAlchemyInviteRepository:
    def __init__(
        self, relational: SqlAlchemyRelationalRepository, record_factory: Callable[..., Any]
    ) -> None:
        self._relational = relational
        self._record = record_factory

    async def create_user_with_invite(
        self,
        *,
        user_id: uuid.UUID,
        invite_id: uuid.UUID,
        email: str,
        username: str,
        display_name: str | None,
        role: str,
        placeholder_password_hash: str,
        invited_by: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> bool:
        try:
            async with self._relational.unit_of_work() as uow:
                s = uow.session
                await s.execute(
                    _INSERT_USER,
                    {
                        "id": str(user_id),
                        "email": email,
                        "username": username,
                        "dn": display_name,
                        "ph": placeholder_password_hash,
                        "by": str(invited_by),
                    },
                )
                await s.execute(
                    _INSERT_ROLE, {"id": str(user_id), "by": str(invited_by), "role": role}
                )
                await s.execute(
                    _INSERT_INVITE_NOW,
                    {
                        "iid": str(invite_id),
                        "id": str(user_id),
                        "role": role,
                        "th": token_hash,
                        "by": str(invited_by),
                        "exp": expires_at,
                    },
                )
                await uow.commit()
        except IntegrityError:
            return False
        return True

    async def _rows(self, stmt: sa.TextClause, params: dict[str, Any]) -> list[Any]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(stmt, params)).all()
            await uow.commit()
        return list(rows)

    def _make(self, row: Any) -> Any:
        return self._record(**dict(row._mapping))

    async def find_by_token_hash(self, token_hash: str) -> Any:
        rows = await self._rows(_FIND, {"h": token_hash})
        return self._make(rows[0]) if rows else None

    async def consume(self, token_hash: str, *, now: datetime, pending_password_hash: str) -> Any:
        rows = await self._rows(
            _CONSUME, {"h": token_hash, "now": now, "pp": pending_password_hash}
        )
        if not rows:
            return None
        return await self.find_by_token_hash(token_hash)

    async def find_consumed_for_user(self, user_id: uuid.UUID) -> Any:
        rows = await self._rows(
            _sql(
                "SELECT @C@ @F@ WHERE i.user_id = CAST(:id AS uuid) AND i.consumed_at IS NOT NULL "
                "AND i.revoked_at IS NULL AND u.status = 'invited' "
                "ORDER BY i.created_at DESC LIMIT 1"
            ),
            {"id": str(user_id)},
        )
        return self._make(rows[0]) if rows else None

    async def activate_user(
        self, user_id: uuid.UUID, *, password_hash: str, algo_params: dict[str, int], now: datetime
    ) -> bool:
        async with self._relational.unit_of_work() as uow:
            won = (
                await uow.session.execute(
                    _ACTIVATE,
                    {
                        "id": str(user_id),
                        "ph": password_hash,
                        "ap": json.dumps(algo_params),
                        "now": now,
                    },
                )
            ).all()
            if won:
                await uow.session.execute(_CLEAR_PENDING, {"id": str(user_id)})
            await uow.commit()
        return bool(won)

    async def reissue(
        self,
        user_id: uuid.UUID,
        *,
        invite_id: uuid.UUID,
        token_hash: str,
        invited_by: uuid.UUID,
        expires_at: datetime,
        now: datetime,
    ) -> Any:
        async with self._relational.unit_of_work() as uow:
            s = uow.session
            row = (await s.execute(_IS_INVITED, {"id": str(user_id)})).first()
            if row is None:
                return None
            await s.execute(
                sa.text(
                    "UPDATE user_invites SET revoked_at = :now WHERE user_id = CAST(:id AS uuid) "
                    "AND revoked_at IS NULL AND (consumed_at IS NULL OR pending_password_hash "
                    "IS NOT NULL)"
                ),
                {"id": str(user_id), "now": now},
            )
            await s.execute(
                _INSERT_INVITE,
                {
                    "iid": str(invite_id),
                    "id": str(user_id),
                    "role": row.role,
                    "th": token_hash,
                    "by": str(invited_by),
                    "exp": expires_at,
                    "now": now,
                },
            )
            fresh = (await s.execute(_FIND_BY_ID, {"iid": str(invite_id)})).first()
            await uow.commit()
        return self._make(fresh) if fresh is not None else None

    async def revoke_open(self, user_id: uuid.UUID, *, now: datetime) -> bool:
        rows = await self._rows(_REVOKE, {"id": str(user_id), "now": now})
        return bool(rows)

    async def list_pending(self, *, now: datetime) -> tuple[Any, ...]:
        rows = await self._rows(_PENDING, {})
        return tuple(self._make(r) for r in rows)
