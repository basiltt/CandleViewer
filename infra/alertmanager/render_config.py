#!/usr/bin/env python3
"""E04-T05: render alertmanager.yml with the quiet-hours window from CV_ALERT_QUIET_HOURS.

Stdlib only (runs in the pinned python init container before Alertmanager starts,
because Alertmanager does not expand env vars). The committed alertmanager.yml is the
default render (22:00-07:00 UTC) and stays a valid config on its own; this script only
rewrites the block between the `# BEGIN quiet_hours` / `# END quiet_hours` markers.

    CV_ALERT_QUIET_HOURS="HH:MM-HH:MM"   (UTC; a start later than end wraps midnight)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

DEFAULT = "22:00-07:00"
BEGIN, END = "# BEGIN quiet_hours", "# END quiet_hours"
_SPEC = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")


class QuietHoursError(ValueError):
    """CV_ALERT_QUIET_HOURS is malformed or empty."""


def parse(spec: str) -> list[tuple[str, str]]:
    """Return Alertmanager `times` ranges (start inclusive, end exclusive) for the window."""
    m = _SPEC.match(spec.strip())
    if not m:
        raise QuietHoursError(f"CV_ALERT_QUIET_HOURS must be HH:MM-HH:MM, got {spec!r}")
    start, end = f"{m[1]}:{m[2]}", f"{m[3]}:{m[4]}"
    if start == end:
        raise QuietHoursError("CV_ALERT_QUIET_HOURS start and end must differ")
    if start < end:
        return [(start, end)]
    ranges = [(start, "24:00")]
    if end != "00:00":
        ranges.append(("00:00", end))
    return ranges


def block(ranges: list[tuple[str, str]]) -> str:
    lines = [BEGIN, "  - name: quiet_hours", "    time_intervals:", "      - times:"]
    for s, e in ranges:
        lines += [f'          - start_time: "{s}"', f'            end_time: "{e}"']
    return "\n".join(lines + [END])


def render(template: str, spec: str) -> str:
    i, j = template.index(BEGIN), template.index(END) + len(END)
    return template[:i] + block(parse(spec)) + template[j:]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: render_config.py <in alertmanager.yml> <out alertmanager.yml>",
            file=sys.stderr,
        )
        return 2
    spec = os.environ.get("CV_ALERT_QUIET_HOURS") or DEFAULT
    try:
        out = render(Path(argv[0]).read_text(encoding="utf-8"), spec)
    except QuietHoursError as e:
        print(str(e), file=sys.stderr)
        return 1
    Path(argv[1]).write_text(out, encoding="utf-8", newline="\n")
    print(f"alertmanager config rendered; quiet hours {spec} UTC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
