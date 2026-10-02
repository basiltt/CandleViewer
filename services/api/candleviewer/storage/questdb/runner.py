"""Idempotent QuestDB DDL runner keyed on `_cv_migrations` (E07-T03).

`docs/plan/21-database-schema.md` Sec.9.1: "QuestDB DDL lives in
`backend/db/questdb/NNNN_*.sql`, applied by a small idempotent runner keyed
on a `_cv_migrations` table inside QuestDB." Run at boot by
`StorageService.start()` — never by a request handler.

Also performs the column-drift guard: compares the live `tables()`/
`table_columns()` listing against the parsed DDL files and raises
`StorageSchemaDrift` rather than let a write path touch a mismatched shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import structlog

from candleviewer.storage.errors import StorageSchemaDrift
from candleviewer.storage.questdb.ddl import TableDef, parse_ddl_dir

logger = structlog.get_logger(__name__)

_MIGRATIONS_TABLE = "_cv_migrations"

_CREATE_MIGRATIONS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} (
  ts          TIMESTAMP,
  filename    SYMBOL CAPACITY 256 CACHE,
  applied_at  TIMESTAMP
) TIMESTAMP(ts) PARTITION BY YEAR WAL
  DEDUP UPSERT KEYS(ts, filename);
"""


class QuestDbExecutor(Protocol):
    """The minimal surface the runner needs from a PGWire connection —
    kept as a `Protocol` so tests can supply an in-memory fake instead of a
    real `asyncpg` connection (no docker available for unit tests)."""

    async def execute(self, sql: str, *args: object) -> None: ...

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]: ...


async def applied_migrations(executor: QuestDbExecutor) -> set[str]:
    """Filenames already recorded in `_cv_migrations`."""
    await executor.execute(_CREATE_MIGRATIONS_TABLE)
    # `_MIGRATIONS_TABLE` is a module constant, never user input; noqa'd
    # rather than parameterised because QuestDB/Postgres bind params are
    # values, not identifiers.
    # nosemgrep: cv-storage-sql-construction -- module-constant identifier
    rows = await executor.fetch(
        f"SELECT filename FROM {_MIGRATIONS_TABLE}"  # noqa: S608  # nosec B608 - module constant identifier, not user input
    )
    return {str(row["filename"]) for row in rows}


async def run_migrations(executor: QuestDbExecutor, ddl_dir: Path) -> list[str]:
    """Apply every `NNNN_*.sql` file not already recorded, in filename order.

    Returns the list of filenames newly applied this call (empty on a
    no-op second run — the idempotency acceptance criterion). Each file's
    statements are executed individually (`CREATE TABLE IF NOT EXISTS` makes
    per-statement idempotency redundant but harmless) and the file is
    recorded in `_cv_migrations` only after every statement in it succeeds.
    """
    already = await applied_migrations(executor)
    newly_applied: list[str] = []
    # `Path.glob` on a small local `backend/db/questdb/` directory at boot is
    # not a hot-path blocking call in the C-2.18 sense; kept sync for
    # simplicity, run once per process start.
    sql_paths = sorted(ddl_dir.glob("*.sql"))  # noqa: ASYNC240
    for sql_path in sql_paths:
        if sql_path.name in already:
            continue
        for table in parse_ddl_file_statements(sql_path):
            await executor.execute(table)
        await executor.execute(
            # `_MIGRATIONS_TABLE` is a module constant; `$1` binds the value.
            f"INSERT INTO {_MIGRATIONS_TABLE} (ts, filename, applied_at) "  # noqa: S608  # nosec B608 - module constant identifier, not user input
            "VALUES (now(), $1, now())",
            sql_path.name,
        )
        newly_applied.append(sql_path.name)
        logger.info("questdb_migration_applied", filename=sql_path.name)
    return newly_applied


def parse_ddl_file_statements(path: Path) -> list[str]:
    """Re-read a `.sql` file and return each `CREATE TABLE ... ;` statement
    verbatim (not the parsed `TableDef`) so the runner executes exactly what
    is on disk, byte for byte, rather than a reconstruction.

    `--` line comments are stripped before the paren-depth scan below: a
    comment containing an unbalanced `(` or `)` (e.g. a prose aside spanning
    lines) would otherwise desynchronise the depth counter and corrupt
    statement boundaries sent to QuestDB.
    """
    stripped_lines = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        idx = line.find("--")
        stripped_lines.append(line if idx == -1 else line[:idx] + "\n")
    text = "".join(stripped_lines)
    statements: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        current.append(char)
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == ";" and depth == 0:
            stmt = "".join(current).strip()
            if stmt and not stmt.startswith("--"):
                statements.append(stmt)
            current = []
    return statements


async def assert_no_schema_drift(executor: QuestDbExecutor, ddl_dir: Path) -> None:
    """Compare the live column set of every DDL-defined table against the
    parsed `.sql` files; raise `StorageSchemaDrift` on any mismatch.

    Uses `table_columns('<name>')`, QuestDB's introspection function, rather
    than string-matching `tables()` output.
    """
    expected = parse_ddl_dir(ddl_dir)
    for table in expected:
        # `table.name` comes from parsing our own trusted `.sql` files, never
        # from user input. `column` is a SQL keyword in QuestDB and must be
        # double-quoted when referenced as an identifier in the SELECT list.
        query = f"SELECT \"column\" FROM table_columns('{table.name}')"  # noqa: S608  # nosec B608 - table.name from trusted parsed DDL files, not user input
        rows = await executor.fetch(query)
        live_columns = {str(row["column"]).lower() for row in rows}
        expected_columns = set(table.columns)
        if live_columns != expected_columns:
            missing = expected_columns - live_columns
            extra = live_columns - expected_columns
            raise StorageSchemaDrift(
                f"questdb table {table.name!r} column drift: "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )


def expected_tables(ddl_dir: Path) -> list[TableDef]:
    """Convenience re-export for callers (e.g. the reader's query-builder
    lint tests) that want the parsed DDL without importing `ddl` directly."""
    return parse_ddl_dir(ddl_dir)
