from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.domain.funding import (
    FundingIntervalUnknown,
    annualised_pct,
    resolve_funding_interval_minutes,
    settle,
)


@dataclass(frozen=True)
class _Inst:
    funding_interval_min: int


@pytest.mark.parametrize(
    ("interval", "expected"), [(60, "8760"), (120, "4380"), (240, "2190"), (480, "1095")]
)
def test_annualised_pct_uses_resolved_interval(interval: int, expected: str) -> None:
    assert annualised_pct(Decimal("0.01"), interval) == Decimal(expected) * Decimal("0.01") * 100


def test_annualised_pct_240_is_not_480() -> None:
    rate = Decimal("0.0001")
    assert annualised_pct(rate, 240) == rate * Decimal(525600) / 240 * 100
    assert annualised_pct(rate, 240) == 2 * annualised_pct(rate, 480)


@given(
    interval=st.sampled_from([60, 120, 240, 480]),
    rate=st.decimals(min_value=Decimal("-0.01"), max_value=Decimal("0.01"), places=8),
)
def test_property_annualisation_matches_formula_for_any_interval(
    interval: int, rate: Decimal
) -> None:
    row = settle("BTCUSDT", 1_000_000, rate, interval)
    assert row.interval_min == interval
    assert row.annualised_pct == rate * (Decimal(525600) / Decimal(interval)) * 100


def test_resolve_returns_instrument_value() -> None:
    assert resolve_funding_interval_minutes(_Inst(240)) == 240


@pytest.mark.parametrize("bad", [0, -5, 24 * 60 + 1])
def test_resolve_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(FundingIntervalUnknown):
        resolve_funding_interval_minutes(_Inst(bad))


def test_resolve_raises_on_unknown_instrument_never_defaults() -> None:
    with pytest.raises(FundingIntervalUnknown):
        resolve_funding_interval_minutes(None)


def test_resolve_rejects_non_int() -> None:
    with pytest.raises(FundingIntervalUnknown):
        resolve_funding_interval_minutes(_Inst(True))
    with pytest.raises(FundingIntervalUnknown):
        resolve_funding_interval_minutes(_Inst("480"))  # type: ignore[arg-type]  # deliberately wrong type


def test_annualised_pct_rejects_bad_interval() -> None:
    with pytest.raises(FundingIntervalUnknown):
        annualised_pct(Decimal(1), 0)
