"""#2168: QuestDB PGWire has no `LIMIT $n` bind slot; every builder's params must match its `$n`."""

from __future__ import annotations

import re

import pytest

from candleviewer.bars.limits import MAX_LIMIT
from candleviewer.domain.sql_names import SqlBindMismatch, assert_bind_count
from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.reader import (
    _MAX_QUERY_LIMIT,
    build_read_funding,
    build_read_klines,
)

_RNG = TimeRange(start_us=0, end_us=10)


def _distinct(sql: str) -> int:
    return len(set(re.findall(r"\$\d+", sql)))


@pytest.mark.parametrize("limit", [None, 1, 500, MAX_LIMIT + 1])
def test_klines_bind_count_matches_placeholders(limit: int | None) -> None:
    q = build_read_klines("BTCUSDT", "1", _RNG, limit)
    assert len(q.params) == _distinct(q.sql) == 4
    assert ("LIMIT" in q.sql) == (limit is not None)


@pytest.mark.parametrize("limit", [1, 501])
def test_funding_bind_count_matches_placeholders(limit: int) -> None:
    q = build_read_funding("BTCUSDT", _RNG, limit)
    assert len(q.params) == _distinct(q.sql) == 3
    assert q.sql.endswith(f"LIMIT {limit}")


@pytest.mark.parametrize("bad", [0, -1, MAX_LIMIT + 2, True])
def test_limit_outside_clamp_is_refused(bad: int) -> None:
    with pytest.raises(ValueError):
        build_read_klines("BTCUSDT", "1", _RNG, bad)
    with pytest.raises(ValueError):
        build_read_funding("BTCUSDT", _RNG, bad)


def test_assert_bind_count_rejects_extra_and_missing() -> None:
    assert_bind_count("SELECT 1 WHERE a = $1 AND b = $2 AND c = $1", (1, 2))
    with pytest.raises(SqlBindMismatch):
        assert_bind_count("SELECT 1 WHERE a = $1 LIMIT $2", (1, 2, 3))
    with pytest.raises(SqlBindMismatch):
        assert_bind_count("SELECT 1 WHERE a = $1 AND b = $2", (1,))
    with pytest.raises(SqlBindMismatch):
        assert_bind_count("SELECT 1 WHERE a = $2", (1,))


def test_query_limit_cap_mirrors_bars_max_limit() -> None:
    assert _MAX_QUERY_LIMIT == MAX_LIMIT + 1
