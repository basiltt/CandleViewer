"""Business-hours SLA arithmetic (docs/plan/03-testing-strategy.md §11.3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
AT_RISK_FRACTION = 0.75


@dataclass(frozen=True)
class Calendar:
    tz: ZoneInfo
    working_days: frozenset[int]
    start: time
    end: time
    holidays: frozenset[date]

    @property
    def day_minutes(self) -> int:
        return (self.end.hour - self.start.hour) * 60 + (self.end.minute - self.start.minute)


def _hm(text: str) -> time:
    hour, minute = text.split(":")
    return time(int(hour), int(minute))


def calendar_from_dict(raw: dict[str, object]) -> Calendar:
    days = raw.get("working_days", _DAYS[:5])
    return Calendar(
        tz=ZoneInfo(str(raw.get("timezone", "UTC"))),
        working_days=frozenset(_DAYS.index(str(d)[:3].title()) for d in days),  # type: ignore[attr-defined]
        start=_hm(str(raw.get("work_start", "09:00"))),
        end=_hm(str(raw.get("work_end", "17:00"))),
        holidays=frozenset(date.fromisoformat(str(h)) for h in raw.get("holidays", []) or []),  # type: ignore[attr-defined]
    )


def load_calendar(path: str | Path) -> Calendar:
    import yaml

    return calendar_from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


# Triage windows in business minutes; sprint = 5 business days (1-week sprints).
def window_minutes(severity: str, cal: Calendar) -> int:
    day = cal.day_minutes
    table = {"P0": 120, "P1": day, "P2": 3 * day, "P3": 5 * day}
    return table[severity.upper()]


def _windows(cal: Calendar, frm: datetime, days: int = 400):
    d = frm.astimezone(cal.tz).date()
    for _ in range(days):
        if d.weekday() in cal.working_days and d not in cal.holidays:
            yield (
                datetime.combine(d, cal.start, cal.tz),
                datetime.combine(d, cal.end, cal.tz),
            )
        d += timedelta(days=1)


def business_minutes_between(opened: datetime, now: datetime, cal: Calendar) -> float:
    total = 0.0
    if now <= opened:
        return total
    for ws, we in _windows(cal, opened, days=800):
        if ws >= now:
            break
        lo, hi = max(ws, opened), min(we, now)
        if hi > lo:
            total += (hi - lo).total_seconds() / 60
    return total


def deadline(opened: datetime, minutes: float, cal: Calendar) -> datetime:
    """Instant at which `minutes` business minutes have elapsed since `opened`."""
    remaining = float(minutes)
    last = opened
    for ws, we in _windows(cal, opened):
        lo = max(ws, opened)
        if we <= lo:
            continue
        span = (we - lo).total_seconds() / 60
        if remaining <= span:
            return lo + timedelta(minutes=remaining)
        remaining -= span
        last = we
    return last


def classify(severity: str, opened: datetime, now: datetime, cal: Calendar) -> str:
    """Return 'ok' | 'sla-at-risk' | 'sla-breached' for an untriaged bug."""
    window = window_minutes(severity, cal)
    used = business_minutes_between(opened, now, cal)
    if used > window:
        return "sla-breached"
    if used >= AT_RISK_FRACTION * window:
        return "sla-at-risk"
    return "ok"
