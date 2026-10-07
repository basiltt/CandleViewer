"""E12-S05 / SR-E12-09 (BR-02): strict `/v5/market/kline` page validation.

Inputs are the recorded corpus pages `rest/kline_BTCUSDT_1_page{0,1,2}.json` (C-13.5); the
tampered variants are derived from them in-test (one field mutated), never invented shapes.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.domain.klines import KlinePageRejected
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.klines import (
    PATH,
    BybitKlineFetcher,
    fetch_kline_page,
    parse_kline_page,
)
from tests._corpus import rest

PAGE0 = rest("rest/kline_BTCUSDT_1_page0.json")
NOW_MS = 1_700_100_000_000  # after every corpus bar closed
TICK = Decimal("0.1")


def _page(**overrides: Any) -> dict[str, Any]:
    page: dict[str, Any] = copy.deepcopy(PAGE0)
    return page | overrides


def _mutate(row: int, col: int, value: str) -> dict[str, Any]:
    page = _page()
    page["result"]["list"][row][col] = value
    return page


def _parse(payload: dict[str, Any], **kw: Any) -> list[Any]:
    return parse_kline_page(
        payload, symbol="BTCUSDT", interval="1", tick_size=TICK, now_ms=NOW_MS, **kw
    )


def test_parse_kline_page_corpus_page_is_ascending_and_confirmed() -> None:
    events = _parse(_page())
    starts = [e.start for e in events]
    assert len(events) == 200
    assert starts == sorted(starts)
    assert starts[0] == 1_700_015_000_000_000
    assert all(e.end == e.start + 60_000_000 - 1 for e in events)
    assert all(e.confirmed and e.source == "backfill" for e in events)


def test_parse_kline_page_forming_bar_is_unconfirmed() -> None:
    newest_ms = int(PAGE0["result"]["list"][0][0])
    events = parse_kline_page(_page(), symbol="BTCUSDT", interval="1", now_ms=newest_ms + 1)
    assert events[-1].confirmed is False
    assert all(e.confirmed for e in events[:-1])


@pytest.mark.parametrize(
    ("row", "col", "value", "reason"),
    [
        (3, 2, "62000.0", "high_below_body"),  # high < max(o, c)
        (3, 3, "62999.0", "low_above_body"),  # low > min(o, c)
        (3, 5, "-1", "negative_volume"),
        (3, 6, "-5", "negative_volume"),
        (3, 1, "62902.05", "off_tick"),
        (3, 4, "0", "non_positive_price"),
        (3, 0, "1700026760001", "misaligned_time"),
        (0, 0, "1700026999999", "misaligned_time"),
        (3, 0, "abc", "unparseable"),
        (3, 1, "NaN", "unparseable"),
        (3, 1, "x", "unparseable"),
    ],
)
def test_parse_kline_page_tampered_row_rejects_whole_page(
    row: int, col: int, value: str, reason: str
) -> None:
    with pytest.raises(KlinePageRejected) as info:
        _parse(_mutate(row, col, value))
    assert info.value.reason == reason


def test_parse_kline_page_non_monotonic_rejected() -> None:
    page = _page()
    rows = page["result"]["list"]
    rows[1], rows[2] = rows[2], rows[1]
    with pytest.raises(KlinePageRejected) as info:
        _parse(page)
    assert info.value.reason == "non_monotonic"


def test_parse_kline_page_duplicate_open_time_rejected() -> None:
    page = _page()
    page["result"]["list"][1] = list(page["result"]["list"][0])
    with pytest.raises(KlinePageRejected, match="newest-first"):
        _parse(page)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"retCode": 0}, "envelope"),
        ({"result": {"symbol": "BTCUSDT"}}, "envelope"),
        ({"result": {"symbol": "ETHUSDT", "list": []}}, "symbol_mismatch"),
        ({"result": {"list": [["1", "2"]]}}, "row_shape"),
        ({"result": {"list": [[1700026940000, "1", "1", "1", "1", "1", "1"]]}}, "unparseable"),
        ({"result": {"list": [["1700026940000", 1, "1", "1", "1", "1", "1"]]}}, "row_shape"),
    ],
)
def test_parse_kline_page_bad_envelope_rejected(payload: dict[str, Any], reason: str) -> None:
    with pytest.raises(KlinePageRejected) as info:
        _parse(payload)
    assert info.value.reason == reason


def test_parse_kline_page_month_interval_not_backfillable() -> None:
    with pytest.raises(KlinePageRejected):
        parse_kline_page(_page(), symbol="BTCUSDT", interval="M")


def test_parse_kline_page_without_tick_skips_only_tick_check() -> None:
    events = parse_kline_page(
        _mutate(3, 1, "62902.05"), symbol="BTCUSDT", interval="1", now_ms=NOW_MS
    )
    assert len(events) == 200


def test_kline_page_rejected_unknown_reason_is_bounded() -> None:
    assert KlinePageRejected("x", "free text").reason == "envelope"


class _Client:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any], EndpointClass]] = []

    async def get_public(
        self, path: str, *, params: dict[str, Any], endpoint_class: EndpointClass
    ) -> dict[str, Any]:
        self.calls.append((path, params, endpoint_class))
        return self.payload


async def test_fetch_kline_page_uses_public_market_data_bucket() -> None:
    client = _Client(_page())
    events = await fetch_kline_page(
        client,  # type: ignore[arg-type]  # structural fake of the governed client
        "BTCUSDT",
        "1",
        start_us=1_700_015_000_000_000,
        end_us=1_700_026_940_000_000,
        tick_size=TICK,
    )
    assert len(events) == 200
    path, params, bucket = client.calls[0]
    assert path == PATH
    assert bucket is EndpointClass.MARKET_DATA
    assert params == {
        "category": "linear",
        "symbol": "BTCUSDT",
        "interval": "1",
        "start": 1_700_015_000_000,
        "end": 1_700_026_940_000,
        "limit": 1000,
    }


@pytest.mark.parametrize(
    ("symbol", "interval", "limit", "exc"),
    [
        ("btc/../x", "1", 10, KlinePageRejected),
        ("BTCUSDT", "M", 10, KlinePageRejected),
        ("BTCUSDT", "1", 1001, ValueError),
        ("BTCUSDT", "1", 0, ValueError),
    ],
)
async def test_fetch_kline_page_rejects_bad_inputs_before_any_call(
    symbol: str, interval: str, limit: int, exc: type[Exception]
) -> None:
    client = _Client(_page())
    with pytest.raises(exc):
        await fetch_kline_page(
            client, symbol, interval, start_us=0, end_us=1, limit=limit  # type: ignore[arg-type]
        )
    assert client.calls == []


async def test_bybit_kline_fetcher_applies_catalogue_tick() -> None:
    client = _Client(_mutate(3, 1, "62902.05"))
    fetcher = BybitKlineFetcher(client, tick_size_for=lambda s: TICK)  # type: ignore[arg-type]
    with pytest.raises(KlinePageRejected):
        await fetcher("BTCUSDT", "1", 0, 1)
    plain = BybitKlineFetcher(_Client(_page()))  # type: ignore[arg-type]
    assert len(await plain("BTCUSDT", "1", 0, 1)) == 200
