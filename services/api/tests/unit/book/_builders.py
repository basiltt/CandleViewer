"""Shared builders for book tests (no network, synthetic levels)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from candleviewer.exchange.base.models import BookDelta, BookLevel, BookSnapshot

_EID = UUID(int=1)


def lvl(ticks: int, qty: int | str) -> BookLevel:
    return BookLevel(price=Decimal(ticks) / 10, qty=Decimal(qty), price_ticks=ticks)


def snap(u: int, bids: list[BookLevel], asks: list[BookLevel], depth: int = 200) -> BookSnapshot:
    return BookSnapshot(
        event_id=_EID, ts_event=u, ts_ingest=u, source="live", symbol="BTCUSDT", depth=depth,
        bids=tuple(bids), asks=tuple(asks), update_id=u, cross_seq=u, ts_match=u,
        reason="subscribe",
    )  # fmt: skip


def delta(
    u: int, prev: int, bids: list[BookLevel] = (), asks: list[BookLevel] = (), depth: int = 200
) -> BookDelta:
    return BookDelta(
        event_id=_EID, ts_event=u, ts_ingest=u, source="live", symbol="BTCUSDT", depth=depth,
        bids=tuple(bids), asks=tuple(asks), update_id=u, prev_update_id=prev, cross_seq=u,
        ts_match=u,
    )  # fmt: skip
