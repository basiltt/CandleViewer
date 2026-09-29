"""`0003_audit_log`: single head, offline render, and the DDL invariants the
ticket requires (trigger chain, append-only trigger, REVOKE, checkpoints)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

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
        "REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM cv_app",
        "REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM cv_ro",
        "CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON audit_log",
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate()",
        "PERFORM pg_advisory_xact_lock(hashtext('audit_log'))",
        "record_id     uuid NOT NULL UNIQUE",
        "audit_field(NEW.prev_hash)",
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


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar(self) -> int:
        return self._value


class _FakeBind:
    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts

    def exec_driver_sql(self, sql: str) -> _FakeResult:
        table = sql.rsplit(" ", 1)[-1]
        return _FakeResult(self._counts[table])


class _FakeOp:
    def __init__(self, counts: dict[str, int]) -> None:
        self._bind = _FakeBind(counts)
        self.executed: list[str] = []

    def get_bind(self) -> _FakeBind:
        return self._bind

    def execute(self, sql: Any) -> None:
        self.executed.append(str(sql))


@pytest.mark.parametrize(
    "counts",
    [{"audit_log": 3, "audit_checkpoints": 0}, {"audit_log": 0, "audit_checkpoints": 1}],
)
def test_0003_downgrade_refuses_when_audit_history_present(
    counts: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load()
    fake = _FakeOp(counts)
    monkeypatch.setattr(mod, "op", fake)
    with pytest.raises(RuntimeError, match=r"C-5.7"):
        mod.downgrade()
    assert fake.executed == []


def test_0003_downgrade_proceeds_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    fake = _FakeOp({"audit_log": 0, "audit_checkpoints": 0})
    monkeypatch.setattr(mod, "op", fake)
    mod.downgrade()
    assert fake.executed == [mod._DOWNGRADE_SQL]


def test_0003_audit_checkpoints_are_append_only() -> None:
    """PR #1561 N3: checkpoints get the same mutation/truncate guards and REVOKEs."""
    mod = _load()
    sql = mod._UPGRADE_SQL
    for needle in (
        "CREATE TRIGGER trg_audit_ckpt_append BEFORE UPDATE OR DELETE ON audit_checkpoints",
        "CREATE TRIGGER trg_audit_ckpt_no_truncate BEFORE TRUNCATE ON audit_checkpoints",
        "REVOKE UPDATE, DELETE, TRUNCATE ON audit_checkpoints FROM cv_app",
        "REVOKE UPDATE, DELETE, TRUNCATE ON audit_checkpoints FROM cv_ro",
    ):
        assert needle in sql, needle
    assert sql.index("CREATE TABLE audit_checkpoints") < sql.index("trg_audit_ckpt_append")
    assert "DROP TRIGGER IF EXISTS trg_audit_ckpt_append ON audit_checkpoints" in (
        mod._DOWNGRADE_SQL
    )
