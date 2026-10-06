from __future__ import annotations

from typing import Any

import httpx
import pytest

from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.funding import (
    BybitFundingFetcher,
    FundingRowRejected,
    fetch_funding_page,
    parse_funding_page,
)
from candleviewer.exchange.bybit.rest import BybitRestClient
from tests._corpus import rest


def _page(**row: Any) -> dict[str, Any]:
    base = {"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": "1700006400000"}
    return {"retCode": 0, "result": {"list": [{**base, **row}]}}


def test_parse_recorded_8h_and_4h_fixtures() -> None:
    btc = parse_funding_page(rest("rest/funding_history_BTCUSDT_8h.json"), symbol="BTCUSDT")
    eth = parse_funding_page(rest("rest/funding_history_ETHUSDT_4h.json"), symbol="ETHUSDT")
    assert len(btc) == len(eth) == 4
    assert btc[0].ts_us - btc[1].ts_us == 8 * 3_600 * 1_000_000
    assert eth[0].ts_us - eth[1].ts_us == 4 * 3_600 * 1_000_000


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"result": {}},
        {"result": {"list": ["x"]}},
        _page(symbol="ETHUSDT"),
        _page(fundingRate=1),
        _page(fundingRate="abc"),
        _page(fundingRate="NaN"),
        _page(fundingRate="5"),
        _page(fundingRateTimestamp="0"),
        _page(fundingRateTimestamp="x"),
    ],
)
def test_parse_rejects_malformed_rows(payload: dict[str, Any]) -> None:
    with pytest.raises(FundingRowRejected):
        parse_funding_page(payload, symbol="BTCUSDT")


async def test_fetch_is_public_market_data_and_bounds_params() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=rest("rest/funding_history_BTCUSDT_8h.json"))

    cfg = RestClientConfig(base_url="https://api-demo.bybit.com")
    async with BybitRestClient(cfg, transport=httpx.MockTransport(handler)) as client:
        rows = await BybitFundingFetcher(client)("BTCUSDT", 1_000_000, 2_000_000, 200)
        assert len(rows) == 4
        with pytest.raises(ValueError):
            await fetch_funding_page(client, "BTCUSDT", start_us=0, end_us=1, limit=201)
        with pytest.raises(FundingRowRejected):
            await fetch_funding_page(client, "btc/usdt", start_us=0, end_us=1)
    q = dict(seen[0].url.params)
    assert q["limit"] == "200" and q["category"] == "linear"
    assert seen[0].url.path == "/v5/market/funding/history"
    assert "X-BAPI-API-KEY" not in seen[0].headers
