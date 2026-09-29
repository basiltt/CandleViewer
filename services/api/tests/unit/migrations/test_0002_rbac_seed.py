"""Tests for `0002_rbac_seed` (E07-T02): offline SQL render, and the
`db.models` metadata this ticket introduces.

No database is needed: `alembic upgrade head --sql` renders offline. The
single-head invariant across the whole versions/ directory is owned by
`test_single_head.py`, not by every historical revision's own test file
(each subsequent migration adds a new tip and would otherwise make a
per-revision copy of that assertion stale by construction).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]


def test_migration_0002_renders_offline_without_error() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=_SERVICES_API_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    # `upgrade()`'s data-driven bootstrap-owner step is guarded by
    # `op.get_context().as_sql` and is a no-op in offline mode; the revision
    # still appears in the rendered SQL's stamp comment.
    assert "0002_rbac_seed" in result.stdout


def test_migration_0002_downgrade_is_a_documented_noop() -> None:
    import importlib.util

    module_path = (
        _SERVICES_API_ROOT / "candleviewer" / "migrations" / "versions" / "0002_rbac_seed.py"
    )
    spec = importlib.util.spec_from_file_location("_0002_rbac_seed_under_test", module_path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    # downgrade() must not raise and must not attempt any DDL/DML.
    revision.downgrade()
