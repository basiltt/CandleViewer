"""Unit tests for `tools/ci/run_previous_release_upgrade.py` (CI-MIG-004).

Only the no-op path (no release tag cut yet) is exercised without a real
Postgres; the restore/upgrade path needs `psql` + a live DB and is covered
by the `migrations` CI job directly (it runs against the service container).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "api"))

from tools.ci.run_previous_release_upgrade import _latest_snapshot, _to_psql_dsn, main

_SERVICES_API_ROOT = Path(__file__).resolve().parents[2] / "services" / "api"


def test_latest_snapshot_returns_none_when_dir_missing(tmp_path: Path) -> None:
    assert _latest_snapshot(tmp_path / "nope") is None


def test_latest_snapshot_returns_none_when_dir_empty(tmp_path: Path) -> None:
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    assert _latest_snapshot(schema_dir) is None


def test_latest_snapshot_picks_highest_sorted_name(tmp_path: Path) -> None:
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "v0.1.0.sql").write_text("-- old", encoding="utf-8")
    (schema_dir / "v0.2.0.sql").write_text("-- new", encoding="utf-8")
    assert _latest_snapshot(schema_dir).name == "v0.2.0.sql"


def test_main_exits_zero_when_no_snapshot_exists(tmp_path: Path) -> None:
    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--dsn",
            "postgresql+asyncpg://cv:cv@localhost:5432/candleviewer",
        ]
    )
    assert exit_code == 0


def test_main_prints_notice_when_no_snapshot_exists(tmp_path: Path, capsys) -> None:
    main(
        [
            "--root",
            str(tmp_path),
            "--dsn",
            "postgresql+asyncpg://cv:cv@localhost:5432/candleviewer",
        ]
    )
    out = capsys.readouterr().out
    assert "::notice::" in out
    assert "CI-MIG-004" in out


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql+asyncpg://cv:cv@localhost:5432/candleviewer",
        "postgresql+psycopg://cv:cv@localhost:5432/candleviewer",
        "postgresql+psycopg2://cv:cv@localhost:5432/candleviewer",
        "postgresql://cv:cv@localhost:5432/candleviewer",
    ],
)
def test_to_psql_dsn_strips_any_driver_suffix(dsn: str) -> None:
    assert _to_psql_dsn(dsn, _SERVICES_API_ROOT) == "postgresql://cv:cv@localhost:5432/candleviewer"
