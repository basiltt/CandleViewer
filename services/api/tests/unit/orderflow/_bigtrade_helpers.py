"""Shared builders for big-trade engine tests (no network, no wall clock)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint

TICK = Decimal("0.1")
_n = 0


def trade(
    ts_us: int,
    price: str,
    qty: str,
    side: str = "buy",
    trade_id: str | None = None,
    symbol: str = "BTCUSDT",
) -> TradeEvent:
    global _n
    _n += 1
    p, q = Decimal(price), Decimal(qty)
    return TradeEvent(
        event_id=EventId(uuid.UUID(int=_n)),
        ts_event=ts_us,
        ts_ingest=ts_us + 5_000,
        source="live",
        symbol=symbol,
        trade_id=trade_id or f"t{ts_us:015d}-{price}-{qty}-{side}",
        price=p,
        qty=q,
        side=side,  # type: ignore[arg-type]  # validated Literal at construction
        is_block_trade=False,
        price_ticks=int(p / TICK),
        notional=p * q,
        seq=_n,
    )


def recorded_prints(symbol: str, kind: str = "clean") -> list[TradeEvent]:
    """Recorded corpus (E08-T05; files resolved via `tests._corpus.CORPUS_ROOT`, B5-b
    harness) through the production parser, mapped to `TradeEvent` exactly as
    `ingestion/trade_stream.py` does (`notional = price * qty`, `price_ticks` from the tick)."""
    from tests._corpus import TICKS, frames, normalize

    tick = TICKS[symbol]
    out: list[TradeEvent] = []
    for frame in frames(f"ws/{kind}_publicTrade_{symbol}.jsonl"):
        for p in normalize(frame):
            assert isinstance(p, TradePrint)  # trade frames only in this corpus file
            out.append(
                TradeEvent.model_validate(
                    {
                        "event_id": EventId(uuid.UUID(int=len(out) + 1)),
                        "ts_event": p.ts_event_us,
                        "ts_ingest": p.ts_event_us,
                        "source": "replay",
                        "symbol": symbol,
                        "trade_id": p.trade_id,
                        "price": p.price,
                        "qty": p.qty,
                        "side": p.side,
                        "is_block_trade": p.is_block_trade,
                        "price_ticks": int((p.price / tick).to_integral_value()),
                        "notional": p.price * p.qty,
                        "seq": len(out) + 1,
                    }
                )
            )
    return out
