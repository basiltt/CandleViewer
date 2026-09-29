"""Integration: `0003_audit_log` + `SqlAlchemyAuditRepository` against real
Postgres 16 (testcontainers). Covers the DB-side AC: trigger-computed chain
with 64-zero genesis, Python verifier agreeing byte-for-byte with the
trigger, out-of-band tamper located, cv_app refused UPDATE/DELETE,
round-trip upgrade/downgrade/upgrade, checkpoint idempotency.

Not run locally (no docker); exercised by the `migrations`/integration CI jobs.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.models import VerifyResult
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        _alembic(dsn, "upgrade", "head")
        yield dsn


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        check=True,
    )


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


async def _emit_n(dsn: str, n: int, wal: Path) -> None:
    """Engine is built inside the running loop and disposed before it closes
    (never shared across `asyncio.run` calls — asyncpg futures are
    loop-bound; that was the `different loop` CI failure)."""
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        writer = AuditWriter(SqlAlchemyAuditRepository(relational), str(wal))
        await writer.start()
        for i in range(n):
            await writer.emit(
                "orders.submit",
                actor_label="bot",
                actor_ip="10.0.0.7",
                object_id=str(i),
                before_state={"qty": "0.01", "password_hash": "x"} if i % 2 else None,
            )
        await writer.flush(60)
        await writer.stop(5)
    finally:
        await relational.dispose()


async def _verify(dsn: str) -> VerifyResult:
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        return await AuditQueryService(SqlAlchemyAuditRepository(relational)).verify()
    finally:
        await relational.dispose()


def test_trigger_chain_genesis_and_python_verifier_agree(pg_dsn: str, tmp_path: Path) -> None:
    asyncio.run(_emit_n(pg_dsn, 1000, tmp_path / "a.wal"))
    with psycopg.connect(_sync(pg_dsn)) as conn:
        first = conn.execute("SELECT prev_hash FROM audit_log ORDER BY id LIMIT 1").fetchone()
        assert first is not None and first[0] == "0" * 64
        leak = conn.execute(
            "SELECT count(*) FROM audit_log WHERE before_state::text LIKE '%\"x\"%'"
        )
        assert leak.fetchone() == (0,)
    result = asyncio.run(_verify(pg_dsn))
    assert result.verified and result.entries_checked >= 1000


def test_superuser_tamper_is_located(pg_dsn: str, tmp_path: Path) -> None:
    asyncio.run(_emit_n(pg_dsn, 5, tmp_path / "b.wal"))
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        victim = conn.execute("SELECT max(id) - 2 FROM audit_log").fetchone()
        assert victim is not None
        conn.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_append")
        conn.execute("UPDATE audit_log SET reason = 'forged' WHERE id = %s", (victim[0],))
        conn.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_append")
    result = asyncio.run(_verify(pg_dsn))
    assert not result.verified and result.first_bad_id == victim[0]


def test_truncate_refused_even_for_owner(pg_dsn: str) -> None:
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute("TRUNCATE audit_log")


def test_app_role_cannot_update_or_delete(pg_dsn: str) -> None:
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        conn.execute("CREATE ROLE cv_app_t LOGIN PASSWORD 'test-only'")
        conn.execute("GRANT SELECT, INSERT ON audit_log TO cv_app_t")
        conn.execute("SET ROLE cv_app_t")
        for stmt in ("UPDATE audit_log SET reason = 'x'", "DELETE FROM audit_log"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(stmt)


def test_migration_downgrade_refused_while_audit_history_exists(
    pg_dsn: str, tmp_path: Path
) -> None:
    asyncio.run(_emit_n(pg_dsn, 1, tmp_path / "c.wal"))
    with pytest.raises(subprocess.CalledProcessError):
        _alembic(pg_dsn, "downgrade", "0002_rbac_seed")


def test_migration_round_trip_on_empty_db() -> None:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        _alembic(dsn, "upgrade", "head")
        _alembic(dsn, "downgrade", "0002_rbac_seed")
        _alembic(dsn, "upgrade", "head")
