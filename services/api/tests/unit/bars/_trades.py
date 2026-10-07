"""Shared helpers for the time-bar tests (E12-S01)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from candleviewer.bars.models import Bar, BarUpdate
from candleviewer.exchange.base.models import TradeEvent

SYM = "BTCUSDT"
_EID = uuid.UUID(int=1)


def us(hms: str, day: str = "2026-10-05") -> int:
    """`"10:00:59.900"` on `day` (UTC) as epoch microseconds."""
    dt = datetime.fromisoformat(f"{day}T{hms}").replace(tzinfo=UTC)
    return int(dt.timestamp()) * 1_000_000 + dt.microsecond


def trade(
    ts: int, px: str | Decimal = "100", qty: str | Decimal = "1", side: str = "buy", seq: int = 0
) -> TradeEvent:
    p, q = Decimal(px), Decimal(qty)
    return TradeEvent.model_construct(
        schema_version=1,
        event_id=_EID,
        ts_event=ts,
        ts_ingest=ts,
        source="replay",
        category="linear",
        symbol=SYM,
        trade_id=str(seq),
        price=p,
        qty=q,
        side=side,
        is_block_trade=False,
        price_ticks=0,
        notional=p * q,
        seq=seq,
    )


def final_bars(updates: Iterable[BarUpdate]) -> list[Bar]:
    """Latest emission per bar index, in index order (amendments overwrite, like the upsert)."""
    latest: dict[int, Bar] = {}
    for u in updates:
        latest[u.bar.index] = u.bar
    return [latest[i] for i in sorted(latest)]


def closes(updates: Sequence[BarUpdate]) -> list[Bar]:
    return [u.bar for u in updates if u.kind == "close"]
