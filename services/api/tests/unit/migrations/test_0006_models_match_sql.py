"""`0006_sessions_idle_timeout`: `candleviewer.db.models` must mirror the hand-written
SQL (column, default, range CHECK) or `alembic check` (CI-MIG-002) reports drift."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from candleviewer.db import models

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]


def test_sessions_has_idle_timeout_column_with_default() -> None:
    column = models.sessions.columns["idle_timeout_s"]
    assert column.nullable is False
    assert column.type.python_type is int
    assert str(column.server_default.arg) == "900"  # type: ignore[union-attr]


def test_sessions_has_idle_timeout_range_check() -> None:
    names = {c.name for c in models.sessions.constraints}
    assert any(n and n.endswith("sessions_idle_timeout_range") for n in names)


def test_rendered_sql_adds_idle_timeout_and_downgrade_reverses_it() -> None:
    def render(*args: str) -> str:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", *args, "--sql"],
            cwd=_SERVICES_API_ROOT,
            env={**os.environ},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    up = render("upgrade", "head")
    assert "ALTER TABLE sessions ADD COLUMN idle_timeout_s integer NOT NULL DEFAULT 900" in up
    down = render("downgrade", "0006_sessions_idle_timeout:0005_mfa_totp_replay_guard")
    assert "ALTER TABLE sessions DROP COLUMN idle_timeout_s" in down
