"""Shared helpers for the Bybit adapter contract pack (E08-Q02).

Everything reads the recorded corpus through `tests._corpus` (C-13.5): raw frames in,
normalised domain events out, no network, injected clocks only.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.bybit.orderbook import parse_book_frame
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion.trade_stream import TradeStream

TICK = Decimal("0.1")
NOW_US = 1_700_000_009_500_000


def tick_of(_symbol: str) -> Decimal:
    return TICK


def book_events(frames: list[str], tick: Callable[[str], Decimal | None] = tick_of) -> list[Any]:
    """Parse every book frame through the production parser."""
    out = []
    for raw in frames:
        ev = parse_book_frame(raw, tick)
        assert ev is not None, raw[:80]
        out.append(ev)
    return out


class TradeHarness:
    """A `TradeStream` wired like the composition root, on a fake clock."""

    def __init__(self, symbol: str = "BTCUSDT", fetch: Any = None) -> None:
        self.bus = Bus()
        self.sub = self.bus.subscribe(
            "contract", "live.md.*.trade", QueuePolicy.NEVER_DROP, maxsize=100_000
        )
        self.gap_sub = self.bus.subscribe("contract-gap", "live.md.*.gap", QueuePolicy.NEVER_DROP)
        self.stream = TradeStream(
            bus=self.bus,
            env="live",
            set_desired=lambda _d: None,
            parse_frame=parse_trade_frame,
            topic_for=trade_topic,
            is_listed=lambda s: s == symbol,
            touch=lambda _t: None,
            fetch_recent=fetch,
            tick_size=lambda _s: TICK,
            clock=lambda: 0.0,
            now_us=lambda: NOW_US,
        )
        self.stream.acquire("contract", symbol)

    def drain(self) -> list[Any]:
        out = []
        while not self.sub.queue.empty():
            out.append(self.sub.queue.get_nowait())
        return out

    def drain_gaps(self) -> list[Any]:
        out = []
        while not self.gap_sub.queue.empty():
            out.append(self.gap_sub.queue.get_nowait())
        return out


def counter_value(counter: Any, **labels: str) -> float:
    return float((counter.labels(**labels) if labels else counter)._value.get())
