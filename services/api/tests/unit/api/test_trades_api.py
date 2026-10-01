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
    def __init__(self) -> None:
        self.acquired: list[tuple[str, str]] = []

    def acquire(self, consumer: str, symbol: str) -> None:
        self.acquired.append((consumer, symbol))

    def release(self, consumer: str, symbol: str) -> None:
        pass

    def tick_size(self, symbol: str) -> Decimal | None:
        return Decimal("0.1")

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
    assert body["meta"]["has_more"] is True and body["meta"]["count"] == 2
    assert body["meta"]["next_cursor"]


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


def test_get_trades_acquires_demand_so_tape_fills() -> None:
    reader = Reader()
    _client(reader=reader).get("/market/trades?symbol=BTCUSDT")
    assert reader.acquired == [("rest-tape", "BTCUSDT")]


def test_get_trades_cursor_pages_without_overlap() -> None:
    c = _client()
    p1 = c.get("/market/trades", params={"symbol": "BTCUSDT", "limit": 2}).json()
    assert p1["meta"]["has_more"] is True
    p2 = c.get(
        "/market/trades",
        params={"symbol": "BTCUSDT", "limit": 2, "cursor": p1["meta"]["next_cursor"]},
    ).json()
    assert [i["id"] for i in p2["items"]] == ["t1"]
    assert p2["meta"] == {"next_cursor": None, "has_more": False, "count": 1}
    assert c.get("/market/trades", params={"symbol": "BTCUSDT", "cursor": "!!"}).status_code == 400


def test_get_trades_clusters_same_side_same_price_in_window() -> None:
    # t1 buy@t0, t3 buy@t+2ms (same price): merged; t2 sell stays alone.
    r = _client().get("/market/trades", params={"symbol": "BTCUSDT", "cluster_window_ms": 10})
    body = r.json()
    Page.model_validate(body)
    by_id = {i["id"]: i for i in body["items"]}
    assert by_id["t1"]["cluster_size"] == 2 and by_id["t1"]["size"] == "5.1"
    assert by_id["t2"]["cluster_size"] == 1
    assert "t3" not in by_id


def test_get_trades_derives_tick_direction() -> None:
    items = _client().get("/market/trades?symbol=BTCUSDT").json()["items"]
    assert all(PublicTrade.model_validate(i) for i in items)
    assert items[0]["tick_direction"] == "ZeroPlusTick"
