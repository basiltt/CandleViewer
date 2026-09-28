"""Unit tests for `candleviewer.migrations.boot` (E03-T10).

Uses a fake `asyncpg` connection so no database is needed: exercises the
lock-acquire/release call sequence, the `CV_MIGRATION_LOCK_TIMEOUT` ->
`MigrationLockTimeout` path, and the subprocess failure -> `MigrationApplyFailed`
path. Real concurrent-boot serialisation against a live Postgres is covered
by `services/api/tests/integration/migrations/test_boot_advisory_lock.py`
(`@pytest.mark.integration`, needs docker — not run in this sandbox).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from candleviewer.migrations.boot import (
    MigrationApplyFailed,
    MigrationLockTimeout,
    run_migrations_under_advisory_lock,
    to_asyncpg_dsn,
    to_sync_dsn,
)


class _FakeConn:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.closed = False

    async def execute(self, query: str, *args: object) -> str:
        self.executed.append(query)
        return "SELECT 1"

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_conn() -> _FakeConn:
    return _FakeConn()


async def test_run_migrations_acquires_and_releases_lock(fake_conn: _FakeConn) -> None:
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with (
        patch("candleviewer.migrations.boot.asyncpg.connect", AsyncMock(return_value=fake_conn)),
        patch("candleviewer.migrations.boot.subprocess.run", return_value=completed) as run_mock,
    ):
        result = await run_migrations_under_advisory_lock(
            "postgresql://x", services_api_root=Path("."), lock_timeout_s=5.0
        )

    assert result.applied is True
    assert result.stdout == "ok"
    assert any("pg_advisory_lock" in q for q in fake_conn.executed)
    assert any("pg_advisory_unlock" in q for q in fake_conn.executed)
    assert fake_conn.closed is True
    run_mock.assert_called_once()


async def test_lock_released_even_when_upgrade_fails(fake_conn: _FakeConn) -> None:
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    with (
        patch("candleviewer.migrations.boot.asyncpg.connect", AsyncMock(return_value=fake_conn)),
        patch("candleviewer.migrations.boot.subprocess.run", return_value=completed),
        pytest.raises(MigrationApplyFailed, match="boom"),
    ):
        await run_migrations_under_advisory_lock(
            "postgresql://x", services_api_root=Path("."), lock_timeout_s=5.0
        )

    assert any("pg_advisory_unlock" in q for q in fake_conn.executed)
    assert fake_conn.closed is True


async def test_lock_timeout_raises_ci_dep_004(fake_conn: _FakeConn) -> None:
    call_count = 0

    async def _hang_once(query: str, *args: object) -> str:
        nonlocal call_count
        call_count += 1
        fake_conn.executed.append(query)
        if call_count == 1:
            # Only the lock-acquire call hangs; the `finally` block's
            # unlock call (reached after the wait_for cancels this one)
            # must still succeed so the connection is always released.
            import asyncio

            await asyncio.sleep(10)
        return "SELECT 1"

    fake_conn.execute = _hang_once  # type: ignore[method-assign]

    with (
        patch("candleviewer.migrations.boot.asyncpg.connect", AsyncMock(return_value=fake_conn)),
        pytest.raises(MigrationLockTimeout, match="CI-DEP-004"),
    ):
        await run_migrations_under_advisory_lock(
            "postgresql://x", services_api_root=Path("."), lock_timeout_s=0.01
        )

    assert fake_conn.closed is True


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql+asyncpg://u:p@h:5432/d",
        "postgresql+psycopg_async://u:p@h:5432/d",
        "postgresql+psycopg2://u:p@h:5432/d",
        "postgresql://u:p@h:5432/d",
    ],
)
def test_to_sync_dsn_any_driver_uses_sync_psycopg(dsn: str) -> None:
    assert to_sync_dsn(dsn) == "postgresql+psycopg://u:p@h:5432/d"
    assert to_asyncpg_dsn(dsn) == "postgresql://u:p@h:5432/d"


async def test_alembic_subprocess_receives_sync_dsn(fake_conn: _FakeConn) -> None:
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    connect = AsyncMock(return_value=fake_conn)
    with (
        patch("candleviewer.migrations.boot.asyncpg.connect", connect),
        patch("candleviewer.migrations.boot.subprocess.run", return_value=completed) as run_mock,
    ):
        await run_migrations_under_advisory_lock(
            "postgresql+asyncpg://u:p@h/d", services_api_root=Path("."), lock_timeout_s=5.0
        )

    assert run_mock.call_args.kwargs["env"]["CV_PG_DSN"] == "postgresql+psycopg://u:p@h/d"
    assert connect.call_args.kwargs["dsn"] == "postgresql://u:p@h/d"
