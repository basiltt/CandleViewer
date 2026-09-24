"""Single source of truth for the sprint calendar.

Owner decision 2026-09-24: development is AI-driven (Claude Code, parallel
agents), so the cadence is **1-week sprints, 7 calendar days, Fri -> Thu**,
Sprint 01 starting Fri 2026-09-25.  Story points per sprint are unchanged
(90 eng pts; S07 = 45); only the calendar is compressed.

Old (human) calendar for reference: 2-week sprints from Mon 2026-09-28.
"""
import datetime
import re

SPRINT01_START = datetime.date(2026, 9, 25)   # Friday
SPRINT_DAYS = 7
LAST_SPRINT = 26

_OLD_START = datetime.date(2026, 9, 28)
_OLD_DAYS = 14


def sprint_num(label):
    if not label:
        return None
    m = re.search(r"(\d+)", str(label))
    return int(m.group(1)) if m else None


def sprint_range(n):
    start = SPRINT01_START + datetime.timedelta(days=(n - 1) * SPRINT_DAYS)
    end = start + datetime.timedelta(days=SPRINT_DAYS - 1)
    return start, end


def sprint_dates(label):
    n = sprint_num(label)
    if n is None:
        return None, None
    s, e = sprint_range(n)
    return s.isoformat(), e.isoformat()


def old_to_new(d):
    """Map a date on the old 2-week calendar to the new 1-week one.

    Sprint starts map to sprint starts; the old Friday end (day 11) maps to
    the new Thursday end (day 6); other days scale proportionally.
    """
    if isinstance(d, str):
        d = datetime.date.fromisoformat(d)
    delta = (d - _OLD_START).days
    n, off = divmod(delta, _OLD_DAYS)
    if off >= 11:
        off = 6
    else:
        off = round(off * 6 / 11)
    return SPRINT01_START + datetime.timedelta(days=n * SPRINT_DAYS + off)


def train_range(first_sprint, last_sprint):
    return sprint_range(first_sprint)[0], sprint_range(last_sprint)[1]


if __name__ == "__main__":
    for n in (1, 4, 7, 10, 14, 18, 22, 26):
        s, e = sprint_range(n)
        print(f"S{n:02d} {s} -> {e}")
    print("GA:", sprint_range(LAST_SPRINT)[1])
