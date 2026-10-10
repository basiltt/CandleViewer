"""Every QuestDB DDL column type is one QuestDB 8.x accepts (#2203 CI: "invalid type").

Docker-free guard. A Postgres-only type (`INTEGER`, `BIGINT`, `TEXT`, ...) or an unsupported
`ADD COLUMN IF NOT EXISTS` (QuestDB 8.1 reads `IF` as the column and `NOT` as its type) fails
only on a real server, and then takes the whole integration suite down with it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DDL_DIR = Path(__file__).resolve().parents[6] / "backend" / "db" / "questdb"

#: QuestDB 8.x column types (https://questdb.io/docs/reference/sql/datatypes/).
QUESTDB_TYPES = frozenset(
    {
        "BOOLEAN", "BYTE", "SHORT", "CHAR", "INT", "LONG", "DATE", "TIMESTAMP", "FLOAT",
        "DOUBLE", "STRING", "VARCHAR", "SYMBOL", "LONG256", "GEOHASH", "UUID", "IPV4",
        "BINARY", "LONG128",
    }
)  # fmt: skip

_COL = re.compile(r"^\s*(\w+|\"[^\"]+\")\s+([A-Za-z0-9_]+)")
_CREATE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\)\s*TIMESTAMP", re.S | re.I)
_ALTER_ADD = re.compile(r"ALTER\s+TABLE\s+\w+\s+ADD\s+COLUMN\s+(.*?);", re.S | re.I)


def _sql(path: Path) -> str:
    return "\n".join(line.split("--", 1)[0] for line in path.read_text("utf-8").splitlines())


def _files() -> list[Path]:
    files = sorted(DDL_DIR.glob("*.sql"))
    assert files
    return files


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_create_table_column_types_are_questdb_types(path: Path) -> None:
    bad: list[str] = []
    for table, body in _CREATE.findall(_sql(path)):
        for raw in body.split(","):
            m = _COL.match(raw)
            if m and m.group(2).upper() not in QUESTDB_TYPES:
                bad.append(f"{table}.{m.group(1)} {m.group(2)}")
    assert bad == []


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_alter_add_column_uses_supported_syntax_and_types(path: Path) -> None:
    for clause in _ALTER_ADD.findall(_sql(path)):
        assert not clause.upper().startswith("IF "), f"{path.name}: ADD COLUMN IF NOT EXISTS"
        parts = clause.split()
        assert parts[1].upper() in QUESTDB_TYPES, f"{path.name}: {clause}"


def test_guard_rejects_postgres_types_and_if_not_exists() -> None:
    assert "BIGINT" not in QUESTDB_TYPES and "INTEGER" not in QUESTDB_TYPES
    m = _ALTER_ADD.search("ALTER TABLE t ADD COLUMN IF NOT EXISTS x LONG;")
    assert m is not None and m.group(1).upper().startswith("IF ")
