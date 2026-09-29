"""Unit tests for `candleviewer.storage.questdb.runner` (E07-T03).

Covers DDL-runner idempotency (second run applies nothing) and the
column-drift guard, against a fake in-memory `QuestDbExecutor` — no docker
needed for these unit-level behaviours (integration tests exercise the real
engine separately).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.storage.errors import StorageSchemaDrift
from candleviewer.storage.questdb.ddl import parse_ddl_dir
from candleviewer.storage.questdb.runner import (
    applied_migrations,
    assert_no_schema_drift,
    run_migrations,
)

DDL_DIR = Path(__file__).resolve().parents[6] / "backend" / "db" / "questdb"


class _FakeExecutor:
    """An in-memory stand-in for a QuestDB PGWire connection.

    Tracks executed DDL statements and a `_cv_migrations` row set in plain
    Python collections, and derives `table_columns()` responses from the
    same DDL files this module parses — so the drift test can perturb one
    column and see the guard fire.
    """

    def __init__(self) -> None:
        self.executed: list[str] = []
        self._migrations: set[str] = set()
        self._table_columns: dict[str, set[str]] = {
            t.name: set(t.columns) for t in parse_ddl_dir(DDL_DIR)
        }

    async def execute(self, sql: str, *args: object) -> None:
        self.executed.append(sql)
        if sql.strip().upper().startswith("INSERT INTO _CV_MIGRATIONS"):
            self._migrations.add(str(args[0]))

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        if "_cv_migrations" in sql:
            return [{"filename": name} for name in sorted(self._migrations)]
        if "table_columns" in sql:
            # sql looks like: SELECT column FROM table_columns('trades')
            name = sql.split("'")[1]
            return [{"column": col} for col in sorted(self._table_columns.get(name, set()))]
        return []


@pytest.mark.asyncio
async def test_run_migrations_applies_every_file_on_first_run() -> None:
    executor = _FakeExecutor()
    applied = await run_migrations(executor, DDL_DIR)
    assert applied == ["0001_core_tables.sql", "0002_footprint_cells.sql"]


@pytest.mark.asyncio
async def test_run_migrations_second_run_applies_nothing() -> None:
    executor = _FakeExecutor()
    await run_migrations(executor, DDL_DIR)
    executor.executed.clear()
    applied_second = await run_migrations(executor, DDL_DIR)
    assert applied_second == []
    # No *data* table DDL re-issued on the idempotent second run (only the
    # always-idempotent `_cv_migrations` bootstrap statement, which itself
    # contains `CREATE TABLE`, runs again).
    assert not any(
        "CREATE TABLE" in stmt.upper() and "_CV_MIGRATIONS" not in stmt.upper()
        for stmt in executor.executed
    )


@pytest.mark.asyncio
async def test_applied_migrations_reflects_recorded_filenames() -> None:
    executor = _FakeExecutor()
    await run_migrations(executor, DDL_DIR)
    names = await applied_migrations(executor)
    assert names == {"0001_core_tables.sql", "0002_footprint_cells.sql"}


@pytest.mark.asyncio
async def test_assert_no_schema_drift_passes_when_columns_match() -> None:
    executor = _FakeExecutor()
    await assert_no_schema_drift(executor, DDL_DIR)  # no raise


@pytest.mark.asyncio
async def test_assert_no_schema_drift_raises_on_missing_column() -> None:
    executor = _FakeExecutor()
    executor._table_columns["trades"].discard("notional")
    with pytest.raises(StorageSchemaDrift, match="trades"):
        await assert_no_schema_drift(executor, DDL_DIR)


@pytest.mark.asyncio
async def test_assert_no_schema_drift_raises_on_extra_column() -> None:
    executor = _FakeExecutor()
    executor._table_columns["trades"].add("unexpected_column")
    with pytest.raises(StorageSchemaDrift, match="extra"):
        await assert_no_schema_drift(executor, DDL_DIR)
