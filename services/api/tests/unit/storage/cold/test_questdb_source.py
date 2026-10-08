"""Unit tests: `QuestDbHotTierSource` paging/allowlist and the logging sink."""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

from candleviewer.observability.logging import configure_logging
from candleviewer.storage.cold.observability import LoggingSystemEventSink
from candleviewer.storage.cold.questdb_source import (
    QuestDbHotTierSource,
    UnsupportedExportStream,
    _us_to_datetime,
)
from candleviewer.storage.models import StreamKind
from tests.unit.storage.cold._helpers import DAY_START_US, day_range


class _FakeConn:
    def __init__(self, n: int) -> None:
        self.rows = [
            {"ts": DAY_START_US + i, "symbol": "BTCUSDT", "price": 1.0 + i} for i in range(n)
        ]
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls.append((sql, params))
        if "count(*)" in sql:
            return [{"n": len(self.rows)}]
        # Paging bounds are inlined as SQL literals (QuestDB's PGWire LIMIT
        # rejects bind params for them), so recover lo/hi from the SQL text.
        limit_clause = sql.rsplit("LIMIT", 1)[1].strip()
        lo_str, hi_str = limit_clause.split(",")
        lo, hi = int(lo_str), int(hi_str)
        return self.rows[lo:hi]


async def test_iter_partition_pages_with_bound_params_and_order() -> None:
    conn = _FakeConn(7)
    src = QuestDbHotTierSource(conn)
    batches = [
        b async for b in src.iter_partition("BTCUSDT", StreamKind.TRADES, day_range(), batch_rows=3)
    ]
    assert [b.num_rows for b in batches] == [3, 3, 1]
    sql, params = conn.calls[0]
    assert "FROM trades" in sql and "ORDER BY ts, price" in sql and "BTCUSDT" not in sql
    assert params[:3] == (
        "BTCUSDT",
        _us_to_datetime(day_range().start_us),
        _us_to_datetime(day_range().end_us),
    )
    assert await src.count_partition("BTCUSDT", StreamKind.TRADES, day_range()) == 7


async def test_iter_partition_exact_multiple_stops_on_empty_page() -> None:
    conn = _FakeConn(4)
    src = QuestDbHotTierSource(conn)
    got = [
        b.num_rows
        async for b in src.iter_partition("BTCUSDT", StreamKind.TICKERS, day_range(), batch_rows=2)
    ]
    assert got == [2, 2]
    assert "ORDER BY ts LIMIT" in conn.calls[0][0]


async def test_count_partition_empty_result_is_zero() -> None:
    class _Empty(_FakeConn):
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            return []

    assert (
        await QuestDbHotTierSource(_Empty(0)).count_partition(
            "BTCUSDT", StreamKind.TRADES, day_range()
        )
        == 0
    )


async def test_unmapped_stream_is_rejected() -> None:
    with pytest.raises(UnsupportedExportStream):
        await QuestDbHotTierSource(_FakeConn(0)).count_partition(
            "BTCUSDT", StreamKind.BARS, day_range()
        )


@pytest.mark.parametrize("severity", ["INFO", "WARNING", "CRITICAL"])
async def test_logging_sink_emits_every_level(severity: str) -> None:
    configure_logging(env="demo")  # as an earlier suite would: pins the cached chain + stdout
    with capture_logs() as logs:
        await LoggingSystemEventSink().emit(severity, "CODE_X", {"partition": "trades/x"})  # type: ignore[arg-type]  # parametrised literal
    assert [e["code"] for e in logs] == ["CODE_X"]
