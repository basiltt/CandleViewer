"""Fixtures for cv-untrusted-exchange-response (E12-X03, SR-040).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""


async def backfill_bad(client, symbol):
    payload = await client.get_public("/v5/market/kline", params={"category": "linear"})
    rows = payload["result"]  # ruleid: cv-untrusted-exchange-response
    return rows


async def status_bad(response):
    if response.get("retCode") != 0:  # ruleid: cv-untrusted-exchange-response
        raise RuntimeError


async def json_bad(http, url):
    response = await http.get(url)
    return response.json()  # ruleid: cv-untrusted-exchange-response


async def backfill_ok(adapter, symbol, rng):
    page = await adapter.fetch_klines(symbol, "1", rng)  # ok: cv-untrusted-exchange-response
    return [bar.close for bar in page.bars]


def domain_ok(bar):
    return bar.result_code if bar.confirmed else None  # ok: cv-untrusted-exchange-response
