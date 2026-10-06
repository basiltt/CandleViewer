"""Funding-rate domain primitives (E24-T02): the ONE interval accessor and the
ONE annualisation formula.

`docs/plan/22-api-openapi.yaml` `/market/funding`: the funding interval is
instrument-specific (8 h common, some 1/2/4 h) - never assume 8 h. Every
consumer (backfill writer, API, countdown) resolves the interval through
`resolve_funding_interval_minutes` and annualises through `annualised_pct`;
no derivatives module may carry its own interval literal (CI guard:
`tests/unit/orderflow/test_funding_interval_guard.py`).

Exchange-neutral (C-2.2): no exchange field names here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, Protocol

#: Minutes in a 365-day year. The annualisation numerator (not an interval).
MINUTES_PER_YEAR: Final[int] = 525_600

#: `funding_rates.source` for rows backfilled from the settled-history endpoint.
SOURCE_HISTORY: Final[str] = "history"

#: Intervals the exchange is known to publish are not enforced here (a new
#: interval must not need a code change); only sanity bounds are.
MIN_INTERVAL_MIN: Final[int] = 1
MAX_INTERVAL_MIN: Final[int] = 24 * 60


class FundingIntervalUnknown(LookupError):
    """The instrument (or its interval) is unknown. Never defaulted at
    runtime: a wrong interval corrupts the countdown and the annualisation
    together (ticket technical notes)."""


class PredictedFundingRefused(ValueError):
    """A predicted/estimated funding value reached a settled-row writer."""


class HasFundingInterval(Protocol):
    @property
    def funding_interval_min(self) -> int: ...


def resolve_funding_interval_minutes(instrument: HasFundingInterval | None) -> int:
    """The single accessor: the instrument's `funding_interval_min`, or raise."""
    if instrument is None:
        raise FundingIntervalUnknown("instrument is not in the instruments cache")
    value = instrument.funding_interval_min
    if isinstance(value, bool) or not isinstance(value, int):
        raise FundingIntervalUnknown("instrument funding interval is not an integer")
    if not MIN_INTERVAL_MIN <= value <= MAX_INTERVAL_MIN:
        raise FundingIntervalUnknown(f"instrument funding interval {value} min is out of range")
    return value


def annualised_pct(funding_rate: Decimal, interval_min: int) -> Decimal:
    """`funding_rate * (525600 / interval_min) * 100`, in `Decimal`."""
    if not MIN_INTERVAL_MIN <= interval_min <= MAX_INTERVAL_MIN:
        raise FundingIntervalUnknown(f"funding interval {interval_min} min is out of range")
    return funding_rate * (Decimal(MINUTES_PER_YEAR) / Decimal(interval_min)) * Decimal(100)


@dataclass(frozen=True, slots=True)
class FundingSettlement:
    """A normalised settled-history print as the adapter returns it: the
    exchange gives no interval and no annualisation, so neither is carried."""

    ts_us: int
    symbol: str
    funding_rate: Decimal


@dataclass(frozen=True, slots=True)
class SettledFunding:
    """One settled funding payment. The only shape the store accepts."""

    ts_us: int
    symbol: str
    funding_rate: Decimal
    interval_min: int
    annualised_pct: Decimal
    source: str = SOURCE_HISTORY


@dataclass(frozen=True, slots=True)
class PredictedFunding:
    """The current, unsettled, accruing rate. Never persisted."""

    ts_us: int
    symbol: str
    funding_rate: Decimal
    predicted: Literal[True] = True
    estimated: Literal[True] = True


def settle(symbol: str, ts_us: int, funding_rate: Decimal, interval_min: int) -> SettledFunding:
    """Build a settled row, computing `annualised_pct` at write time."""
    return SettledFunding(
        ts_us=ts_us,
        symbol=symbol,
        funding_rate=funding_rate,
        interval_min=interval_min,
        annualised_pct=annualised_pct(funding_rate, interval_min),
    )


__all__ = [
    "MAX_INTERVAL_MIN",
    "MINUTES_PER_YEAR",
    "MIN_INTERVAL_MIN",
    "SOURCE_HISTORY",
    "FundingIntervalUnknown",
    "FundingSettlement",
    "HasFundingInterval",
    "PredictedFunding",
    "PredictedFundingRefused",
    "SettledFunding",
    "annualised_pct",
    "resolve_funding_interval_minutes",
    "settle",
]
