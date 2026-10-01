"""Integration: single-use invite redemption on real Postgres 16 (E09-S05).

Concurrent `consume` calls must have exactly one winner. Not run locally (no
docker); exercised by CI `integration`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.models import InviteRecord, UserRecord
from candleviewer.storage.repositories.invites_sqlalchemy import SqlAlchemyInviteRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 10, 1, tzinfo=UTC)
PW = "pending-hash"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


async def test_concurrent_consume_has_exactly_one_winner(pg_dsn: str) -> None:
    await seed(pg_dsn, "owner1", "correct horse battery")
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    repo = SqlAlchemyInviteRepository(rel, lambda **f: InviteRecord.model_validate(f))
    try:
        users = SqlAlchemyUserRepository(rel, lambda **f: UserRecord.model_validate(f))
        owner = await users.find_by_identifier("owner1")
        assert owner is not None
        by = owner.id
        th = "h" * 64
        created = await repo.create_user_with_invite(
            user_id=uuid.uuid4(),
            invite_id=uuid.uuid4(),
            email="race@example.com",
            username="racer",
            display_name=None,
            role="viewer",
            placeholder_password_hash="x",  # noqa: S106 - placeholder, not a credential
            invited_by=by,
            token_hash=th,
            expires_at=_NOW + timedelta(hours=72),
        )
        assert created is True
        results = await asyncio.gather(
            *(repo.consume(th, now=_NOW, pending_password_hash=PW) for _ in range(8))
        )
        assert sum(r is not None for r in results) == 1
        assert await repo.consume(th, now=_NOW, pending_password_hash=PW) is None
    finally:
        await rel.dispose()
