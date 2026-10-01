"""`GET /market/trades` (`docs/plan/22-api-openapi.yaml` `getTrades`, E08-S04).

Serves the in-memory hot tape kept by `TradeStream` (last 1 000 prints per
symbol), newest-first. RBAC (C-12.4) mirrors `api/ticker.py`: fail-closed
501/401/403. Clustering (`cluster_window_ms > 0`) is E22 scope and is rejected
with 400 rather than silently ignored; deeper history is E16 (QuestDB/Parquet).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.api.ticker import _iso, _Principal, _problem, _Resolver
from candleviewer.exchange.base.models import TradeEvent

_REQUIRED_PERMISSION = "marketdata:read"


class TradeReader(Protocol):
    def recent(self, symbol: str) -> list[TradeEvent]: ...
    def is_listed(self, symbol: str) -> bool: ...


def serialize_trade(event: TradeEvent) -> dict[str, object]:
    return {
        "id": event.trade_id,
        "ts": _iso(event.ts_event),
        "price": format(event.price, "f"),
        "size": format(event.qty, "f"),
        "side": event.side,
        "is_block_trade": event.is_block_trade,
        "cluster_size": 1,
    }


def _parse_ts(value: str | None) -> int | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must carry a UTC offset")
    return int(dt.astimezone(UTC).timestamp() * 1_000_000)


def make_trades_router(
    reader_provider: Callable[[], TradeReader | None],
    *,
    principal_resolver: _Resolver | None = None,
) -> APIRouter:
    router = APIRouter(tags=["market-data"])

    @router.get("/market/trades")
    async def get_trades(
        request: Request,
        symbol: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = None,
        cursor: str | None = Query(default=None, max_length=512),
        limit: int = Query(default=100, ge=1, le=500),
        side: Literal["buy", "sell"] | None = None,
        min_size: str | None = None,
        cluster_window_ms: int = Query(default=0, ge=0, le=5000),
        cluster_tolerance_ticks: int = Query(default=0, ge=0, le=20),
    ) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        resolved: Any = principal_resolver.resolve(request)
        principal: _Principal | None = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        if not principal.has(_REQUIRED_PERMISSION):
            return _problem(403, "Forbidden", f"requires {_REQUIRED_PERMISSION}")
        if not (4 <= len(symbol) <= 20 and symbol.isascii() and symbol.isalnum()):
            return _problem(400, "Bad request", "invalid symbol")
        if cluster_window_ms > 0 or cursor is not None:
            return _problem(400, "Bad request", "clustering/cursor paging not available yet")
        try:
            start, end = _parse_ts(from_), _parse_ts(to)
            floor = None if min_size is None else Decimal(min_size)
        except (ValueError, InvalidOperation):
            return _problem(400, "Bad request", "invalid from/to/min_size")
        symbol = symbol.upper()
        reader = reader_provider()
        if reader is None:
            return _problem(503, "Service unavailable", "trade stream not running")
        if not reader.is_listed(symbol):
            return _problem(404, "Not found", f"unknown instrument {symbol}")
        rows = [
            e
            for e in reversed(reader.recent(symbol))
            if (start is None or e.ts_event >= start)
            and (end is None or e.ts_event < end)
            and (side is None or e.side == side)
            and (floor is None or e.qty >= floor)
        ]
        page = rows[:limit]
        meta = {"next_cursor": None, "has_more": len(rows) > limit, "count": len(page)}
        items = [serialize_trade(e) for e in page]
        return JSONResponse(status_code=200, content={"items": items, "meta": meta})

    return router


__all__ = ["TradeReader", "make_trades_router", "serialize_trade"]
