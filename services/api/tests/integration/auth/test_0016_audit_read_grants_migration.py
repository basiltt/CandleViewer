"""Integration: `0016_audit_read_grants` round-trip on real Postgres 16 (#2083).

upgrade 0016 -> downgrade 0015 -> upgrade 0016 (C-5.5), plus idempotency on a pre-seeded
DB. The exact role set is asserted, so no other role may gain the grant. Each step matches
04-security-program.md §7.2.1 (manager + owner) and, after downgrade, the 0001 seed.
Not run locally (no docker); exercised by the integration/migrations CI jobs.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

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


def _grants(dsn: str) -> set[str]:
    with psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql")) as conn:
        return {str(r[0]) for r in conn.execute(_GRANTS_SQL).fetchall()}


def _run_sql(dsn: str, *statements: str) -> None:
    with psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True) as c:
        for sql in statements:
            c.execute(sql)


def _rev_0016() -> ModuleType:
    path = _ROOT / "candleviewer" / "migrations" / "versions" / "0016_audit_read_grants.py"
    spec = importlib.util.spec_from_file_location("_rev_0016_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_0016_round_trip_moves_audit_read_grant(pg_dsn: str) -> None:
    _alembic(pg_dsn, "upgrade", "0016_audit_read_grants")
    assert _grants(pg_dsn) == {"manager", "owner"}
    _alembic(pg_dsn, "downgrade", "0015_rules_arm_live_permission")
    assert _grants(pg_dsn) == {"owner", "viewer"}
    _alembic(pg_dsn, "upgrade", "0016_audit_read_grants")
    assert _grants(pg_dsn) == {"manager", "owner"}


def test_0016_upgrade_is_idempotent_on_a_pre_seeded_db(pg_dsn: str) -> None:
    """A DB already re-seeded by `db/seed.py` (manager grant present) upgrades cleanly,
    and re-applying the upgrade SQL is a no-op: no duplicate grant, no other role gains it."""
    rev = _rev_0016()
    _alembic(pg_dsn, "downgrade", "0015_rules_arm_live_permission")
    _run_sql(pg_dsn, rev._GRANT.format(role="manager"))
    _alembic(pg_dsn, "upgrade", "0016_audit_read_grants")
    _run_sql(pg_dsn, rev._REVOKE_VIEWER, rev._GRANT.format(role="manager"))
    assert _grants(pg_dsn) == {"manager", "owner"}
    with psycopg.connect(pg_dsn.replace("postgresql+psycopg", "postgresql")) as conn:
        dupes = conn.execute(
            "SELECT count(*) FROM role_permissions rp JOIN permissions p "
            "ON p.id = rp.permission_id WHERE p.code = 'audit:read' "
            "GROUP BY rp.role_id HAVING count(*) > 1"
        ).fetchall()
    assert dupes == []
