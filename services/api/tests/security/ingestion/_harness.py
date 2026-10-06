"""In-process injection harness for E08-X02 (stands in for the E08-Q03 proxy).

Drives raw frames through the *production* stream objects the socket pump calls
(`TradeStream`/`TickerStream`/`BookStream.handle_frame`), wired exactly as the
composition root does, with fake clocks and an in-memory bus. No network.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.orderbook_wiring import BookStream

TICK = {"BTCUSDT": Decimal("0.1")}


def tick(symbol: str) -> Decimal | None:
    return TICK.get(symbol)


class Rig:
    """One env's three public streams on one bus, all demanding BTCUSDT."""

    def __init__(self) -> None:
        self.bus = Bus()
        self.sub = self.bus.subscribe("x02", "live.md.*.*", QueuePolicy.NEVER_DROP, maxsize=100_000)
        self.resubs: deque[str] = deque(maxlen=64)  # bounded: thrash tests measure memory
        self.now_s = 0.0

        async def resub(topic: str) -> None:
            self.resubs.append(topic)

        def listed(s: str) -> bool:
            return s in TICK

        common: dict[str, Any] = {
            "bus": self.bus,
            "env": "live",
            "set_desired": lambda _t: None,
            "is_listed": listed,
            "touch": lambda _t: None,
            "clock": lambda: self.now_s,
            "now_us": lambda: int(self.now_s * 1_000_000),
        }
        self.trades = TradeStream(parse_frame=parse_trade_frame, topic_for=trade_topic, **common)
        self.tickers = TickerStream(
            parse_frame=parse_ticker_frame, topic_for=ticker_topic, **common
        )
        self.books = BookStream(
            parse_frame=lambda f: parse_book_frame(f, tick),
            topic_for=book_topic,
            resubscribe=resub,
            default_depth=50,
            **common,
        )
        for s in (self.trades, self.tickers, self.books):
            s.acquire("x02", "BTCUSDT")

    async def feed(self, frame: str) -> None:
        """Exactly the `IngestionService._pump_frames` fan-out for one frame."""
        await self.trades.handle_frame(frame)
        await self.tickers.handle_frame(frame)
        await self.books.handle_frame(frame)

    def drain(self) -> list[Any]:
        out: list[Any] = []
        while not self.sub.queue.empty():
            out.append(self.sub.queue.get_nowait())
        return out
