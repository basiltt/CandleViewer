"""Integration: concurrent login failures against real Postgres 16 (SR-015/SR-016).

Drives the real SQL `record_login_failure` with N concurrent callers; a lost update
would leave the count below N or miss the lock. Not run locally (no docker); CI only.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.login_service import LOCKOUT_THRESHOLD
from candleviewer.auth.models import UserRecord
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime.now(UTC).replace(microsecond=0)
_LOCK = timedelta(minutes=15)


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


def _rec(model: Any) -> Callable[..., Any]:
    return lambda **f: model.model_validate(f)


async def _burst(pg_dsn: str, name: str, n: int) -> tuple[UserRecord, list[datetime | None]]:
    await seed(pg_dsn, name, "correct horse battery")
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    users = SqlAlchemyUserRepository(rel, _rec(UserRecord), clock=lambda: _NOW)
    try:
        user = await users.find_by_identifier(name)
        assert user is not None
        results = await asyncio.gather(
            *(
                users.record_login_failure(
                    str(user.id), lockout_threshold=LOCKOUT_THRESHOLD, lock_duration=_LOCK, now=_NOW
                )
                for _ in range(n)
            )
        )
        final = await users.find_by_identifier(name)
        assert final is not None
        return final, list(results)
    finally:
        await rel.dispose()


async def test_concurrent_failures_count_exactly_and_lock_at_threshold(pg_dsn: str) -> None:
    n = LOCKOUT_THRESHOLD * 3
    final, results = await _burst(pg_dsn, "race-a", n)

    assert final.failed_login_count == n  # no lost update
    assert final.locked_until == _NOW + _LOCK
    # Exactly the failures numbered >= threshold report a lock.
    assert sum(r is not None for r in results) == n - LOCKOUT_THRESHOLD + 1


async def test_exactly_threshold_concurrent_failures_lock(pg_dsn: str) -> None:
    final, results = await _burst(pg_dsn, "race-b", LOCKOUT_THRESHOLD)

    assert final.failed_login_count == LOCKOUT_THRESHOLD
    assert final.locked_until == _NOW + _LOCK
    assert sum(r is not None for r in results) == 1


async def test_threshold_minus_one_concurrent_failures_do_not_lock(pg_dsn: str) -> None:
    final, results = await _burst(pg_dsn, "race-c", LOCKOUT_THRESHOLD - 1)

    assert final.failed_login_count == LOCKOUT_THRESHOLD - 1
    assert final.locked_until is None
    assert all(r is None for r in results)
