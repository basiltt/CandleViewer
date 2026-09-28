"""Integration tests for the E09-T01 identity/RBAC/session/MFA migration.

Needs a real Postgres 16 (`testcontainers`, `@pytest.mark.integration` —
CONSTITUTION.md C-13.3 / `.claude/rules/40-testing.md`); no network egress
beyond the locally-started container, no live exchange. Not run in this
sandbox: docker is unavailable here ("not run locally: no docker" — see the
PR body); this suite is exercised by the `migrations` CI job.
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

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]
_REVISION = "0001_identity_rbac_sessions_mfa"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


def _alembic(dsn: str, *args: str) -> None:
    # Fixed argv (sys.executable + literal alembic subcommands from this test
    # module only); no shell, no untrusted input.
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_SERVICES_API_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn},
        check=True,
    )


def _psycopg_dsn(async_dsn: str) -> str:
    return async_dsn.replace("postgresql+asyncpg", "postgresql")


def test_migration_applies_reverses_and_reapplies_cleanly(pg_dsn: str) -> None:
    """AC: 'Migration applies and reverses cleanly.'"""
    _alembic(pg_dsn, "upgrade", "head")
    _alembic(pg_dsn, "downgrade", "-1")
    _alembic(pg_dsn, "upgrade", "head")

    with psycopg.connect(_psycopg_dsn(pg_dsn)) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        tables = {row[0] for row in cur.fetchall()}
    expected = {
        "users",
        "roles",
        "permissions",
        "role_permissions",
        "user_roles",
        "user_account_access",
        "sessions",
        "sessions_rotation",
        "mfa_methods",
        "mfa_challenges",
        "recovery_codes",
        "alembic_version",
    }
    assert expected <= tables


@pytest.fixture(scope="module")
def migrated_conn(pg_dsn: str) -> Iterator[psycopg.Connection]:
    _alembic(pg_dsn, "upgrade", "head")
    conn = psycopg.connect(_psycopg_dsn(pg_dsn), autocommit=False)
    yield conn
    conn.close()


def _insert_user(cur: psycopg.Cursor, *, email: str, username: str, status: str = "active") -> str:
    cur.execute(
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (gen_random_uuid(), %s, %s, %s, %s) RETURNING id",
        (email, username, "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA", status),
    )
    row = cur.fetchone()
    assert row is not None
    return str(row[0])


def _owner_role_id(cur: psycopg.Cursor) -> str:
    cur.execute("SELECT id FROM roles WHERE name = 'owner'")
    row = cur.fetchone()
    assert row is not None
    return str(row[0])


def test_owner_floor_rejects_removing_the_last_active_owner(
    migrated_conn: psycopg.Connection,
) -> None:
    """AC: 'The owner floor is enforced by the database.'"""
    conn = migrated_conn
    with conn.cursor() as cur:
        user_id = _insert_user(cur, email="owner1@example.com", username="owner_one")
        owner_role_id = _owner_role_id(cur)
        cur.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)",
            (user_id, owner_role_id),
        )
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("DELETE FROM user_roles WHERE user_id = %s", (user_id,))
        # ERRCODE 23514 is mapped by psycopg to CheckViolation, not RaiseException.
        with pytest.raises(psycopg.errors.CheckViolation) as excinfo:
            conn.commit()
    assert excinfo.value.sqlstate == "23514"
    conn.rollback()

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM user_roles WHERE user_id = %s", (user_id,))
        assert cur.fetchone() is not None
    conn.rollback()


def test_owner_floor_allows_reshuffle_within_one_transaction(
    migrated_conn: psycopg.Connection,
) -> None:
    """Deferred trigger only checks end-of-transaction state."""
    conn = migrated_conn
    with conn.cursor() as cur:
        first_id = _insert_user(cur, email="owner2@example.com", username="owner_two")
        owner_role_id = _owner_role_id(cur)
        cur.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)",
            (first_id, owner_role_id),
        )
    conn.commit()

    with conn.cursor() as cur:
        second_id = _insert_user(cur, email="owner3@example.com", username="owner_three")
        cur.execute("DELETE FROM user_roles WHERE user_id = %s", (first_id,))
        cur.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)",
            (second_id, owner_role_id),
        )
    conn.commit()  # must succeed: exactly one owner at commit time

    with conn.cursor() as cur:
        # The module-scoped connection has already committed other owners in
        # earlier tests; assert on *this* test's reshuffle, not on a global count.
        cur.execute(
            "SELECT user_id FROM user_roles WHERE role_id = %s AND user_id IN (%s, %s)",
            (owner_role_id, first_id, second_id),
        )
        rows = [str(r[0]) for r in cur.fetchall()]  # psycopg returns uuid.UUID
        assert rows == [str(second_id)]
    conn.rollback()


def test_non_argon2id_password_hash_rejected(migrated_conn: psycopg.Connection) -> None:
    """AC: 'Non-Argon2id password hashes are rejected at the storage layer.'"""
    conn = migrated_conn
    with conn.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        cur.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (gen_random_uuid(), 'bcrypt@example.com', 'bcrypt_user', %s)",
            ("$2b$12$abcdefghijklmnopqrstuv",),
        )
    conn.rollback()


def test_soft_deleted_user_frees_email_and_username(migrated_conn: psycopg.Connection) -> None:
    """AC: 'Soft-deleted users free their email and username.'"""
    conn = migrated_conn
    email, username = "recycled@example.com", "recycled_user"
    with conn.cursor() as cur:
        first_id = _insert_user(cur, email=email, username=username)
        cur.execute("UPDATE users SET deleted_at = now() WHERE id = %s", (first_id,))
    conn.commit()

    with conn.cursor() as cur:
        _insert_user(cur, email=email, username=username)
    conn.commit()  # must succeed: partial unique indexes exclude deleted_at IS NOT NULL


def test_permission_seed_matches_rbac_seed_fixture(migrated_conn: psycopg.Connection) -> None:
    """AC: 'Permission seed matches the API contract.'

    Compares the seeded `permissions.code` set against the checked-in
    `candleviewer/auth/rbac_seed.json` fixture (generated from
    `22-api-openapi.yaml` `x-rbac.permissions`; E09-T03 wires the live
    regenerate-and-diff contract test `rbac_vocabulary_single_source`).
    """
    import json

    seed_path = _SERVICES_API_ROOT / "candleviewer" / "auth" / "rbac_seed.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    expected_codes = {p["code"] for p in seed["permissions"]}

    conn = migrated_conn
    with conn.cursor() as cur:
        cur.execute("SELECT code FROM permissions")
        actual_codes = {row[0] for row in cur.fetchall()}
    conn.rollback()

    assert actual_codes == expected_codes


def test_role_permissions_match_openapi_x_permissions(
    migrated_conn: psycopg.Connection,
) -> None:
    """AC5: RBAC seed matches the single source of truth.

    `docs/plan/22-api-openapi.yaml` `x-permissions` is the contract (per its own
    comment). This directly parses that block and compares it against the
    seeded `role_permissions` for `manager` and `viewer` (owner is `"*"` i.e.
    every permission, checked separately) so drift between the migration seed
    and the API contract fails this ticket's gate rather than only a
    fixture-vs-fixture comparison. A stronger generator-based check lands in
    E09-T03 (`rbac_vocabulary_single_source`); this is the interim real check.
    """
    import re

    openapi_path = _SERVICES_API_ROOT.parent.parent / "docs" / "plan" / "22-api-openapi.yaml"
    text = openapi_path.read_text(encoding="utf-8")
    block_match = re.search(r"x-permissions:\n(.*?)\npaths:", text, re.S)
    assert block_match is not None, "x-permissions block not found in 22-api-openapi.yaml"
    block = block_match.group(1)

    def _role_codes(role: str) -> set[str]:
        role_match = re.search(role + r":\n((?:    - .*\n)+)", block)
        assert role_match is not None, f"role {role!r} not found in x-permissions"
        return {line.strip("- ").strip() for line in role_match.group(1).splitlines()}

    expected_manager = _role_codes("manager")
    expected_viewer = _role_codes("viewer")

    conn = migrated_conn
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.code FROM role_permissions rp "
            "JOIN roles r ON r.id = rp.role_id "
            "JOIN permissions p ON p.id = rp.permission_id "
            "WHERE r.name = %s",
            ("manager",),
        )
        actual_manager = {row[0] for row in cur.fetchall()}

        cur.execute(
            "SELECT p.code FROM role_permissions rp "
            "JOIN roles r ON r.id = rp.role_id "
            "JOIN permissions p ON p.id = rp.permission_id "
            "WHERE r.name = %s",
            ("viewer",),
        )
        actual_viewer = {row[0] for row in cur.fetchall()}
    conn.rollback()

    assert actual_manager == expected_manager
    assert actual_viewer == expected_viewer
