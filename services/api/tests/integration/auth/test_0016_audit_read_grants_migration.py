"""Integration: `0016_audit_read_grants` round-trip on real Postgres 16 (#2083).

upgrade 0016 -> downgrade 0015 -> upgrade 0016 (C-5.5); the grant set at each step matches
04-security-program.md §7.2.1 (manager + owner) and, after downgrade, the 0001 seed.
Not run locally (no docker); exercised by the integration/migrations CI jobs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_GRANTS_SQL = (
    "SELECT r.name FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
    "JOIN permissions p ON p.id = rp.permission_id WHERE p.code = 'audit:read' ORDER BY 1"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn},
        check=True,
    )


def _grants(dsn: str) -> list[str]:
    with psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql")) as conn:
        return [str(r[0]) for r in conn.execute(_GRANTS_SQL).fetchall()]


def test_0016_round_trip_moves_audit_read_grant(pg_dsn: str) -> None:
    _alembic(pg_dsn, "upgrade", "0016_audit_read_grants")
    assert _grants(pg_dsn) == ["manager", "owner"]
    _alembic(pg_dsn, "downgrade", "0015_rules_arm_live_permission")
    assert _grants(pg_dsn) == ["owner", "viewer"]
    _alembic(pg_dsn, "upgrade", "0016_audit_read_grants")
    assert _grants(pg_dsn) == ["manager", "owner"]
