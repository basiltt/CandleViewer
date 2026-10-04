"""Regression tests for the semgrep SQL-construction fixes (PR #1755 follow-up)."""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.storage.cold.duckdb_views import query_symbol_day_count
from candleviewer.storage.questdb.reader import pgwire_committed_counter
from candleviewer.storage.sql_identifiers import (
    UnsafeSqlIdentifier,
    checked_identifier,
    sql_string_literal,
)


@pytest.mark.parametrize("name", ["trades", "_cv_migrations", "bars_1m", "A" * 63])
def test_checked_identifier_plain_name_is_returned(name: str) -> None:
    assert checked_identifier(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "1trades", "trades; DROP TABLE x", "a b", 'tr"ades', "trades--", "A" * 64, "pg.public.t"],
)
def test_checked_identifier_injection_shaped_name_is_rejected(name: str) -> None:
    with pytest.raises(UnsafeSqlIdentifier):
        checked_identifier(name)


def test_sql_string_literal_doubles_quotes() -> None:
    assert sql_string_literal("a'b") == "'a''b'"


def test_sql_string_literal_nul_is_rejected() -> None:
    with pytest.raises(UnsafeSqlIdentifier):
        sql_string_literal("a\x00b")


class _RecordingConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.queries.append(sql)
        return [{"n": 2}]


async def test_committed_counter_valid_tables_counts_each() -> None:
    conn = _RecordingConnection()
    counter = pgwire_committed_counter(conn, ("trades", "bars"))
    assert await counter() == 4
    assert conn.queries == ["SELECT count() AS n FROM trades", "SELECT count() AS n FROM bars"]


def test_committed_counter_unsafe_table_rejected_before_any_query() -> None:
    conn = _RecordingConnection()
    with pytest.raises(UnsafeSqlIdentifier):
        pgwire_committed_counter(conn, ("trades; DROP TABLE bars",))
    assert conn.queries == []


def test_query_symbol_day_count_unregistered_view_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unregistered view"):
        query_symbol_day_count(tmp_path / "x.duckdb", "trades; --", "BTCUSDT", "2026-10-17")
