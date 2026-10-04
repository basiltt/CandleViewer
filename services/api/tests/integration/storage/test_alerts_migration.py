"""Integration: `0014_alerts` + alert repositories against real Postgres 16 (E40-T01).

Covers the Gherkin scenarios: constraint rejection, append-only deliveries for
the app role vs `cv_owner`, partial-index use, reversible migration.
Not run locally (no docker); exercised by the integration/migrations CI jobs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import errors as pgerr
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_H = "a" * 64
_IR = '{"conditions": {}}'


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        check=True,
    )


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        _alembic(dsn, "upgrade", "head")
        yield dsn


def _conn(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _alert(c: psycopg.Connection[tuple[object, ...]], **over: object) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, display_name, password_hash, status) "
        "VALUES (%s, %s, %s, 'u', '$argon2id$placeholder', 'active')",
        (uid, f"{uid}@example.test", f"u{uid[:12]}"),
    )
    aid = str(uuid.uuid4())
    cols = {
        "id": aid,
        "owner_user_id": uid,
        "name": f"a-{aid}",
        "condition_ir": _IR,
        "condition_hash": _H,
        **over,
    }
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    c.execute(f"INSERT INTO alerts ({names}) VALUES ({marks})", list(cols.values()))  # noqa: S608
    return aid


def test_constraints_reject_bad_data(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        with pytest.raises(pgerr.CheckViolation, match="al_cooldown"):
            _alert(c, cooldown_seconds=90000)
        with pytest.raises(pgerr.CheckViolation, match="al_channels"):
            _alert(c, channels="{in_app,email,webhook,push,desktop,in_app}")
        with pytest.raises(pgerr.CheckViolation, match="al_webhook"):
            _alert(c, channels="{webhook}")


def test_deliveries_append_only_for_app_role_and_purgeable_by_owner(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        aid = _alert(c)
        c.execute(
            "INSERT INTO alert_deliveries (alert_id, channel, title) VALUES (%s, 'in_app', 't')",
            (aid,),
        )
        c.execute("UPDATE alert_deliveries SET status = 'sent' WHERE alert_id = %s", (aid,))
        c.execute("CREATE ROLE cv_owner LOGIN SUPERUSER")
        c.execute("CREATE ROLE cv_app_t LOGIN")
        c.execute("GRANT ALL ON alert_deliveries TO cv_app_t")
        c.execute("SET SESSION AUTHORIZATION cv_app_t")
        with pytest.raises(pgerr.RaiseException, match="append-only"):
            c.execute("DELETE FROM alert_deliveries WHERE alert_id = %s", (aid,))
        c.execute("RESET SESSION AUTHORIZATION")
        c.execute("SET SESSION AUTHORIZATION cv_owner")
        c.execute("DELETE FROM alert_deliveries WHERE alert_id = %s", (aid,))
        c.execute("RESET SESSION AUTHORIZATION")


def test_live_alert_query_uses_partial_index(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        aid = _alert(c)
        c.execute(
            "INSERT INTO alerts (owner_user_id, name, symbol, condition_ir, condition_hash) "
            "SELECT owner_user_id, 'bulk-' || g, 'SYM' || (g % 50), condition_ir, condition_hash "
            "FROM alerts, generate_series(1, 500) g WHERE id = %s",
            (aid,),
        )
        c.execute(
            "UPDATE alerts SET enabled = false WHERE name LIKE 'bulk-%%' AND symbol <> 'SYM1'"
        )
        c.execute("ANALYZE alerts")
        plan = "\n".join(
            str(r[0])
            for r in c.execute(
                "EXPLAIN SELECT id FROM alerts WHERE symbol = 'BTCUSDT' "
                "AND enabled AND deleted_at IS NULL"
            )
        )
        assert "ix_alerts_live" in plan


def test_downgrade_refuses_when_populated_then_drops_when_empty(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _alert(c)
        with pytest.raises(subprocess.CalledProcessError):
            _alembic(pg_dsn, "downgrade", "0013_rules")
        c.execute("DELETE FROM alerts")
        _alembic(pg_dsn, "downgrade", "0013_rules")
        _alembic(pg_dsn, "upgrade", "head")
