"""Regression test for the 0001 migration's jsonb-default bind-param bug.

`op.execute(str)` wraps the SQL in `sqlalchemy.text()`, which treats a bare
`:name` as a bind parameter placeholder. The `password_algo_params` column's
DEFAULT `'{"m":65536,"t":3,"p":4}'::jsonb` literal contains `:65536`, `:3`,
`:4`, which previously raised
`InvalidRequestError: A value is required for bind parameter '65536'`
during `alembic upgrade --sql` (and therefore during a real upgrade).

This test needs no database: `alembic upgrade head --sql` only renders SQL
offline. It asserts the DEFAULT renders with plain colons and that no
bind-parameter error occurs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]


def test_migration_0001_renders_jsonb_default_without_bind_param_error() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=_SERVICES_API_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "bind parameter" not in result.stderr.lower()
    assert '\'{"m":65536,"t":3,"p":4}\'::jsonb' in result.stdout
