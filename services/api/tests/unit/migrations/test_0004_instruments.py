"""Tests for `0004_instruments` (E08-S01): parents `0003_audit_log`, offline
SQL render, and a documented downgrade check. The single-head invariant
across the whole `versions/` directory is owned by the tip's own test (see
`test_single_head.py`) rather than duplicated in every historical revision's
test file.

No database is needed: `alembic upgrade head --sql` renders offline.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]


def test_0004_parents_0003_audit_log() -> None:
    import importlib.util

    module_path = (
        _SERVICES_API_ROOT / "candleviewer" / "migrations" / "versions" / "0004_instruments.py"
    )
    spec = importlib.util.spec_from_file_location("_0004_instruments_under_test", module_path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    assert revision.revision == "0004_instruments"
    assert revision.down_revision == "0003_audit_log"


def test_migration_0004_renders_offline_without_error() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=_SERVICES_API_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE instruments" in result.stdout
    assert "CREATE TABLE instrument_versions" in result.stdout
    assert "0004_instruments" in result.stdout


def test_migration_0004_downgrade_drops_both_tables() -> None:
    import importlib.util

    module_path = (
        _SERVICES_API_ROOT / "candleviewer" / "migrations" / "versions" / "0004_instruments.py"
    )
    spec = importlib.util.spec_from_file_location("_0004_instruments_under_test", module_path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    assert "DROP TABLE IF EXISTS instrument_versions" in revision._DOWNGRADE_SQL
    assert "DROP TABLE IF EXISTS instruments" in revision._DOWNGRADE_SQL
    # instruments dropped after instrument_versions (FK direction).
    iv_pos = revision._DOWNGRADE_SQL.index("DROP TABLE IF EXISTS instrument_versions")
    inst_pos = revision._DOWNGRADE_SQL.index("DROP TABLE IF EXISTS instruments")
    assert iv_pos < inst_pos
