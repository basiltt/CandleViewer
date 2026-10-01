"""E08-S04 `GET /market/trades` contract + RBAC (no network)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import Page, PublicTrade
from candleviewer.api.trades import make_trades_router
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.ingestion.ticker_stream import uuid7


def _ev(i: int, side: str, qty: str) -> TradeEvent:
    ts = 1_700_000_000_000_000 + i * 1000
    return TradeEvent.model_validate(
        {
            "event_id": uuid7(ts // 1000),
            "ts_event": ts,
            "ts_ingest": ts,
            "source": "live",
            "symbol": "BTCUSDT",
            "trade_id": f"t{i}",
            "price": Decimal("63120.5"),
            "qty": Decimal(qty),
            "side": side,
            "is_block_trade": False,
            "price_ticks": 0,
            "notional": Decimal("1"),
            "seq": i,
        }
    )


class Reader:
    def recent(self, symbol: str) -> list[TradeEvent]:
        return [_ev(1, "buy", "0.1"), _ev(2, "sell", "2"), _ev(3, "buy", "5")]

    def is_listed(self, symbol: str) -> bool:
        return symbol == "BTCUSDT"


class Principal:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    def has(self, permission: str) -> bool:
        return self.ok and permission == "marketdata:read"


class Resolver:
    def __init__(self, principal: Principal | None) -> None:
        self.principal = principal

    async def resolve(self, request: Request) -> Any:
        return self.principal


_OK = Principal(True)
_READER = Reader()


def _client(principal: Principal | None = _OK, reader: Any = _READER) -> TestClient:
    app = FastAPI()
    app.include_router(make_trades_router(lambda: reader, principal_resolver=Resolver(principal)))
    return TestClient(app)


def test_get_trades_newest_first_matches_openapi_schema() -> None:
    r = _client().get("/market/trades", params={"symbol": "BTCUSDT", "limit": 2})
    assert r.status_code == 200
    body = r.json()
    Page.model_validate(body)
    items = [PublicTrade.model_validate(i) for i in body["items"]]
    assert [i.id for i in items] == ["t3", "t2"]
    assert body["meta"] == {"next_cursor": None, "has_more": True, "count": 2}


def test_get_trades_filters_side_min_size_and_window() -> None:
    c = _client()
    r = c.get("/market/trades", params={"symbol": "btcusdt", "side": "buy", "min_size": "1"})
    assert [i["id"] for i in r.json()["items"]] == ["t3"]
    r = c.get(
        "/market/trades",
        params={
            "symbol": "BTCUSDT",
            "from": "2023-11-14T22:13:20.002Z",
            "to": "2023-11-14T22:13:20.003Z",
        },
    )
    assert [i["id"] for i in r.json()["items"]] == ["t2"]


@pytest.mark.parametrize(
    ("principal", "params", "status"),
    [
        (None, {"symbol": "BTCUSDT"}, 401),
        (Principal(False), {"symbol": "BTCUSDT"}, 403),
        (Principal(True), {"symbol": "BAD*"}, 400),
        (Principal(True), {"symbol": "BTCUSDT", "cluster_window_ms": 50}, 400),
        (Principal(True), {"symbol": "BTCUSDT", "from": "nope"}, 400),
        (Principal(True), {"symbol": "BTCUSDT", "from": "2023-11-14T22:13:20"}, 400),
        (Principal(True), {"symbol": "ETHUSDT"}, 404),
    ],
)
def test_get_trades_error_paths(principal: Principal | None, params: Any, status: int) -> None:
    assert _client(principal).get("/market/trades", params=params).status_code == status


def test_get_trades_unwired_is_501_or_503() -> None:
    app = FastAPI()
    app.include_router(make_trades_router(lambda: None))
    assert TestClient(app).get("/market/trades?symbol=BTCUSDT").status_code == 501
    assert _client(reader=None).get("/market/trades?symbol=BTCUSDT").status_code == 503
