"""Fixtures for cv-bybit-category-required (E12-X03, SR-054).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""


async def kline_without_category(client, symbol):
    return await client.get_public("/v5/market/kline", params={"symbol": symbol, "interval": "1"})  # ruleid: cv-bybit-category-required


async def kline_wrong_category(client, symbol):
    return await client.get_public("/v5/market/kline", params={"category": "spot", "symbol": symbol})  # ruleid: cv-bybit-category-required


async def order_without_category(client, symbol):
    return await client.signed_request("POST", "/v5/order/create", body={"symbol": symbol})  # ruleid: cv-bybit-category-required


async def tickers_no_params(client):
    return await client.get_public("/v5/market/tickers")  # ruleid: cv-bybit-category-required


async def params_var_without_category(client, symbol):
    params = {"symbol": symbol, "limit": 1000}  # ruleid: cv-bybit-category-required
    return await client.get_public("/v5/market/recent-trade", params=params)


async def kline_ok(client, symbol):
    return await client.get_public("/v5/market/kline", params={"category": "linear", "symbol": symbol})  # ok: cv-bybit-category-required


async def order_ok(client, symbol):
    return await client.signed_request("POST", "/v5/order/create", body={"category": "linear", "symbol": symbol})  # ok: cv-bybit-category-required


async def params_var_ok(get_public, symbol):
    params = {"category": "linear", "symbol": symbol, "limit": 1000}  # ok: cv-bybit-category-required
    return await get_public("/v5/market/recent-trade", params=params)


def unrelated_dict_ok(symbol):
    params = {"symbol": symbol}  # ok: cv-bybit-category-required
    return params


async def server_time_ok(client):
    return await client.get_public("/v5/market/time")  # ok: cv-bybit-category-required
