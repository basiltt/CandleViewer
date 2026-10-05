"""CLI: ``ledger`` (CSV -> pushgateway), ``defects`` (GitHub bugs -> pushgateway), ``snapshot``.

All network goes through injected callables so tests run offline. Credentials: only
GH_TOKEN (read-only issues) and PUSHGATEWAY_URL; no secret is ever logged.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.ga_defects import forecast as fc
from tools.ga_defects import ledger, metrics
from tools.triage import dor

LEDGER_PATH = Path("docs/plan/backlog/artifacts/e49-design-qa-ledger.csv")
LOG_PATH = Path("docs/plan/backlog/artifacts/e49-triage-log.md")
WEEKLY_MARKER = "<!-- ga-defects:weekly {day} -->"
EXIT_NO_PUSH = 2  # --require-push and PUSHGATEWAY_URL unset
EXIT_LEDGER_SCHEMA = 3
GA_DATE = date(2027, 3, 25)  # S26 boundary, docs/plan/backlog/_tools/calendar_cv.py


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _sev(issue: dict[str, Any]) -> str | None:
    return dor.severity_of(
        issue.get("body") or "", [x["name"] for x in issue["labels"]]
    )


def _labels(issue: dict[str, Any]) -> set[str]:
    return {x["name"] for x in issue["labels"]}


def history(
    issues: list[dict[str, Any]], today: date, days: int = 21
) -> list[fc.Point]:
    """Reconstruct the daily excess-open series from created/closed timestamps."""
    pts: list[fc.Point] = []
    for back in range(days, -1, -1):
        day = today - timedelta(days=back)
        end = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)
        n = {"P0": 0, "P1": 0, "P2": 0}
        for i in issues:
            sev = _sev(i)
            closed = i.get("closed_at")
            if (
                sev in n
                and _ts(i["created_at"]) <= end
                and (not closed or _ts(closed) > end)
            ):
                n[sev] += 1
        pts.append((day, float(fc.excess_open(n["P0"], n["P1"], n["P2"]))))
    return pts


def build_snapshot(
    issues: list[dict[str, Any]], now: datetime, sla_of: Callable[[dict[str, Any]], str]
) -> metrics.DefectSnapshot:
    snap = metrics.DefectSnapshot()
    snap.open_by_severity = dict.fromkeys(ledger.SEVERITIES, 0)
    week_ago = now - timedelta(days=7)
    for i in issues:
        if _ts(i["created_at"]) >= week_ago:
            snap.arrived_7d += 1
        if i.get("closed_at") and _ts(i["closed_at"]) >= week_ago:
            snap.closed_7d += 1
        if i.get("closed_at"):
            continue
        sev, labs = _sev(i) or "unknown", _labels(i)
        snap.open_by_severity[sev] = snap.open_by_severity.get(sev, 0) + 1
        for lab in sorted(labs):
            if lab.startswith("area/"):
                comp = lab[5:]
                snap.open_by_component[comp] = snap.open_by_component.get(comp, 0) + 1
        if "triaged" not in labs:
            snap.untriaged += 1
        state = sla_of(i)
        if state != "ok":
            snap.sla[(sev, state)] = snap.sla.get((sev, state), 0) + 1
        age = (now - _ts(i["created_at"])).total_seconds() / 86400
        snap.ages_days.setdefault(sev, []).append(age)
    pts = history(issues, now.date())
    for name, f in (
        ("linear", fc.linear_zero_date(pts)),
        ("trailing_3w", fc.trailing_rate_zero_date(pts)),
    ):
        d = fc.days_to_zero(f, now.date())
        if d is not None:
            snap.forecast_days[name] = (
                d  # undefined => series omitted, dashboard shows "n/a"
            )
    return snap


def weekly_section(snap: metrics.DefectSnapshot, now: datetime, ga: date) -> str:
    day = now.date().isoformat()
    sev = ", ".join(f"{k}={v}" for k, v in sorted(snap.open_by_severity.items()))
    lines = [
        WEEKLY_MARKER.format(day=day),
        f"## GA defect snapshot {day} (automated, E49-T02)",
        "",
        f"- Open by severity: {sev}",
        f"- Arrived/closed (7d): {snap.arrived_7d}/{snap.closed_7d}; untriaged: {snap.untriaged}",
    ]
    for m in ("linear", "trailing_3w"):
        d = snap.forecast_days.get(m)
        lines.append(
            f"- Forecast {m}: "
            + (
                f"{(now.date() + timedelta(days=d)).isoformat()} ({d} d)"
                if d is not None
                else "undefined"
            )
        )
    lines += [f"- GA target: {ga.isoformat()} (S26 boundary)", ""]
    return "\n".join(lines)


def append_weekly(log: Path, section: str, day: str) -> bool:
    """Idempotent per day: returns False when this day's snapshot is already present."""
    text = log.read_text(encoding="utf-8")
    if WEEKLY_MARKER.format(day=day) in text:
        return False
    log.write_text(text.rstrip("\n") + "\n\n" + section, encoding="utf-8")
    return True


