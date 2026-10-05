"""Zero-crossing forecasts for the GA burn-down (pure functions, no I/O).

The tracked quantity is *excess open* defects: P0 + P1 + max(P2 - 10, 0), which is exactly zero
when the R5 exit criteria (docs/plan/30-release-roadmap.md section 9.3 item 3) are met. A forecast
that cannot be defended returns an explicit undefined result with a reason, never a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

#: R5 exit numbers (roadmap 9.3 item 3); the dashboard target line is checked against these.
EXIT_P2_MAX = 10
MIN_SPAN_DAYS = 7
WINDOW_DAYS = 21

Point = tuple[date, float]


@dataclass(frozen=True)
class Forecast:
    """`when` is None exactly when the forecast is undefined; `reason` always says why."""

    when: date | None
    reason: str  # ok | zero-reached | insufficient-data | not-converging


def excess_open(p0: int, p1: int, p2: int) -> int:
    return p0 + p1 + max(p2 - EXIT_P2_MAX, 0)


def _window(points: list[Point]) -> list[Point]:
    ordered = sorted(points)
    if not ordered:
        return []
    start = ordered[-1][0] - timedelta(days=WINDOW_DAYS)
    return [p for p in ordered if p[0] >= start]


def _undefined(reason: str) -> Forecast:
    return Forecast(None, reason)


def linear_zero_date(points: list[Point]) -> Forecast:
    """Least-squares line over the trailing 3 weeks; needs >=3 points spanning >=7 days."""
    win = _window(points)
    if win and win[-1][1] <= 0:
        return Forecast(win[-1][0], "zero-reached")
    if len(win) < 3 or (win[-1][0] - win[0][0]).days < MIN_SPAN_DAYS:
        return _undefined("insufficient-data")
    xs = [float((d - win[0][0]).days) for d, _ in win]
    ys = [v for _, v in win]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    if slope >= 0:
        return _undefined("not-converging")
    last_fit = my + slope * (xs[-1] - mx)
    if last_fit <= 0:  # fit already at/below zero though the latest observation is not
        return Forecast(win[-1][0], "ok")
    return Forecast(win[-1][0] + timedelta(days=round(last_fit / -slope)), "ok")


def trailing_rate_zero_date(points: list[Point]) -> Forecast:
    """Naive projection of the mean net burn rate over the trailing 3 weeks."""
    win = _window(points)
    if win and win[-1][1] <= 0:
        return Forecast(win[-1][0], "zero-reached")
    if len(win) < 2 or (win[-1][0] - win[0][0]).days < MIN_SPAN_DAYS:
        return _undefined("insufficient-data")
    days = (win[-1][0] - win[0][0]).days
    rate = (win[0][1] - win[-1][1]) / days  # defects closed net per day
    if rate <= 0:
        return _undefined("not-converging")
    return Forecast(win[-1][0] + timedelta(days=round(win[-1][1] / rate)), "ok")


def days_to_zero(fc: Forecast, today: date) -> int | None:
    return None if fc.when is None else (fc.when - today).days
