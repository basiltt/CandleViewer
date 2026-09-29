"""Bybit `instruments-info` (`category=linear`) parsing (C-2.2: all Bybit
vocabulary — `tickSize`, `qtyStep`, `lotSizeFilter`, ... — lives only here).

`candleviewer.ingestion.instruments` consumes the neutral `Instrument` model
this module returns; it never sees a raw Bybit field name.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from candleviewer.domain.events import Instrument

_STATUS_MAP: dict[str, Literal["pre_launch", "trading", "delivering", "closed"]] = {
    "PreLaunch": "pre_launch",
    "Trading": "trading",
    "Delivering": "delivering",
    "Closed": "closed",
}


class InstrumentParseError(ValueError):
    """A raw `instruments-info` list item is missing a required field or has
    a value that cannot be coerced to the expected type. Raised per-item so
    a caller can decide whether one bad row should fail the whole refresh
    or just be skipped-and-logged; this module does not decide that policy."""


def _decimal(raw: Mapping[str, Any], key: str) -> Decimal:
    value = raw.get(key)
    if value is None or value == "":
        raise InstrumentParseError(f"missing required field {key!r}")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise InstrumentParseError(f"field {key!r} is not a valid decimal: {value!r}") from exc


def _optional_decimal(raw: Mapping[str, Any], key: str, default: Decimal) -> Decimal:
    value = raw.get(key)
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise InstrumentParseError(f"field {key!r} is not a valid decimal: {value!r}") from exc


def parse_instrument(raw: Mapping[str, Any], *, fetched_at_us: int) -> Instrument:
    """Normalise one Bybit `instruments-info` (`category=linear`) list item
    into the neutral `Instrument` model. Raises `InstrumentParseError` on any
    missing/malformed required field rather than silently defaulting
    precision-critical values (native-SL/order-validation depends on these
    being exact — C-2.2 adapter rule, ticket "Technical notes").
    """
    try:
        symbol = raw["symbol"]
        status_raw = raw["status"]
        launch_time_ms = int(raw["launchTime"])
    except KeyError as exc:
        raise InstrumentParseError(f"missing required field {exc.args[0]!r}") from exc
    except (TypeError, ValueError) as exc:
        raise InstrumentParseError(
            f"launchTime is not an integer: {raw.get('launchTime')!r}"
        ) from exc

    status = _STATUS_MAP.get(status_raw)
    if status is None:
        raise InstrumentParseError(f"unknown instrument status: {status_raw!r}")

    price_filter = raw.get("priceFilter") or {}
    lot_size_filter = raw.get("lotSizeFilter") or {}
    leverage_filter = raw.get("leverageFilter") or {}
    funding_cfg = raw.get("fundingInterval")

    return Instrument(
        exchange="bybit",
        category="linear",
        symbol=symbol,
        base_coin=raw.get("baseCoin", ""),
        quote_coin=raw.get("quoteCoin", "USDT"),
        settle_coin=raw.get("settleCoin", "USDT"),
        status=status,
        contract_type="linear_perpetual",
        launch_time=launch_time_ms * 1000,
        tick_size=_decimal(price_filter, "tickSize"),
        price_scale=int(raw.get("priceScale", 2)),
        min_price=_optional_decimal(price_filter, "minPrice", Decimal(0)),
        max_price=_optional_decimal(price_filter, "maxPrice", Decimal(0)),
        qty_step=_decimal(lot_size_filter, "qtyStep"),
        min_order_qty=_decimal(lot_size_filter, "minOrderQty"),
        max_order_qty=_decimal(lot_size_filter, "maxOrderQty"),
        max_mkt_order_qty=_optional_decimal(
            lot_size_filter, "maxMktOrderQty", _decimal(lot_size_filter, "maxOrderQty")
        ),
        min_notional=_optional_decimal(lot_size_filter, "minNotionalValue", Decimal(0)),
        max_leverage=_decimal(leverage_filter, "maxLeverage"),
        min_leverage=_optional_decimal(leverage_filter, "minLeverage", Decimal(1)),
        leverage_step=_optional_decimal(leverage_filter, "leverageStep", Decimal("0.01")),
        funding_interval_min=int(funding_cfg) if funding_cfg is not None else 480,
        upper_funding_rate=(
            _decimal(raw, "upperFundingRate")
            if raw.get("upperFundingRate") is not None
            else Decimal(0)
        ),
        lower_funding_rate=(
            _decimal(raw, "lowerFundingRate")
            if raw.get("lowerFundingRate") is not None
            else Decimal(0)
        ),
        copy_trading=bool(raw.get("copyTrading", False) not in (False, "None", "none")),
        metadata_version=1,
        fetched_at=fetched_at_us,
    )
