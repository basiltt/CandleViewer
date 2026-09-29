"""`0003_audit_log`: single head, offline render, and the DDL invariants the
ticket requires (trigger chain, append-only trigger, REVOKE, checkpoints)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[3]


def _load() -> ModuleType:
    path = _ROOT / "candleviewer" / "migrations" / "versions" / "0003_audit_log.py"
    spec = importlib.util.spec_from_file_location("_0003_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_0003_parents_0002_and_is_the_single_head() -> None:
    mod = _load()
    assert mod.down_revision == "0002_rbac_seed"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1 and "0003_audit_log" in heads[0]


def test_0003_renders_offline() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE audit_log" in result.stdout


def test_0003_ddl_matches_schema_doc_invariants() -> None:
    sql = _load()._UPGRADE_SQL
    for needle in (
        "CREATE TRIGGER trg_audit_chain BEFORE INSERT ON audit_log",
        "CREATE TRIGGER trg_audit_append BEFORE UPDATE OR DELETE ON audit_log",
        "REVOKE UPDATE, DELETE ON audit_log FROM cv_app",
        "REVOKE UPDATE, DELETE ON audit_log FROM cv_ro",
        "COALESCE(last_hash, repeat('0',64))",
        "au_action_fmt",
        "CREATE TABLE audit_checkpoints",
    ):
        assert needle in sql, needle
    for idx in ("ix_audit_time", "ix_audit_actor", "ix_audit_action", "ix_audit_object"):
        assert f"CREATE INDEX {idx}" in sql
    assert "GRANT UPDATE" not in sql and "GRANT DELETE" not in sql


def test_0003_downgrade_drops_everything_it_created() -> None:
    sql = _load()._DOWNGRADE_SQL
    for obj in ("audit_checkpoints", "audit_log", "audit_chain()", "forbid_mutation()"):
        assert obj in sql
