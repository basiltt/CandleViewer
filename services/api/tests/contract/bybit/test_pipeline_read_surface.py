"""E08-Q02 pipeline integration: corpus frame -> stream -> bus -> REST read surface.

Drives the real `TradeStream`/`BookStream`/`TickerStream` with raw corpus frames and reads the
result back through the real routers (`/market/trades`, `/market/orderbook`,
`/instruments/{symbol}/ticker`, `/market/klines`), validating each body against the generated
OpenAPI models (the codegen output of `22-api-openapi.yaml`, no hand-written expectations).
Offline, fake clock, in-process (no sockets).

Gaps against the ticket text, reported in the PR: there is no `GET /market/data-coverage` route
and no WS gateway topics (`book.{symbol}.{depth}` etc.) in the codebase yet (E17), so those two
read surfaces cannot be asserted here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import (
    KlineResponse,
    OrderbookSnapshot,
    Page,
    PublicTrade,
    Ticker,
)
from candleviewer.api.instruments import InstrumentsPrincipal
from candleviewer.api.market import MarketDataPrincipal, make_market_router
from candleviewer.api.orderbook import make_orderbook_router
from candleviewer.api.ticker import make_ticker_router
from candleviewer.api.trades import make_trades_router
from candleviewer.book.models import BookPhase
from candleviewer.bus.bus import Bus
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.ingestion.metrics import ingest_events_total
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import frames, rest
from tests.contract.bybit._support import NOW_US, TradeHarness, counter_value, tick_of

_PRINCIPAL = InstrumentsPrincipal(user_id="u1", permissions=frozenset({"marketdata:read"}))


class _Resolver:
    def resolve(self, request: Request) -> Any:
        return _PRINCIPAL


def _client(*routers: Any) -> TestClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return TestClient(app, client=("127.0.0.1", 50000))


async def test_trades_fixture_to_rest_matches_the_oracle_rows() -> None:
    """E08-TC-D01/D02: the REST page equals the O-TRD oracle set, newest first, no duplicates."""
    h = TradeHarness()
    wire = [d for raw in frames("ws/publicTrade_BTCUSDT.jsonl") for d in json.loads(raw)["data"]]
    before = counter_value(ingest_events_total, stream="trade", symbol="BTCUSDT")
    for raw in frames("ws/publicTrade_BTCUSDT.jsonl"):
        await h.stream.handle_frame(raw)
    bus_ids = [e.trade_id for e in h.drain()]
    assert counter_value(ingest_events_total, stream="trade", symbol="BTCUSDT") - before == len(
        wire
    )
    client = _client(make_trades_router(lambda: h.stream, principal_resolver=_Resolver()))
    body = client.get("/market/trades", params={"symbol": "BTCUSDT", "limit": 100}).json()
    Page.model_validate(body)
    items = [PublicTrade.model_validate(i) for i in body["items"]]
    assert {i.id for i in items} == {d["i"] for d in wire} == set(bus_ids)  # REST == bus == wire
    assert body["meta"]["count"] == len(wire)
    block = [i for i in items if i.is_block_trade]
    assert [b.id for b in block] == [d["i"] for d in wire if d["BT"]]
    assert all(set(i.model_dump(exclude_none=True)) <= set(PublicTrade.model_fields) for i in items)


async def _book(frames_: list[str]) -> BookStream:
    resubs: list[str] = []

    async def resub(topic: str) -> None:
        resubs.append(topic)

    stream = BookStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _t: None,
        parse_frame=lambda f: parse_book_frame(f, tick_of),
        topic_for=book_topic,
        resubscribe=resub,
        is_listed=lambda s: s == "BTCUSDT",
        touch=lambda _t: None,
        now_us=lambda: NOW_US,
    )
    stream.acquire("it", "BTCUSDT")
    for raw in frames_:
        await stream.handle_frame(raw)
    stream.resubs = resubs  # type: ignore[attr-defined]
    return stream


async def test_book_fixture_to_rest_orderbook_is_ordered_uncrossed_and_schema_valid() -> None:
    """E08-TC-E02/E03 shape: top-50 over REST, best bid < best ask, ordered, `u` == last applied."""
    stream = await _book(frames("ws/orderbook_BTCUSDT.jsonl")[:500])
    client = _client(make_orderbook_router(lambda: stream, principal_resolver=_Resolver()))
    r = client.get("/market/orderbook", params={"symbol": "BTCUSDT", "depth": 50})
    assert r.status_code == 200
    body = r.json()
    OrderbookSnapshot.model_validate(body)
    bids = [Decimal(p) for p, _ in body["bids"]]
    asks = [Decimal(p) for p, _ in body["asks"]]
    assert len(bids) == len(asks) == 50 and bids == sorted(bids, reverse=True)
    assert asks == sorted(asks) and bids[0] < asks[0]
    assert body["u"] == json.loads(frames("ws/orderbook_BTCUSDT.jsonl")[499])["data"]["u"]
    assert body["stale"] is False


async def test_book_gap_serves_503_while_resyncing_never_a_patched_book() -> None:
    """E08-TC-E06 over the read surface: after the u hole the REST view refuses, then a
    snapshot recovers it."""
    raw = frames("ws/orderbook_BTCUSDT.jsonl")
    stream = await _book(raw[:2701])  # includes the hole frame (index 2700)
    assert stream.phase("BTCUSDT") is BookPhase.SNAPSHOT_PENDING
    assert stream.resubs == [book_topic("BTCUSDT", 200)]  # type: ignore[attr-defined]
    client = _client(make_orderbook_router(lambda: stream, principal_resolver=_Resolver()))
    assert client.get("/market/orderbook", params={"symbol": "BTCUSDT"}).status_code == 503
    await stream.handle_frame(raw[0])  # fresh snapshot (corpus u == 1) re-seeds the book
    r = client.get("/market/orderbook", params={"symbol": "BTCUSDT"})
    assert r.status_code == 200 and r.json()["u"] == 1


async def test_ticker_fixture_to_rest_returns_the_merged_full_ticker() -> None:
    stream = TickerStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _t: None,
        parse_frame=parse_ticker_frame,
        topic_for=ticker_topic,
        is_listed=lambda s: s == "BTCUSDT",
        touch=lambda _t: None,
        clock=lambda: 0.0,
        now_us=lambda: NOW_US,
    )
    stream.acquire("it", "BTCUSDT")
    for raw in frames("ws/tickers_BTCUSDT.jsonl"):
        await stream.handle_frame(raw)
    client = _client(make_ticker_router(lambda: stream, principal_resolver=_Resolver()))
    r = client.get("/instruments/BTCUSDT/ticker")
    assert r.status_code == 200
    body = r.json()
    Ticker.model_validate(body)
    assert body["bid1_price"] == "63121.00" and body["bid1_size"] == "0"  # last delta wins
    assert body["last_price"] == "63121.00" and body["mark_price"] == "63118.90"  # merged
    assert body["funding_rate"] == "0" and body["stale"] is False


@dataclass(slots=True)
class _Row:
    ts_us: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str
    confirmed: bool = True


class _Cache:
    def __init__(self, rows: list[_Row]) -> None:
        self.rows = rows

    async def read_klines(
        self, sym: str, interval: str, rng: Any, tier: str = "auto"
    ) -> list[_Row]:
        return [r for r in self.rows if rng.start_us <= r.ts_us < rng.end_us]


def test_kline_fixture_to_rest_is_ascending_gapless_and_schema_valid() -> None:
    """E08-TC-F01 shape: the 450 corpus bars, wire-descending, are served ascending with no
    duplicated or missing open time."""
    wire = [
        row
        for i in range(3)
        for row in rest(f"rest/kline_BTCUSDT_1_page{i}.json")["result"]["list"]
    ]
    rows = [_Row(int(r[0]) * 1000, r[1], r[2], r[3], r[4], r[5], r[6]) for r in wire]
    rows.sort(key=lambda r: r.ts_us)
    resolver = type(
        "R",
        (),
        {"resolve": lambda _s, _r: MarketDataPrincipal("u1", frozenset({"marketdata:read"}))},
    )()
    client = _client(make_market_router(lambda: _Cache(rows), principal_resolver=resolver))
    r = client.get(
        "/market/klines",
        params={
            "symbol": "BTCUSDT",
            "interval": "1",
            "from": "2023-11-14T00:00:00Z",
            "to": "2023-11-16T00:00:00Z",
            "limit": 1000,
        },
    )
    assert r.status_code == 200
    body = r.json()
    KlineResponse.model_validate(body)
    ts = [b["t"] for b in body["bars"]]
    assert len(ts) == len(set(ts)) == 450 and ts == sorted(ts)
    assert body["meta"]["count"] == 450
