"""Venue-neutral trade print (E08-S04, `docs/plan/24-internal-schemas.md` §2.1).

An exchange adapter parses its native tape frame (WS push or REST recent-trade
page) into `TradePrint`s; ingestion owns dedupe, ordering, gap marking and the
`TradeEvent` envelope. `side` is the **taker/aggressor** side.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

#: Hostile-upstream cap: ids longer than this are rejected before the dedupe ring.
MAX_TRADE_ID_LEN = 64
#: A single frame/page carrying more prints than this is rejected outright.
MAX_PRINTS_PER_BATCH = 2000


@dataclass(frozen=True, slots=True)
class TradePrint:
    symbol: str
    trade_id: str
    ts_event_us: int
    price: Decimal
    qty: Decimal
    side: Literal["buy", "sell"]
    is_block_trade: bool
