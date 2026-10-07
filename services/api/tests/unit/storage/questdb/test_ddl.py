"""Unit tests for `candleviewer.storage.questdb.ddl` (E07-T03).

Verifies the parser against the real `backend/db/questdb/*.sql` files —
this is also the drift-detector's dependency, so getting parsing right here
is load-bearing for the schema-drift acceptance criterion.
"""

from __future__ import annotations

from pathlib import Path

from candleviewer.storage.questdb.ddl import parse_ddl_dir, parse_ddl_file

DDL_DIR = Path(__file__).resolve().parents[6] / "backend" / "db" / "questdb"


def test_parse_ddl_dir_finds_all_nineteen_tables() -> None:
    tables = parse_ddl_dir(DDL_DIR)
    names = {t.name for t in tables}
    assert len(tables) == 19
    assert "trades" in names
    assert "bars_time" in names
    assert "engine_metrics" in names


def test_parse_ddl_file_trades_has_expected_dedup_keys() -> None:
    tables = parse_ddl_file(DDL_DIR / "0001_core_tables.sql")
    trades = next(t for t in tables if t.name == "trades")
    assert trades.dedup_keys == ("ts", "symbol", "trade_id")
    assert trades.partition_by == "DAY"
    assert trades.ts_col == "ts"
    assert "trade_id" in trades.columns
    assert "notional" in trades.columns


def test_parse_ddl_file_orderbook_deltas_partitioned_by_hour() -> None:
    tables = parse_ddl_file(DDL_DIR / "0001_core_tables.sql")
    deltas = next(t for t in tables if t.name == "orderbook_deltas")
    assert deltas.partition_by == "HOUR"


def test_parse_ddl_file_engine_metrics_has_no_dedup_keys() -> None:
    tables = parse_ddl_file(DDL_DIR / "0002_footprint_cells.sql")
    metrics = next(t for t in tables if t.name == "engine_metrics")
    assert metrics.dedup_keys == ()


def test_parse_ddl_file_comments_are_stripped_from_columns() -> None:
    tables = parse_ddl_file(DDL_DIR / "0001_core_tables.sql")
    trades = next(t for t in tables if t.name == "trades")
    # No comment fragment ever leaks into a column name.
    assert all("--" not in col for col in trades.columns)
    assert all(col == col.lower() for col in trades.columns)


def test_alter_parser_accepts_bracketed_types(tmp_path: Path) -> None:
    (tmp_path / "0001.sql").write_text(
        "CREATE TABLE IF NOT EXISTS t (\n  ts TIMESTAMP,\n  a DOUBLE\n"
        ") TIMESTAMP(ts) PARTITION BY DAY WAL;\n"
        "ALTER TABLE t ADD COLUMN IF NOT EXISTS note VARCHAR(32);\n"
        "ALTER TABLE t ADD COLUMN IF NOT EXISTS tag SYMBOL CAPACITY 8 CACHE;\n",
        encoding="utf-8",
    )
    (table,) = parse_ddl_dir(tmp_path)
    assert table.columns == ("ts", "a", "note", "tag")
