"""Regression test for QA bug #1589 (E07-T02-B2): `candleviewer.db.models`
must mirror the DDL shape actually emitted by revision
`0001_identity_rbac_sessions_mfa`'s hand-written SQL, or `alembic check`
(CI-MIG-002, the autogenerate-drift gate) fails on the first real run.

This does not require a live Postgres: `alembic upgrade head --sql` renders
the migration's SQL offline, and this test greps the *rendered SQL string*
(not the model) for the drift points from the bug report, then asserts the
`db.models` metadata declares the matching shape. It does not replace
`alembic check` (still the definitive gate) but catches the specific
regressions named in #1589 without docker.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import Text as CoreText
from sqlalchemy.dialects.postgresql import DOMAIN

from candleviewer.db import models

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]


def _render_sql() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=_SERVICES_API_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_text_columns_in_sql_are_modelled_as_text_not_varchar() -> None:
    """`TEXT` columns in the raw SQL (e.g. mfa_challenges.purpose,
    mfa_methods.label/secret_key_ref, permissions.code/domain/description,
    roles.description, sessions.revoked_reason) must not be `String()` in the
    model — `String()` autogenerates as `VARCHAR`, which drifts from `TEXT`.
    """
    text_columns = [
        (models.mfa_challenges, "purpose"),
        (models.mfa_methods, "label"),
        (models.mfa_methods, "secret_key_ref"),
        (models.permissions, "code"),
        (models.permissions, "domain"),
        (models.permissions, "description"),
        (models.roles, "description"),
        (models.sessions, "revoked_reason"),
    ]
    for table, column_name in text_columns:
        column = table.columns[column_name]
        rendered = str(column.type).upper()
        assert rendered == "TEXT", (
            f"{table.name}.{column_name} renders as {rendered!r}, expected TEXT "
            "(drift vs. the raw-SQL `text` column in 0001)"
        )


def test_sha256_hex_columns_are_modelled_as_the_domain_not_a_varchar() -> None:
    """`sessions.refresh_token_hash` / `recovery_codes.code_hash` are the
    `sha256_hex` DOMAIN in SQL; modelling them as `String(64)` autogenerates
    as `character varying(64)`, which `alembic check` reports as drift
    against a `sha256_hex` domain column.
    """
    for table, column_name in (
        (models.sessions, "refresh_token_hash"),
        (models.recovery_codes, "code_hash"),
    ):
        column_type = table.columns[column_name].type
        assert isinstance(column_type, DOMAIN), (
            f"{table.name}.{column_name} is {type(column_type).__name__}, expected "
            "postgresql.DOMAIN('sha256_hex', ...)"
        )
        assert column_type.name == "sha256_hex"
        assert isinstance(column_type.data_type, CoreText)


def test_partial_indexes_from_sql_are_declared_on_the_model() -> None:
    """Every partial/expression index created by the raw SQL in 0001 must
    exist on the corresponding `Table` (with a `postgresql_where` clause),
    or autogenerate proposes to drop it as an "extra" index.
    """
    expected_by_table = {
        "mfa_challenges": {"ix_mfa_ch_user_open"},
        "mfa_methods": {"ix_mfa_user_active", "ux_mfa_webauthn_cred"},
        "recovery_codes": {"ix_recovery_unused"},
        "role_permissions": {"ix_role_permissions_perm"},
        "user_roles": {"ix_user_roles_role"},
        "users": {"ux_users_email", "ux_users_username", "ix_users_status"},
        "sessions": {"ix_sessions_user_live", "ix_sessions_expiry"},
        "user_account_access": {"ix_uaa_account", "ix_uaa_frozen"},
    }
    for table_name, expected_index_names in expected_by_table.items():
        table = models.metadata.tables[table_name]
        actual_index_names = {ix.name for ix in table.indexes}
        missing = expected_index_names - actual_index_names
        assert not missing, f"{table_name} is missing indexes {missing} present in 0001's SQL"


def test_auto_named_unique_constraints_match_postgres_default_naming() -> None:
    """0001's SQL uses bare `UNIQUE`/`UNIQUE (...)` clauses on `permissions`,
    `roles` and `recovery_codes`, which Postgres auto-names
    `<table>_<col(s)>_key`. The model must use the *same* name (or autogenerate
    proposes to rename the constraint, which `alembic check` reports as drift).
    """
    expected = {
        "permissions": "permissions_code_key",
        "roles": "roles_name_key",
        "recovery_codes": "recovery_codes_user_id_code_hash_key",
        "sessions_rotation": "sessions_rotation_next_session_id_key",
        "sessions": "sessions_refresh_token_hash_key",
    }
    for table_name, expected_name in expected.items():
        table = models.metadata.tables[table_name]
        actual_names = {
            uc.name for uc in table.constraints if uc.__class__.__name__ == "UniqueConstraint"
        }
        assert expected_name in actual_names, (
            f"{table_name} unique constraint names {actual_names} do not include "
            f"{expected_name!r} (Postgres' auto-generated name for 0001's bare UNIQUE)"
        )


def test_rendered_sql_still_creates_the_domain_and_text_columns() -> None:
    """Sanity check binding the above assertions to the actual migration SQL:
    if 0001 is ever edited (it must not be, C-5.4, but belt-and-braces), this
    fails loudly instead of the model and the SQL silently diverging further.
    """
    sql = _render_sql()
    assert "CREATE DOMAIN sha256_hex AS char(64)" in sql
    assert "refresh_token_hash sha256_hex NOT NULL" in sql
    assert "code_hash  sha256_hex NOT NULL" in sql or "code_hash sha256_hex NOT NULL" in sql
