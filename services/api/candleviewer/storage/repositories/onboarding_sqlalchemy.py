"""Postgres store + read-only probes for the first-run checklist (E09-S06).

Static, parameterised SQL only; every query is scoped to the caller's own
`user_id`. Reads `mfa_methods` / `user_account_access` without selecting any
secret column.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_DISMISSED = sa.text("SELECT 1 FROM onboarding_dismissals WHERE user_id = CAST(:u AS uuid)")
_DISMISS = sa.text(
    "INSERT INTO onboarding_dismissals (user_id) VALUES (CAST(:u AS uuid)) "
    "ON CONFLICT (user_id) DO NOTHING"
)
_TOTP = sa.text(
    "SELECT 1 FROM mfa_methods WHERE user_id = CAST(:u AS uuid) AND kind = 'totp' "
    "AND confirmed_at IS NOT NULL AND revoked_at IS NULL LIMIT 1"
)
_BOUND = sa.text("SELECT 1 FROM user_account_access WHERE user_id = CAST(:u AS uuid) LIMIT 1")


class SqlAlchemyOnboardingStore:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def _exists(self, stmt: sa.TextClause, user_id: uuid.UUID) -> bool:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(stmt, {"u": str(user_id)})).first()
            await uow.commit()
        return row is not None

    async def is_dismissed(self, user_id: uuid.UUID) -> bool:
        return await self._exists(_DISMISSED, user_id)

    async def dismiss(self, user_id: uuid.UUID) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_DISMISS, {"u": str(user_id)})
            await uow.commit()

    async def has_confirmed_totp(self, user_id: uuid.UUID) -> bool:
        return await self._exists(_TOTP, user_id)

    async def has_account_binding(self, user_id: uuid.UUID) -> bool:
        return await self._exists(_BOUND, user_id)
