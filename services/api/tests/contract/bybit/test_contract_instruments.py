"""E08-Q02 / E08-TC-A01..A10: `instruments-info` -> `Instrument`, delisting, tick-size change."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.domain.events import Instrument
from candleviewer.exchange.bybit.instruments import parse_instrument, parse_instruments
from tests._corpus import rest

FETCHED_US = 1_700_000_000_000_000
BEFORE = "rest/instruments_before.json"
AFTER = "rest/instruments_after.json"


def _raw(rel: str) -> list[dict[str, Any]]:
    return list(rest(rel)["result"]["list"])


def _catalogue(rel: str) -> dict[str, Instrument]:
    result = parse_instruments(_raw(rel), fetched_at_us=FETCHED_US)
    assert not result.rejected, result.rejected
    return {i.symbol: i for i in result.instruments}


def test_every_filter_field_of_the_internal_schema_is_populated_from_the_wire() -> None:
    wire = next(r for r in _raw(BEFORE) if r["symbol"] == "BTCUSDT")
    inst = parse_instrument(wire, fetched_at_us=FETCHED_US)
    pf, lf, lev = wire["priceFilter"], wire["lotSizeFilter"], wire["leverageFilter"]
    assert inst.tick_size == Decimal(pf["tickSize"]) and inst.min_price == Decimal(pf["minPrice"])
    assert inst.max_price == Decimal(pf["maxPrice"])
    assert inst.qty_step == Decimal(lf["qtyStep"])
    assert inst.min_order_qty == Decimal(lf["minOrderQty"])
    assert inst.max_order_qty == Decimal(lf["maxOrderQty"])
    assert inst.max_mkt_order_qty == Decimal(lf["maxMktOrderQty"])
    assert inst.min_notional == Decimal(lf["minNotionalValue"])
    assert inst.min_leverage == Decimal(lev["minLeverage"])
    assert inst.max_leverage == Decimal(lev["maxLeverage"])
    assert inst.leverage_step == Decimal(lev["leverageStep"])
    assert inst.funding_interval_min == wire["fundingInterval"]
    assert inst.upper_funding_rate == Decimal(wire["upperFundingRate"])
    assert inst.lower_funding_rate == Decimal(wire["lowerFundingRate"])
    assert inst.launch_time == int(wire["launchTime"]) * 1000  # ms -> us
    assert inst.price_scale == int(wire["priceScale"])
    assert (inst.exchange, inst.category, inst.contract_type) == (
        "bybit",
        "linear",
        "linear_perpetual",
    )
    assert inst.fetched_at == FETCHED_US and inst.status == "trading"
    for name in ("tick_size", "qty_step", "min_notional", "max_leverage"):
        assert isinstance(getattr(inst, name), Decimal)


def test_baseline_catalogue_is_linear_usdt_perps_with_documented_symbols() -> None:
    cat = _catalogue(BEFORE)
    assert {"BTCUSDT", "ETHUSDT", "SOLUSDT"} <= set(cat)
    assert all(i.quote_coin == "USDT" and i.settle_coin == "USDT" for i in cat.values())


def test_delisting_is_reported_as_closed_not_dropped() -> None:
    before, after = (_catalogue(rel) for rel in (BEFORE, AFTER))
    assert before["LUNAUSDT"].status == "trading" and after["LUNAUSDT"].status == "closed"
    assert set(before) == set(after)


def test_tick_size_change_is_visible_as_an_exact_decimal_delta() -> None:
    before, after = (_catalogue(rel) for rel in (BEFORE, AFTER))
    assert before["SOLUSDT"].tick_size == Decimal("0.010")
    assert after["SOLUSDT"].tick_size == Decimal("0.005")
    unchanged = [s for s in before if s != "SOLUSDT" and before[s].tick_size != after[s].tick_size]
    assert unchanged == []


def _without(path: tuple[str, ...]) -> dict[str, Any]:
    raw = copy.deepcopy(next(r for r in _raw(BEFORE) if r["symbol"] == "BTCUSDT"))
    node = raw
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return raw


@pytest.mark.parametrize(
    "path",
    [
        ("priceFilter", "tickSize"),
        ("lotSizeFilter", "qtyStep"),
        ("lotSizeFilter", "minOrderQty"),
        ("status",),
        ("launchTime",),
    ],
)
def test_missing_precision_critical_field_is_rejected_per_row_not_defaulted(
    path: tuple[str, ...],
) -> None:
    rows = _raw(BEFORE)
    bad = _without(path)
    result = parse_instruments([bad, *rows[1:2]], fetched_at_us=FETCHED_US)
    assert [r.symbol for r in result.rejected] == ["BTCUSDT"]
    assert len(result.instruments) == 1  # one bad row never fails the catalogue


@pytest.mark.parametrize("bad", ["NaN", "-0.1", "0", "abc"])
def test_non_positive_or_unparseable_tick_size_is_rejected(bad: str) -> None:
    raw = _without(("priceFilter", "tickSize"))
    raw["priceFilter"]["tickSize"] = bad
    assert parse_instruments([raw], fetched_at_us=FETCHED_US).rejected