def _push_or_skip(url: str, job: str, text: str, transport: metrics.Transport) -> bool:
    """Push when a URL is configured; otherwise emit an explicit notice and return False."""
    if not url:
        print("::notice::PUSHGATEWAY_URL not set; metrics push skipped")
        return False
    metrics.push(url, job, text, transport)
    return True


def cmd_ledger(
    path: Path, url: str, transport: metrics.Transport, require_push: bool = False
) -> int:
    try:
        counts = ledger.parse_ledger(path)
    except ValueError as exc:
        print(f"E_LEDGER_SCHEMA: {exc}", file=sys.stderr)
        return EXIT_LEDGER_SCHEMA
    if counts is None:
        print(f"E_LEDGER_MISSING: {path} not found; nothing pushed", file=sys.stderr)
        return 1
    if counts.malformed_rows:
        print(
            f"warning: {counts.malformed_rows} malformed ledger row(s) skipped",
            file=sys.stderr,
        )
    if not _push_or_skip(
        url,
        "design_qa_ledger",
        metrics.render_ledger(counts.open_by_severity),
        transport,
    ):
        return EXIT_NO_PUSH if require_push else 0
    return 0


def fetch_bugs(api: Any) -> list[dict[str, Any]]:
    """All type/bug issues (open and closed in the last 28 days) via the triage GhApi."""
    since = (datetime.now(timezone.utc) - timedelta(days=28)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    # `since` filters on updated_at: applying it to open issues would drop old untouched bugs.
    out: list[dict[str, Any]] = []
    for state in ("open", "closed"):
        page = 1
        while True:
            q = f"/issues?state={state}&labels=type/bug&per_page=100&page={page}"
            if state == "closed":
                q += f"&since={since}"
            batch = api.call("GET", q) or []
            out += [i for i in batch if "pull_request" not in i]
            if len(batch) < 100:
                break
            page += 1
    return out


def cmd_defects(
    api: Any,
    url: str,
    transport: metrics.Transport,
    log: Path | None,
    ga: date,
    require_push: bool = False,
) -> int:
    from tools.triage import sla

    cal = sla.load_calendar(
        os.environ.get("TRIAGE_CALENDAR_PATH", "tools/triage/calendar.yml")
    )
    now = datetime.now(timezone.utc)

    def sla_of(issue: dict[str, Any]) -> str:
        sev = _sev(issue)
        if sev is None or "triaged" in _labels(issue):
            return "ok"
        return sla.classify(sev, _ts(issue["created_at"]), now, cal)

    snap = build_snapshot(fetch_bugs(api), now, sla_of)
    pushed = _push_or_skip(url, metrics.JOB, metrics.render_defects(snap), transport)
    if log is not None:
        append_weekly(log, weekly_section(snap, now, ga), now.date().isoformat())
    return 0 if pushed or not require_push else EXIT_NO_PUSH


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["ledger", "defects", "snapshot"])
    p.add_argument("--path", type=Path, default=LEDGER_PATH)
    p.add_argument(
        "--require-push", action="store_true", help="exit 2 if no push happened"
    )
    p.add_argument(
        "--no-log", action="store_true", help="snapshot: skip the weekly log append"
    )
    a = p.parse_args(argv)
    url = os.environ.get("PUSHGATEWAY_URL", "")
    try:
        if a.cmd == "ledger":
            return cmd_ledger(a.path, url, metrics.http_transport, a.require_push)
        from tools.triage.run import GhApi

        api = GhApi(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
        log = LOG_PATH if a.cmd == "snapshot" and not a.no_log else None
        return cmd_defects(
            api, url, metrics.http_transport, log, GA_DATE, a.require_push
        )
    except metrics.PushError as exc:
        print(f"E_PUSH: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
