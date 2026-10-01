"""`0009_sessions_step_up_state`: `candleviewer.db.models` must mirror the
hand-written SQL (columns, defaults, CHECK) and the downgrade must reverse it."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from candleviewer.db import models

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]


def test_sessions_has_step_up_columns() -> None:
    cols = models.sessions.columns
    assert cols["step_up_elevations"].nullable is False
    assert cols["step_up_failures"].nullable is False
    assert str(cols["step_up_failures"].server_default.arg) == "0"  # type: ignore[union-attr]  # server_default is set
    assert cols["readonly_until"].nullable is True


def test_sessions_has_step_up_failures_range_check() -> None:
    names = {c.name for c in models.sessions.constraints}
    assert any(n and n.endswith("sessions_step_up_failures_range") for n in names)


def test_rendered_sql_adds_step_up_columns_and_downgrade_reverses_it() -> None:
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
    assert "ADD COLUMN step_up_elevations jsonb NOT NULL DEFAULT '{}'::jsonb" in up
    assert "ADD COLUMN readonly_until timestamptz" in up
    down = render("downgrade", "0009_sessions_step_up_state:0008_system_events")
    assert "DROP COLUMN step_up_elevations" in down
    assert "DROP COLUMN readonly_until" in down
