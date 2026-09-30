"""Regression test (mirrors `test_0004_models_match_sql.py`): `candleviewer.db.models`
must mirror the DDL emitted by revision `0005_mfa_totp_replay_guard`'s hand-written
SQL — the nullable `mfa_methods.last_accepted_time_step` bigint column and its
comment — or `alembic check` (CI-MIG-002) reports drift.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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


def test_mfa_methods_has_last_accepted_time_step_column() -> None:
    table = models.mfa_methods
    assert "last_accepted_time_step" in table.columns
    column = table.columns["last_accepted_time_step"]
    assert column.nullable is True
    assert column.type.python_type is int


def test_mfa_methods_last_accepted_time_step_comment_matches_sql() -> None:
    assert models.mfa_methods.columns["last_accepted_time_step"].comment == (
        "TOTP replay guard (E09-S02, migration 0005): highest accepted "
        "RFC 6238 time-step; NULL means no code accepted yet."
    )


def test_rendered_sql_still_adds_the_replay_guard_column() -> None:
    """Sanity check binding the assertions above to the actual migration SQL:
    if 0005 is ever edited before merge, this fails loudly instead of the
    model and the SQL silently diverging further."""
    sql = _render_sql()
    for needle in (
        "ALTER TABLE mfa_methods ADD COLUMN last_accepted_time_step bigint",
        "COMMENT ON COLUMN mfa_methods.last_accepted_time_step",
    ):
        assert needle in sql, needle
