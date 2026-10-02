"""`0010_user_invites`: models mirror the SQL and the downgrade drops the table."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]


def test_user_invites_columns_and_secret_nullability() -> None:
    cols = models.user_invites.columns
    assert cols["token_hash"].nullable is False
    assert cols["pending_password_hash"].nullable is True
    assert cols["consumed_at"].nullable is True


def _render(*args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args, "--sql"],
        cwd=_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_rendered_sql_creates_and_drops_user_invites() -> None:
    assert "CREATE TABLE user_invites" in _render("upgrade", "head")
    down = _render("downgrade", "0010_user_invites:0009_sessions_step_up_state")
    assert "DROP TABLE user_invites" in down
