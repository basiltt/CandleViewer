"""Integration: `0013_rules` + `SqlAlchemyRulesRepository` against real Postgres 16.

Covers the E35-T02 Gherkin scenarios: reversible migration, `rule_armed_shape`,
no duplicate version for an unchanged IR, append-only `rule_events`, retention
that prunes noise but keeps evidence, plus CHECK boundaries and cascades.

Not run locally (no docker); exercised by the integration/migrations CI jobs.
"""

from __future__ import annotations

import asyncio
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

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.rules_sqlalchemy import SqlAlchemyRulesRepository

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_H1 = "a" * 64
_H2 = "b" * 64
_IR = '{"conditions": {}, "actions": []}'


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


def _user(c: psycopg.Connection[tuple[object, ...]]) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, '$argon2id$x')",
        (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
    )
    return uid


def _rule(c: psycopg.Connection[tuple[object, ...]], owner: str, name: str | None = None) -> str:
    rid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO rules (id, name, owner_user_id) VALUES (%s, %s, %s)",
        (rid, name or rid, owner),
    )
    return rid


def _version(c: psycopg.Connection[tuple[object, ...]], rule: str, n: int, h: str) -> str:
    vid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO rule_versions (id, rule_id, version, ir, ir_hash, compiler_version) "
        "VALUES (%s, %s, %s, %s::jsonb, %s, '1.0.0')",
        (vid, rule, n, _IR, h),
    )
    return vid


def _run(
    c: psycopg.Connection[tuple[object, ...]],
    rule: str,
    ver: str,
    *,
    matched: bool,
    age_days: int,
) -> str:
    rid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO rule_runs (id, rule_id, rule_version_id, mode, trigger_reason, "
        "input_snapshot, matched, started_at) VALUES (%s, %s, %s, 'simulate', 'tick', "
        "'{}'::jsonb, %s, now() - make_interval(days => %s))",
        (rid, rule, ver, matched, age_days),
    )
    c.execute("INSERT INTO rule_events (rule_run_id, seq, kind) VALUES (%s, 1, 'log')", (rid,))
    return rid


def test_migration_applies_and_reverses_cleanly(pg_dsn: str) -> None:
    _alembic(pg_dsn, "downgrade", "0012_onboarding_dismissals")
    with _conn(pg_dsn) as c:
        left = c.execute(
            "SELECT count(*) FROM pg_tables WHERE tablename LIKE 'rule\\_%' OR tablename='rules'"
        ).fetchone()
        types = c.execute("SELECT count(*) FROM pg_type WHERE typname LIKE 'rule\\_%'").fetchone()
        assert left == (0,) and types == (0,)
    _alembic(pg_dsn, "upgrade", "head")


