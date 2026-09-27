"""E02-T09 acceptance: generated pydantic models preserve Decimal precision
(never coerce to float) and parse timestamps/epoch-millis fields per
convention C6/C7 — round-tripping to the wire-format JSON the contract
requires.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from candleviewer.api._generated.rest_models import Bar
from candleviewer.ws._generated.ws_models import Metric, Series


def _bar_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "t": "2026-09-27T00:00:00Z",
        "o": "63120.50",
        "h": "63200.00",
        "l": "63100.00",
        "c": "63180.25",
        "v": "12.345678901234567890",
    }
    payload.update(overrides)
    return payload


def test_rest_bar_decimal_field_round_trips_without_float_coercion() -> None:
    bar = Bar.model_validate(_bar_payload(delta="-0.00040000000000000001"))

    assert isinstance(bar.delta, Decimal)
    assert bar.delta == Decimal("-0.00040000000000000001")
    # A float would have lost precision on the 17th+ significant digit.
    assert str(bar.delta) != str(float("-0.00040000000000000001"))

    dumped = bar.model_dump(mode="json")
    assert dumped["delta"] == "-0.00040000000000000001"
    assert isinstance(dumped["delta"], str)


def test_rest_bar_open_time_parses_as_aware_datetime_rfc3339() -> None:
    bar = Bar.model_validate(_bar_payload())
    assert bar.t == datetime(2026, 9, 27, tzinfo=UTC)
    assert bar.t.tzinfo is not None


def test_ws_series_decimal_field_round_trips_without_float_coercion() -> None:
    series = Series.model_validate(
        {"metric": Metric.vwap, "t_ms": 1_700_000_000_000, "v": "0.1000000000000000055511151"}
    )
    assert isinstance(series.v, Decimal)
    assert series.v == Decimal("0.1000000000000000055511151")

    dumped = series.model_dump(mode="json")
    assert dumped["v"] == "0.1000000000000000055511151"


def test_ws_series_epoch_ms_field_is_a_plain_int() -> None:
    series = Series.model_validate({"metric": Metric.vwap, "t_ms": 1_700_000_000_000, "v": "1"})
    assert series.t_ms == 1_700_000_000_000
    assert isinstance(series.t_ms, int)


@pytest.mark.parametrize("bad", ["not-a-number", "1.2.3", ""])
def test_decimal_field_rejects_non_numeric_strings(bad: str) -> None:
    with pytest.raises(ValidationError):
        Bar.model_validate(_bar_payload(delta=bad))
