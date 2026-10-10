"""Every DDL `SYMBOL` column must be an ILP tag (#2198).

QuestDB rejects an ILP *field* written into an existing SYMBOL column, so a SYMBOL column missing
from `tag_columns` makes the whole line fail on a real server. Docker-free guard.
"""

from __future__ import annotations

from pathlib import Path

from candleviewer.storage.questdb.ddl import parse_ddl_dir
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS

DDL_DIR = Path(__file__).resolve().parents[6] / "backend" / "db" / "questdb"


def test_schema_tag_columns_match_ddl_symbol_columns() -> None:
    tables = {t.name: t for t in parse_ddl_dir(DDL_DIR)}
    mismatches = {}
    for name, schema in ALL_SCHEMAS.items():
        ddl_symbols = set(tables[name].symbol_columns)
        if ddl_symbols != set(schema.tag_columns):
            mismatches[name] = {
                "symbol_not_tag": sorted(ddl_symbols - set(schema.tag_columns)),
                "tag_not_symbol": sorted(set(schema.tag_columns) - ddl_symbols),
            }
    assert mismatches == {}


def test_every_bars_table_is_covered_and_source_is_a_tag() -> None:
    for family in ("time", "tick", "volume", "range", "renko", "delta"):
        assert "source" in ALL_SCHEMAS[f"bars_{family}"].tag_columns
