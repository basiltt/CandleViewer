"""Shared `MarketDataRepository` contract suite (E07-T01 acceptance criterion
3: "a contract test suite written once is parametrized over [fake] today and
[questdb, timescale] later ... the same suite passes unchanged").

E07-T02/T03/T04 import `market_data_contract_tests` (or copy its test
bodies via a shared fixture) and parametrize `repo` over their own
implementations; this ticket runs it against `FakeMarketDataRepository` only.
"""

from __future__ import annotations

import pytest

from candleviewer.storage.models import TimeRange
from candleviewer.storage.repositories.market_data import MarketDataRepository
from candleviewer.storage.repositories.rows import BarRow, TradeRow
from candleviewer.storage.testing import FakeMarketDataRepository


@pytest.fixture(params=["fake"])
def repo(request: pytest.FixtureRequest) -> MarketDataRepository:
    if request.param == "fake":
        return FakeMarketDataRepository()
    raise AssertionError(f"unknown param {request.param!r}")  # pragma: no cover


async def test_write_then_read_trades_round_trips(repo: MarketDataRepository) -> None:
    rows = [
        TradeRow(ts_us=1_000, symbol="BTCUSDT", price="50000", qty="0.1", side="buy", trade_id="t1"),
        TradeRow(ts_us=2_000, symbol="BTCUSDT", price="50010", qty="0.2", side="sell", trade_id="t2"),
    ]
    await repo.write_trades(rows)
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=3_000))
    assert result == rows


async def test_read_trades_orders_by_ts_ascending(repo: MarketDataRepository) -> None:
    out_of_order = [
        TradeRow(ts_us=3_000, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="a"),
        TradeRow(ts_us=1_000, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="b"),
        TradeRow(ts_us=2_000, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="c"),
    ]
    await repo.write_trades(out_of_order)
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=10_000))
    assert [r.ts_us for r in result] == [1_000, 2_000, 3_000]


async def test_read_trades_filters_by_range(repo: MarketDataRepository) -> None:
    rows = [
        TradeRow(ts_us=ts, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id=str(ts))
        for ts in (100, 200, 300, 400)
    ]
    await repo.write_trades(rows)
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=150, end_us=350))
    assert [r.ts_us for r in result] == [200, 300]


async def test_write_trades_dedups_on_natural_key(repo: MarketDataRepository) -> None:
    original = TradeRow(
        ts_us=1_000, symbol="BTCUSDT", price="50000", qty="0.1", side="buy", trade_id="t1"
    )
    updated = TradeRow(
        ts_us=1_000, symbol="BTCUSDT", price="50001", qty="0.2", side="buy", trade_id="t1"
    )
    await repo.write_trades([original])
    await repo.write_trades([updated])
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=2_000))
    assert result == [updated]


async def test_read_trades_scoped_by_symbol(repo: MarketDataRepository) -> None:
    await repo.write_trades(
        [
            TradeRow(ts_us=100, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="a"),
            TradeRow(ts_us=100, symbol="ETHUSDT", price="1", qty="1", side="buy", trade_id="b"),
        ]
    )
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=1_000))
    assert [r.symbol for r in result] == ["BTCUSDT"]


async def test_write_then_read_bars_round_trips(repo: MarketDataRepository) -> None:
    bar = BarRow(
        ts_us=60_000_000,
        symbol="BTCUSDT",
        family="time",
        param="60000",
        open="1",
        high="2",
        low="0.5",
        close="1.5",
        volume="10",
    )
    await repo.write_bars([bar])
    result = await repo.read_bars(
        "BTCUSDT", "time", "60000", TimeRange(start_us=0, end_us=120_000_000)
    )
    assert result == [bar]


async def test_latest_ticker_returns_none_when_unwritten(repo: MarketDataRepository) -> None:
    assert await repo.latest_ticker("BTCUSDT") is None


async def test_read_book_snapshot_at_returns_none_before_any_snapshot(
    repo: MarketDataRepository,
) -> None:
    assert await repo.read_book_snapshot_at("BTCUSDT", ts_us=1, depth=10) is None
