"""Domain models for the exchange.base module (M3).

`Trade` and `Ticker` are the normalised domain events named in C-2.3
("Ingestion converts exchange payloads into normalised domain events") —
exchange-neutral shapes with no Bybit-specific field names, symbols, or
error codes (C-2.2). The synthetic feed generator (`candleviewer.ingestion`,
E02-T12) publishes these same shapes so downstream consumers (bus fan-out,
dashboards, E08's real Bybit adapter) share one contract regardless of
which feed produced the event.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class TradeSide(StrEnum):
    """Aggressor side of a trade print."""

    BUY = "buy"
    SELL = "sell"


class Trade(BaseModel):
    """A single normalised trade print.

    `price`/`size` are `Decimal` (never `float`) per the coding standard for
    money/quantity fields. `ts` is the exchange/source event time, tz-aware
    UTC — never `datetime.now()`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    price: Decimal
    size: Decimal
    side: TradeSide
    ts: datetime


class Ticker(BaseModel):
    """A normalised best-bid/ask + last-price snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    last_price: Decimal
    bid_price: Decimal
    ask_price: Decimal
    ts: datetime
