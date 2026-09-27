"""Extra `FakeMarketDataRepository` behaviour not covered by the shared
contract suite: book-snapshot "latest at or before" semantics and depth
truncation (these are fake-specific edge cases, not yet part of the
cross-implementation contract since E07-T02/T03/T04 have not landed to
confirm the exact semantics generalise unchanged)."""

from __future__ import annotations

from candleviewer.storage.models import TimeRange
from candleviewer.storage.repositories.rows import (
    BookDeltaRow,
    BookSnapshotRow,
    FootprintCellRow,
    OrderflowMetricRow,
    TickerRow,
)
from candleviewer.storage.testing import FakeMarketDataRepository


async def test_read_book_snapshot_at_returns_latest_at_or_before() -> None:
    repo = FakeMarketDataRepository()
    early = BookSnapshotRow(
        ts_us=100, symbol="BTCUSDT", seq=1, bids=(("100", "1"),), asks=(("101", "1"),)
    )
    late = BookSnapshotRow(
        ts_us=200, symbol="BTCUSDT", seq=2, bids=(("102", "2"),), asks=(("103", "2"),)
    )
    await repo.write_book_snapshot(early)
    await repo.write_book_snapshot(late)

    at_150 = await repo.read_book_snapshot_at("BTCUSDT", ts_us=150, depth=10)
    assert at_150 is not None
    assert at_150.ts_us == 100

    at_250 = await repo.read_book_snapshot_at("BTCUSDT", ts_us=250, depth=10)
    assert at_250 is not None
    assert at_250.ts_us == 200


async def test_read_book_snapshot_at_truncates_to_depth() -> None:
    repo = FakeMarketDataRepository()
    snapshot = BookSnapshotRow(
        ts_us=100,
        symbol="BTCUSDT",
        seq=1,
        bids=tuple((str(100 - i), "1") for i in range(5)),
        asks=tuple((str(101 + i), "1") for i in range(5)),
    )
    await repo.write_book_snapshot(snapshot)
    result = await repo.read_book_snapshot_at("BTCUSDT", ts_us=100, depth=2)
    assert result is not None
    assert len(result.bids) == 2
    assert len(result.asks) == 2


async def test_read_book_deltas_orders_by_ts_then_seq() -> None:
    repo = FakeMarketDataRepository()
    await repo.write_book_deltas(
        [
            BookDeltaRow(ts_us=100, symbol="BTCUSDT", seq=2, side="bid", price="99", qty="1"),
            BookDeltaRow(ts_us=100, symbol="BTCUSDT", seq=1, side="bid", price="98", qty="1"),
        ]
    )
    result = await repo.read_book_deltas("BTCUSDT", TimeRange(start_us=0, end_us=1_000))
    assert [r.seq for r in result] == [1, 2]


async def test_write_book_deltas_dedups_on_symbol_and_seq() -> None:
    repo = FakeMarketDataRepository()
    await repo.write_book_deltas(
        [BookDeltaRow(ts_us=100, symbol="BTCUSDT", seq=1, side="bid", price="98", qty="1")]
    )
    await repo.write_book_deltas(
        [BookDeltaRow(ts_us=200, symbol="BTCUSDT", seq=1, side="bid", price="99", qty="2")]
    )
    result = await repo.read_book_deltas("BTCUSDT", TimeRange(start_us=0, end_us=1_000))
    assert len(result) == 1
    assert result[0].price == "99"


async def test_latest_ticker_returns_most_recent() -> None:
    repo = FakeMarketDataRepository()
    await repo.write_tickers(
        [
            TickerRow(
                ts_us=100,
                symbol="BTCUSDT",
                last_price="1",
                mark_price="1",
                index_price="1",
                funding_rate="0",
                open_interest="0",
            ),
            TickerRow(
                ts_us=200,
                symbol="BTCUSDT",
                last_price="2",
                mark_price="2",
                index_price="2",
                funding_rate="0",
                open_interest="0",
            ),
        ]
    )
    latest = await repo.latest_ticker("BTCUSDT")
    assert latest is not None
    assert latest.ts_us == 200


async def test_read_orderflow_metrics_scoped_by_metric_name() -> None:
    repo = FakeMarketDataRepository()
    repo._orderflow[("BTCUSDT", "cvd", 100)] = OrderflowMetricRow(
        ts_us=100, symbol="BTCUSDT", metric="cvd", value="1"
    )
    repo._orderflow[("BTCUSDT", "imbalance", 100)] = OrderflowMetricRow(
        ts_us=100, symbol="BTCUSDT", metric="imbalance", value="2"
    )
    result = await repo.read_orderflow_metrics(
        "BTCUSDT", "cvd", TimeRange(start_us=0, end_us=1_000)
    )
    assert [r.metric for r in result] == ["cvd"]


async def test_read_footprint_cells_scoped_by_symbol_and_range() -> None:
    repo = FakeMarketDataRepository()
    repo._footprint[("BTCUSDT", 100, "50000")] = FootprintCellRow(
        bar_ts_us=100, symbol="BTCUSDT", price_level="50000", bid_qty="1", ask_qty="2"
    )
    repo._footprint[("ETHUSDT", 100, "3000")] = FootprintCellRow(
        bar_ts_us=100, symbol="ETHUSDT", price_level="3000", bid_qty="1", ask_qty="2"
    )
    result = await repo.read_footprint_cells("BTCUSDT", TimeRange(start_us=0, end_us=1_000))
    assert [r.symbol for r in result] == ["BTCUSDT"]
