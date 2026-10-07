"""DDL parsing helpers for the QuestDB hot tier (E07-T03).

Parses `backend/db/questdb/*.sql` into a small, structured representation the
migration runner and the column-drift guard both use. Deliberately minimal:
only the shapes the DDL files actually use (`CREATE TABLE IF NOT EXISTS`,
column defs, `TIMESTAMP(...)`, `PARTITION BY`, `WAL`, `DEDUP UPSERT KEYS`).
This is not a general SQL parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

_CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(?P<name>\w+)\s*\((?P<body>.*?)\)\s*"
    r"TIMESTAMP\((?P<ts_col>\w+)\)\s*PARTITION\s+BY\s+(?P<partition>DAY|HOUR|MONTH|YEAR)\s+WAL"
    r"(?:\s*DEDUP\s+UPSERT\s+KEYS\s*\((?P<dedup>[^)]*)\))?\s*;",
    re.IGNORECASE | re.DOTALL,
)

#: A column definition line: `name TYPE [CAPACITY n] [CACHE] -- comment`.
_COLUMN_RE = re.compile(
    r"^\s*(?P<name>\w+)\s+(?P<type>[A-Z0-9_]+)(?:\s+CAPACITY\s+\d+)?(?:\s+CACHE)?\s*$",
    re.IGNORECASE,
)


#: `ALTER TABLE t ADD COLUMN IF NOT EXISTS name TYPE [CAPACITY n] [CACHE];` (additive batches).
_ALTER_ADD_RE = re.compile(
    r"ALTER\s+TABLE\s+(?P<table>\w+)\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<col>\w+)\s+[A-Z0-9_]+(?:\s+CAPACITY\s+\d+)?(?:\s+CACHE)?\s*;",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TableDef:
    """One parsed `CREATE TABLE` statement."""

    name: str
    columns: tuple[str, ...]
    ts_col: str
    partition_by: str
    dedup_keys: tuple[str, ...]
    source_file: str


def _strip_comments(sql_body: str) -> str:
    """Remove `-- ...` line comments so column parsing never sees them."""
    lines = []
    for line in sql_body.splitlines():
        idx = line.find("--")
        lines.append(line if idx == -1 else line[:idx])
    return "\n".join(lines)


def _split_columns(body: str) -> list[str]:
    """Split a `CREATE TABLE` body on top-level commas.

    No column definition in these DDL files contains a comma (no `DECIMAL(p,s)`
    etc.), so a naive split is correct and avoids a bracket-depth parser.
    """
    return [part.strip() for part in body.split(",") if part.strip()]


def parse_ddl_file(path: Path) -> list[TableDef]:
    """Parse every `CREATE TABLE` statement in one `.sql` file."""
    text = path.read_text(encoding="utf-8")
    tables: list[TableDef] = []
    for match in _CREATE_RE.finditer(text):
        body = _strip_comments(match.group("body"))
        columns: list[str] = []
        for raw_col in _split_columns(body):
            # `open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE` lands as one
            # token after comma-splitting collapses the intentional multi-decl
            # line in bars_* tables; `_split_columns` already separated those
            # on commas, so each `raw_col` here is a single `name TYPE` pair.
            col_match = _COLUMN_RE.match(raw_col)
            if col_match:
                columns.append(col_match.group("name").lower())
        dedup_raw = match.group("dedup") or ""
        dedup_keys = tuple(k.strip().lower() for k in dedup_raw.split(",") if k.strip())
        tables.append(
            TableDef(
                name=match.group("name").lower(),
                columns=tuple(columns),
                ts_col=match.group("ts_col").lower(),
                partition_by=match.group("partition").upper(),
                dedup_keys=dedup_keys,
                source_file=path.name,
            )
        )
    return tables


def parse_ddl_dir(dir_path: Path) -> list[TableDef]:
    """Parse every `NNNN_*.sql` file in `dir_path`, in filename order (the
    order they are applied — `backend/db/questdb/NNNN_*.sql` naming, per
    `docs/plan/21-database-schema.md` Sec.9.1)."""
    tables: list[TableDef] = []
    for sql_path in sorted(dir_path.glob("*.sql")):
        tables.extend(parse_ddl_file(sql_path))
    return _apply_alters(tables, dir_path)


def _apply_alters(tables: list[TableDef], dir_path: Path) -> list[TableDef]:
    """Fold `ALTER TABLE ... ADD COLUMN` statements (applied in filename order) into the
    `TableDef`s they extend, so the drift guard sees the live column set."""
    by_name = {t.name: t for t in tables}
    for sql_path in sorted(dir_path.glob("*.sql")):
        text = "\n".join(
            line.split("--", 1)[0] for line in sql_path.read_text(encoding="utf-8").splitlines()
        )
        for m in _ALTER_ADD_RE.finditer(text):
            table = by_name.get(m.group("table").lower())
            col = m.group("col").lower()
            if table is not None and col not in table.columns:
                by_name[table.name] = replace(table, columns=(*table.columns, col))
    return [by_name[t.name] for t in tables]
