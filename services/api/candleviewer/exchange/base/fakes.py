"""In-memory `MarketDataPort` fake for downstream unit tests (ticket body,
acceptance criterion 2). No network, no fixtures, no exchange vocabulary —
callers seed it with plain domain objects and get an isinstance-conforming
adapter back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import Symbol, TsUs

from .errors import NotFoundError
from .models import (
    BookDelta,
    BookSnapshot,
    FundingEvent,
    KlineEvent,
    LiquidationEvent,
    OpenInterestEvent,
    RiskLimitTier,
    TickerEvent,
    TradeEvent,
)

__all__ = ["FakeExchange"]


class FakeExchange:
    """Satisfies `MarketDataPort` structurally (no inheritance). Seed data
    via the constructor; `subscribe_*` methods replay the seeded sequence
    once and then end the iterator — enough for a unit test to assert on a
    finite stream without a real transport."""

    def __init__(
        self,
        *,
        instruments: Sequence[Instrument] = (),
        trades: Sequence[TradeEvent] = (),
        book_events: Sequence[BookSnapshot | BookDelta] = (),
        tickers: Sequence[TickerEvent] = (),
        klines: Sequence[KlineEvent] = (),
        liquidations: Sequence[LiquidationEvent] = (),
        open_interest: Sequence[OpenInterestEvent] = (),
        funding: Sequence[FundingEvent] = (),
        risk_limits: Sequence[RiskLimitTier] = (),
        server_time: TsUs = 0,
    ) -> None:
        self._instruments = {i.symbol: i for i in instruments}
        self._trades = list(trades)
        self._book_events = list(book_events)
        self._tickers = list(tickers)
        self._klines = list(klines)
        self._liquidations = list(liquidations)
        self._open_interest = list(open_interest)
        self._funding = list(funding)
        self._risk_limits = list(risk_limits)
        self._server_time = server_time

    async def instruments(self) -> Sequence[Instrument]:
        return list(self._instruments.values())

    async def instrument(self, symbol: Symbol) -> Instrument:
        try:
            return self._instruments[symbol]
        except KeyError as exc:
            raise NotFoundError(f"no fake instrument seeded for {symbol!r}") from exc

    async def subscribe_trades(self, symbols: Sequence[Symbol]) -> AsyncIterator[TradeEvent]:
        for event in self._trades:
            if event.symbol in symbols:
                yield event

    async def subscribe_book(
        self, symbols: Sequence[Symbol], depth: int
    ) -> AsyncIterator[BookSnapshot | BookDelta]:
        for event in self._book_events:
            if event.symbol in symbols and event.depth == depth:
                yield event

    async def subscribe_ticker(self, symbols: Sequence[Symbol]) -> AsyncIterator[TickerEvent]:
        for event in self._tickers:
            if event.symbol in symbols:
                yield event

    async def subscribe_klines(
        self, symbols: Sequence[Symbol], interval: str
    ) -> AsyncIterator[KlineEvent]:
        for event in self._klines:
            if event.symbol in symbols and event.interval == interval:
                yield event

    async def subscribe_liquidations(
        self, symbols: Sequence[Symbol]
    ) -> AsyncIterator[LiquidationEvent]:
        for event in self._liquidations:
            if event.symbol in symbols:
                yield event

    async def fetch_klines(
        self,
        symbol: Symbol,
        interval: str,
        start: TsUs,
        end: TsUs,
        limit: int = 1000,
    ) -> Sequence[KlineEvent]:
        matches = [
            k
            for k in self._klines
            if k.symbol == symbol and k.interval == interval and start <= k.start <= end
        ]
        return matches[:limit]

    async def fetch_recent_trades(self, symbol: Symbol, limit: int = 1000) -> Sequence[TradeEvent]:
        matches = [t for t in self._trades if t.symbol == symbol]
        return matches[:limit]

    async def fetch_orderbook(self, symbol: Symbol, depth: int = 200) -> BookSnapshot:
        for event in self._book_events:
            if isinstance(event, BookSnapshot) and event.symbol == symbol and event.depth == depth:
                return event
        raise NotFoundError(f"no fake orderbook snapshot seeded for {symbol!r}@{depth}")

    async def fetch_open_interest(
        self, symbol: Symbol, interval: str, start: TsUs, end: TsUs
    ) -> Sequence[OpenInterestEvent]:
        return [
            e
            for e in self._open_interest
            if e.symbol == symbol and e.interval == interval and start <= e.ts_event <= end
        ]

    async def fetch_funding_history(
        self, symbol: Symbol, start: TsUs, end: TsUs
    ) -> Sequence[FundingEvent]:
        return [e for e in self._funding if e.symbol == symbol and start <= e.ts_event <= end]

    async def fetch_risk_limits(self, symbol: Symbol) -> Sequence[RiskLimitTier]:
        return list(self._risk_limits)

    async def server_time_us(self) -> TsUs:
        return self._server_time
