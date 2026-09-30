"""Integration: QuestDB hot tier -> Parquet cold tier -> DuckDB (E07-T04).

Needs Docker (testcontainers QuestDB 8.x); exercised in CI's `integration`
job — not run locally in environments without Docker. Covers the AC's
row-count parity against the real `COUNT(*)`, the `ORDER BY ts, price`
paging over PGWire, and the R0 exit #6 DuckDB symbol-day query.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from candleviewer.storage.cold.duckdb_views import build_views, query_symbol_day_count
from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.questdb_source import QuestDbHotTierSource
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.reader import QuestDbReader
from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from candleviewer.storage.repositories.rows import TradeRow
from tests.integration.storage.test_questdb_hot_tier import (
    DDL_DIR,
    _AsyncpgExecutor,
    _AsyncpgTcpIlpTransport,
    _connect,
    questdb_container,  # noqa: F401 -- pytest fixture re-export
    wait_for_row_count,
)

pytestmark = pytest.mark.integration

_DAY = datetime(2026, 10, 17, tzinfo=UTC)
_START_US = int(_DAY.timestamp() * 1_000_000)


@pytest.mark.asyncio
async def test_hot_to_cold_symbol_day_parity_and_duckdb_count(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
    tmp_path: Path,
) -> None:
    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        writer = IlpWriter(_AsyncpgTcpIlpTransport(host, ilp_port), ALL_SCHEMAS)
        await writer.start()
        repo = QuestDbMarketDataRepository(writer, QuestDbReader(conn))
        rows = [
            TradeRow(
                ts_us=_START_US + i * 1000,
                symbol="BTCUSDT",
                price=f"{65000 + i % 5}.5",
                qty="0.01",
                side="buy" if i % 2 else "sell",
                trade_id=f"t{i}",
            )
            for i in range(2500)
        ]
        await repo.write_trades(rows)
        await writer.flush("trades")
        await writer.stop()

        source = QuestDbHotTierSource(_AsyncpgExecutor(conn))
        rng = TimeRange(start_us=_START_US, end_us=_START_US + 86_400_000_000)
        # Writer is flushed + stopped above (socket drained); WAL apply is
        # still asynchronous, so wait on the table-wide count + writerTxn ==
        # sequencerTxn (shared helper), then check the exporter's own
        # symbol/range-filtered count separately so a filter bug is not
        # misreported as a WAL-apply timeout.
        await wait_for_row_count(conn, "trades", 2500)
        assert await source.count_partition("BTCUSDT", StreamKind.TRADES, rng) == 2500

        exporter = ColdExporter(DatasetRegistry(tmp_path), source, rows_per_group=1000)
        run = await exporter.export_partition("BTCUSDT", StreamKind.TRADES, rng)
        assert run.row_count == 2500
        assert await exporter.verify("BTCUSDT", StreamKind.TRADES, rng)

        db = tmp_path / "analytics.duckdb"
        build_views(db, DatasetRegistry(tmp_path))
        assert query_symbol_day_count(db, "trades", "BTCUSDT", "2026-10-17") == 2500
    finally:
        await conn.close()
