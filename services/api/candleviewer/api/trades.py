"""`GET /market/trades` (`docs/plan/22-api-openapi.yaml` `getTrades`, E08-S04).

Serves the in-memory hot tape kept by `TradeStream` (last 1 000 prints per
symbol), newest-first, with the full contract surface: `from`/`to`, `side`,
`min_size`, opaque keyset `cursor` paging, split-fill clustering
(`cluster_window_ms`/`cluster_tolerance_ticks`) and derived `tick_direction`.
A request for a listed symbol also (re)acquires its `publicTrade` demand with
a grace period, so the tape fills lazily with no other consumer. RBAC (C-12.4)
mirrors `api/ticker.py`: fail-closed 501/401/403. Deeper history is E16.
"""

from __future__ import annotations

import base64
import binascii
import inspect
import json
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
    def acquire(self, consumer: str, symbol: str) -> None: ...
    def release(self, consumer: str, symbol: str) -> None: ...
    def tick_size(self, symbol: str) -> Decimal | None: ...


DEMAND_CONSUMER = "rest-tape"


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


def _tick_directions(asc: list[TradeEvent]) -> dict[str, str]:
    """Bybit tick semantics derived over the hot tape (oldest first)."""
    out: dict[str, str] = {}
    prev: Decimal | None = None
    last = "ZeroPlusTick"
    for e in asc:
        if prev is not None:
            if e.price > prev:
                last = "PlusTick"
            elif e.price < prev:
                last = "MinusTick"
            elif last == "PlusTick":
                last = "ZeroPlusTick"
            elif last == "MinusTick":
                last = "ZeroMinusTick"
            out[e.trade_id] = last
        prev = e.price
    return out


def _cluster(
    asc: list[TradeEvent], window_ms: int, tol_ticks: int, tick: Decimal | None
) -> list[tuple[TradeEvent, Decimal, int]]:
    """Merge same-side prints within `tol_ticks` of the cluster's first price and
    `window_ms` of its first print (split-fill aggregation; display only)."""
    tol = (tick or Decimal(0)) * tol_ticks
    open_: list[list[Any]] = []  # [first, size, n]
    out: list[list[Any]] = []
    for e in asc:
        open_ = [c for c in open_ if (e.ts_event - c[0].ts_event) <= window_ms * 1000]
        for c in open_:
            if c[0].side == e.side and abs(c[0].price - e.price) <= tol:
                c[1] += e.qty
                c[2] += 1
                break
        else:
            c = [e, e.qty, 1]
            open_.append(c)
            out.append(c)
    return [(c[0], c[1], c[2]) for c in out]


def _encode_cursor(e: TradeEvent) -> str:
    raw = json.dumps({"ts": e.ts_event, "id": e.trade_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[int, str]:
    try:
        obj = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        return int(obj["ts"]), str(obj["id"])
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise ValueError("invalid cursor") from exc


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
        try:
            start, end = _parse_ts(from_), _parse_ts(to)
            floor = None if min_size is None else Decimal(min_size)
            after = None if cursor is None else _decode_cursor(cursor)
        except (ValueError, InvalidOperation):
            return _problem(400, "Bad request", "invalid from/to/min_size/cursor")
        symbol = symbol.upper()
        reader = reader_provider()
        if reader is None:
            return _problem(503, "Service unavailable", "trade stream not running")
        if not reader.is_listed(symbol):
            return _problem(404, "Not found", f"unknown instrument {symbol}")
        # Demand is refreshed per request; the grace period expires it when idle.
        reader.acquire(DEMAND_CONSUMER, symbol)
        reader.release(DEMAND_CONSUMER, symbol)
        asc = sorted(reader.recent(symbol), key=lambda e: (e.ts_event, e.trade_id))
        ticks = _tick_directions(asc)
        asc = [
            e
            for e in asc
            if (start is None or e.ts_event >= start)
            and (end is None or e.ts_event < end)
            and (side is None or e.side == side)
        ]
        clusters = (
            _cluster(asc, cluster_window_ms, cluster_tolerance_ticks, reader.tick_size(symbol))
            if cluster_window_ms > 0
            else [(e, e.qty, 1) for e in asc]
        )
        rows = [
            c
            for c in reversed(clusters)
            if (floor is None or c[1] >= floor)
            and (after is None or (c[0].ts_event, c[0].trade_id) < after)
        ]
        page = rows[:limit]
        has_more = len(rows) > limit
        meta = {
            "next_cursor": _encode_cursor(page[-1][0]) if has_more else None,
            "has_more": has_more,
            "count": len(page),
        }
        items = []
        for first, size, n in page:
            item = serialize_trade(first)
            item["size"] = format(size, "f")
            item["cluster_size"] = n
            td = ticks.get(first.trade_id)
            if td is not None:
                item["tick_direction"] = td
            items.append(item)
        return JSONResponse(status_code=200, content={"items": items, "meta": meta})

    return router


__all__ = ["TradeReader", "make_trades_router", "serialize_trade"]
