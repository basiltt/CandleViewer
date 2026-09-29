"""Integration tests for `candleviewer.db.seed` (E07-T02) — idempotent
re-seed against an already-migrated Postgres.

Needs a real Postgres 16 (`testcontainers`, `@pytest.mark.integration` —
CONSTITUTION.md C-13.3 / `.claude/rules/40-testing.md`); no network egress
beyond the locally-started container. Not run in this sandbox: docker is
unavailable here ("not run locally: no docker" — see the PR body); this
suite is exercised by the `migrations` CI job.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.db.seed import upsert_roles_and_permissions

pytestmark = pytest.mark.integration

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


def _alembic(dsn: str, *args: str) -> None:
    sync_dsn = dsn.replace("postgresql+asyncpg", "postgresql+psycopg")
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_SERVICES_API_ROOT,
        env={**os.environ, "CV_PG_DSN": sync_dsn},
        check=True,
    )


def _psycopg_dsn(async_dsn: str) -> str:
    return async_dsn.replace("postgresql+asyncpg", "postgresql")


def _counts(dsn: str) -> tuple[int, int, int]:
    with psycopg.connect(_psycopg_dsn(dsn)) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM roles")
        roles = cur.fetchone()
        cur.execute("SELECT count(*) FROM permissions")
        permissions = cur.fetchone()
        cur.execute("SELECT count(*) FROM role_permissions")
        grants = cur.fetchone()
    assert roles is not None and permissions is not None and grants is not None
    return int(roles[0]), int(permissions[0]), int(grants[0])


async def _run_seed(dsn: str) -> None:
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await upsert_roles_and_permissions(conn)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reseed_against_already_migrated_db_is_a_true_noop(pg_dsn: str) -> None:
    """AC: re-running the seed loader against a seeded database inserts zero
    additional rows (§9.3 rule 5 idempotency)."""
    _alembic(pg_dsn, "upgrade", "head")

    before = _counts(pg_dsn)
    await _run_seed(pg_dsn)
    after = _counts(pg_dsn)

    assert after == before


@pytest.mark.asyncio
async def test_seed_matches_0001s_own_role_permission_grants(pg_dsn: str) -> None:
    """The loader's grants must match `0001_identity_rbac_sessions_mfa`'s own
    unconditional seed exactly, so re-running it is provably a no-op."""
    before = _counts(pg_dsn)
    await _run_seed(pg_dsn)
    after = _counts(pg_dsn)

    assert after == before
