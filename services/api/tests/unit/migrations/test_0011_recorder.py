"""`0011_recorder`: models mirror the SQL, seed/grants render, downgrade drops all (E16-T01)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]


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


def _checks(table: object) -> set[str]:
    return {
        str(c.name)
        for c in table.constraints  # type: ignore[attr-defined]
        if c.__class__.__name__ == "CheckConstraint"
    }


def test_recorder_check_constraint_names_match_sql() -> None:
    assert _checks(models.recorded_symbols) == {
        f"ck_recorded_symbols_{n}"
        for n in ("rs_depth", "rs_retention", "rs_streams", "rs_autoshape")
    }
    assert _checks(models.recording_sessions) == {
        f"ck_recording_sessions_{n}" for n in ("recs_counts", "recs_window")
    }
    assert _checks(models.recording_gaps) == {
        f"ck_recording_gaps_{n}" for n in ("rg_window", "rg_cause")
    }
    assert _checks(models.retention_policies) == {
        f"ck_retention_policies_{n}"
        for n in ("rp_scope", "rp_symshape", "rp_days", "rp_downshape", "rp_disk")
    }


def test_recorder_index_names_match_sql() -> None:
    names = {
        ix.name
        for t in (
            models.recorded_symbols,
            models.recording_sessions,
            models.recording_gaps,
            models.retention_policies,
        )
        for ix in t.indexes
    }
    assert names == {
        "ux_rs_symbol",
        "ix_rs_pinned",
        "ix_rs_auto",
        "ix_recs_symbol_time",
        "ix_recs_live",
        "ix_rg_symbol_time",
        "ux_rp_default",
        "ux_rp_symbol",
    }


def test_upgrade_sql_creates_tables_enums_seed_and_revokes_delete() -> None:
    sql = _render("upgrade", "0010_user_invites:0011_recorder")
    for table in ("recorded_symbols", "recording_sessions", "recording_gaps", "retention_policies"):
        assert f"CREATE TABLE {table}" in sql
    for enum in ("stream_kind", "record_reason", "recording_state", "retention_action"):
        assert f"CREATE TYPE {enum} AS ENUM" in sql
    assert "('trades', 30)" in sql and "('orderbook_delta', 7)" in sql
    assert "REVOKE DELETE, TRUNCATE ON recording_gaps FROM cv_app" in sql
    assert "REVOKE DELETE, TRUNCATE ON recording_sessions FROM cv_app" in sql


def test_downgrade_sql_drops_tables_and_enums() -> None:
    sql = _render("downgrade", "0011_recorder:0010_user_invites")
    for obj in (
        "TABLE IF EXISTS retention_policies",
        "TABLE IF EXISTS recording_gaps",
        "TABLE IF EXISTS recording_sessions",
        "TABLE IF EXISTS recorded_symbols",
        "TYPE IF EXISTS stream_kind",
        "TYPE IF EXISTS retention_action",
    ):
        assert f"DROP {obj}" in sql