def test_armed_rule_must_be_fully_specified(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        rule = _rule(c, _user(c))
        with pytest.raises(pgerr.CheckViolation, match="rule_armed_shape"):
            c.execute("UPDATE rules SET mode = 'armed' WHERE id = %s", (rule,))


@pytest.mark.parametrize(
    ("col", "good", "bad"),
    [
        ("eval_interval_ms", (50, 3600000), (49, 3600001)),
        ("cooldown_seconds", (0, 86400), (-1, 86401)),
        ("priority", (0, 1000), (-1, 1001)),
    ],
)
def test_rule_check_boundaries(
    pg_dsn: str, col: str, good: tuple[int, int], bad: tuple[int, int]
) -> None:
    with _conn(pg_dsn) as c:
        rule = _rule(c, _user(c))
        for v in good:
            c.execute(f"UPDATE rules SET {col} = %s WHERE id = %s", (v, rule))  # noqa: S608
        for v in bad:
            with pytest.raises(pgerr.CheckViolation):
                c.execute(f"UPDATE rules SET {col} = %s WHERE id = %s", (v, rule))  # noqa: S608


def test_unchanged_ir_creates_no_new_version(pg_dsn: str) -> None:
    async def go() -> tuple[bool, bool, int, int]:
        with _conn(pg_dsn) as c:
            rule = _rule(c, _user(c))
        repo = SqlAlchemyRulesRepository(SqlAlchemyRelationalRepository(pg_dsn))
        ir = {"conditions": {}, "actions": []}
        a = await repo.save_version(rule, ir, _H1, compiler_version="1.0.0")
        b = await repo.save_version(rule, ir, _H1, compiler_version="1.0.0")
        c2 = await repo.save_version(rule, ir, _H2, compiler_version="1.0.0")
        return a.created, b.created, b.version, c2.version

    assert asyncio.run(go()) == (True, False, 1, 2)


def test_unique_names_versions_and_hashes(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        _rule(c, owner, "Alpha")
        with pytest.raises(pgerr.UniqueViolation):
            _rule(c, owner, "ALPHA")
        rule = _rule(c, owner)
        _version(c, rule, 1, _H1)
        with pytest.raises(pgerr.UniqueViolation):
            _version(c, rule, 1, _H2)
        with pytest.raises(pgerr.UniqueViolation):
            _version(c, rule, 2, _H1)


def test_rule_events_are_append_only(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        rule = _rule(c, _user(c))
        run = _run(c, rule, _version(c, rule, 1, _H1), matched=True, age_days=0)
        with pytest.raises(pgerr.RaiseException, match="append-only"):
            c.execute("UPDATE rule_events SET kind = 'throttled' WHERE rule_run_id = %s", (run,))
        with pytest.raises(pgerr.RaiseException, match="append-only"):
            c.execute("DELETE FROM rule_events WHERE rule_run_id = %s", (run,))
        # no GUC/role bypass: the owner connection cannot delete directly either
        c.execute("SELECT set_config('cv.rule_retention', 'on', true)")
        with pytest.raises(pgerr.RaiseException, match="append-only"):
            c.execute("DELETE FROM rule_events WHERE rule_run_id = %s", (run,))
        assert c.execute(
            "SELECT kind FROM rule_events WHERE rule_run_id = %s", (run,)
        ).fetchone() == ("log",)


def test_active_version_delete_is_restricted_and_rule_delete_cascades(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        rule = _rule(c, owner)
        ver = _version(c, rule, 1, _H1)
        c.execute("UPDATE rules SET active_version_id = %s WHERE id = %s", (ver, rule))
        with pytest.raises(pgerr.ForeignKeyViolation):
            c.execute("DELETE FROM rule_versions WHERE id = %s", (ver,))
        c.execute("UPDATE rules SET active_version_id = NULL WHERE id = %s", (rule,))
        _run(c, rule, ver, matched=True, age_days=0)
        # rule delete cascades to versions and runs; the immutable events trigger
        # still refuses the cascaded event delete, so the delete is refused as a whole.
        with pytest.raises(pgerr.RaiseException, match="append-only"):
            c.execute("DELETE FROM rules WHERE id = %s", (rule,))


def test_retention_prunes_noise_but_keeps_evidence(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        rule = _rule(c, _user(c))
        ver = _version(c, rule, 1, _H1)
        noise = _run(c, rule, ver, matched=False, age_days=8)
        evidence = _run(c, rule, ver, matched=True, age_days=8)
        fresh = _run(c, rule, ver, matched=False, age_days=1)

    pruned: list[int] = []
    repo = SqlAlchemyRulesRepository(
        SqlAlchemyRelationalRepository(pg_dsn), on_pruned=pruned.append
    )
    result = asyncio.run(repo.prune_unmatched())

    assert result.runs_deleted >= 1 and pruned == [result.runs_deleted]
    with _conn(pg_dsn) as c:
        ids = {str(r[0]) for r in c.execute("SELECT id FROM rule_runs").fetchall()}
        assert noise not in ids and evidence in ids and fresh in ids
        events = c.execute(
            "SELECT count(*) FROM rule_events WHERE rule_run_id = %s", (noise,)
        ).fetchone()
        assert events == (0,)
