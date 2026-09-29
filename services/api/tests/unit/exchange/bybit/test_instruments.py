"""Unit tests for `candleviewer.exchange.bybit.instruments` (E08-S01):
Bybit `instruments-info` payload parsing into the neutral `Instrument`
model (Gherkin AC "Catalogue loaded at startup").
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.exchange.bybit.instruments import InstrumentParseError, parse_instrument

_RAW_BTCUSDT = {
    "symbol": "BTCUSDT",
    "baseCoin": "BTC",
    "quoteCoin": "USDT",
    "settleCoin": "USDT",
    "status": "Trading",
    "launchTime": "1585STUB",  # replaced per-test where needed
    "priceScale": "2",
    "priceFilter": {"tickSize": "0.10", "minPrice": "0.10", "maxPrice": "999999.00"},
    "lotSizeFilter": {
        "qtyStep": "0.001",
        "minOrderQty": "0.001",
        "maxOrderQty": "100.000",
        "maxMktOrderQty": "50.000",
        "minNotionalValue": "5",
    },
    "leverageFilter": {"minLeverage": "1", "maxLeverage": "100.00", "leverageStep": "0.01"},
    "fundingInterval": 480,
    "upperFundingRate": "0.00375",
    "lowerFundingRate": "-0.00375",
    "copyTrading": "utaOnly",
}


def _raw(**overrides: object) -> dict[str, object]:
    raw = copy.deepcopy({k: v for k, v in _RAW_BTCUSDT.items() if k != "launchTime"})
    raw["launchTime"] = "1585699200000"
    raw.update(overrides)
    return raw


def test_parse_instrument_normalises_the_documented_bybit_payload() -> None:
    inst = parse_instrument(_raw(), fetched_at_us=1_700_000_000_000_000)

    assert inst.symbol == "BTCUSDT"
    assert inst.status == "trading"
    assert inst.tick_size == Decimal("0.10")
    assert inst.qty_step == Decimal("0.001")
    assert inst.min_order_qty == Decimal("0.001")
    assert inst.max_order_qty == Decimal("100.000")
    assert inst.min_notional == Decimal("5")
    assert inst.max_leverage == Decimal("100.00")
    assert inst.funding_interval_min == 480
    assert inst.metadata_version == 1
    assert isinstance(inst.tick_size, Decimal)
    assert isinstance(inst.min_notional, Decimal)


def test_parse_instrument_maps_every_documented_status() -> None:
    for bybit_status, expected in (
        ("PreLaunch", "pre_launch"),
        ("Trading", "trading"),
        ("Delivering", "delivering"),
        ("Closed", "closed"),
    ):
        inst = parse_instrument(_raw(status=bybit_status), fetched_at_us=1)
        assert inst.status == expected


def test_parse_instrument_raises_on_missing_required_field() -> None:
    raw = _raw()
    del raw["priceFilter"]["tickSize"]  # type: ignore[index]
    with pytest.raises(InstrumentParseError, match="tickSize"):
        parse_instrument(raw, fetched_at_us=1)


def test_parse_instrument_raises_on_unknown_status() -> None:
    with pytest.raises(InstrumentParseError, match="status"):
        parse_instrument(_raw(status="SomethingNew"), fetched_at_us=1)


def test_parse_instrument_raises_on_non_decimal_tick_size() -> None:
    raw = _raw()
    raw["priceFilter"]["tickSize"] = "not-a-number"  # type: ignore[index]
    with pytest.raises(InstrumentParseError, match="tickSize"):
        parse_instrument(raw, fetched_at_us=1)


@pytest.mark.parametrize("bad_value", ["0", "-0.10", "NaN", "Infinity", "-Infinity"])
def test_parse_instrument_rejects_non_positive_or_non_finite_tick_size(bad_value: str) -> None:
    raw = _raw()
    raw["priceFilter"]["tickSize"] = bad_value  # type: ignore[index]
    with pytest.raises(InstrumentParseError, match="tickSize"):
        parse_instrument(raw, fetched_at_us=1)


@pytest.mark.parametrize("bad_value", ["0", "-0.001", "NaN", "Infinity"])
def test_parse_instrument_rejects_non_positive_or_non_finite_qty_step(bad_value: str) -> None:
    raw = _raw()
    raw["lotSizeFilter"]["qtyStep"] = bad_value  # type: ignore[index]
    with pytest.raises(InstrumentParseError, match="qtyStep"):
        parse_instrument(raw, fetched_at_us=1)


@pytest.mark.parametrize("bad_value", ["0", "-0.001", "NaN", "Infinity"])
def test_parse_instrument_rejects_non_positive_or_non_finite_min_order_qty(bad_value: str) -> None:
    raw = _raw()
    raw["lotSizeFilter"]["minOrderQty"] = bad_value  # type: ignore[index]
    with pytest.raises(InstrumentParseError, match="minOrderQty"):
        parse_instrument(raw, fetched_at_us=1)


def test_parse_instrument_rejects_non_finite_optional_decimal() -> None:
    raw = _raw()
    raw["priceFilter"]["minPrice"] = "Infinity"  # type: ignore[index]
    with pytest.raises(InstrumentParseError, match="minPrice"):
        parse_instrument(raw, fetched_at_us=1)


def test_parse_instrument_raises_parse_error_on_non_integer_price_scale() -> None:
    raw = _raw(priceScale="not-an-int")
    with pytest.raises(InstrumentParseError, match="priceScale"):
        parse_instrument(raw, fetched_at_us=1)


def test_parse_instrument_raises_parse_error_on_non_integer_funding_interval() -> None:
    raw = _raw(fundingInterval="not-an-int")
    with pytest.raises(InstrumentParseError, match="fundingInterval"):
        parse_instrument(raw, fetched_at_us=1)


@given(
    tick=st.decimals(min_value="0.00000001", max_value="1000", places=8, allow_nan=False),
    qty=st.decimals(min_value="0.00000001", max_value="1000", places=8, allow_nan=False),
)
def test_parse_instrument_never_loses_decimal_precision_for_tick_or_qty(
    tick: Decimal, qty: Decimal
) -> None:
    raw = _raw()
    raw["priceFilter"]["tickSize"] = str(tick)  # type: ignore[index]
    raw["lotSizeFilter"]["qtyStep"] = str(qty)  # type: ignore[index]
    raw["lotSizeFilter"]["maxOrderQty"] = str(qty * 1000)  # type: ignore[index]
    raw["lotSizeFilter"]["minOrderQty"] = "0.00000001"  # type: ignore[index]

    inst = parse_instrument(raw, fetched_at_us=1)

    assert inst.tick_size == tick
    assert inst.qty_step == qty
    assert isinstance(inst.tick_size, Decimal)
    assert isinstance(inst.qty_step, Decimal)
