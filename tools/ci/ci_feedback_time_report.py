#!/usr/bin/env python3
"""E03-T15: weekly PR-feedback-time report (ADR-0013 §Validation).

Reads `ci-metrics` artifact JSON files (one record per PR-triggered
`pr.yml` run, each `{"pr": <number>, "feedback_seconds": <float>,
"concluded_at": "<ISO8601>"}` — the shape emitted by the `pr.yml`
`ci-required` resolver since E03-T01) from a directory, computes p50/p90
PR-feedback time over the trailing window, and renders a GitHub
job-summary-flavoured markdown report.

Rebalance trigger: ADR-0013 targets PR feedback <=15 minutes end-to-end.
When p90 exceeds that budget, the report includes an explicit rebalance
instruction (see `docs/ci-runbook.md` §10) so the signal is never silently
dropped.

Stdlib only — no network access performed by this module.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path

DEFAULT_REBALANCE_BUDGET_MINUTES = 15.0

REBALANCE_INSTRUCTION = (
    "review the job matrix's path filters and the slowest lane in this "
    "run; either narrow that lane's trigger conditions or split it"
)


class MetricsReportError(Exception):
    """Raised when the metrics window has no usable records (exit 2)."""


def load_records(
    metrics_dir: Path,
    *,
    since: dt.datetime,
    now: dt.datetime,
) -> list[float]:
    """Return the list of feedback_seconds for records concluded in
    [since, now]. Records with unparsable/missing fields are skipped
    (not counted as zero, not fatal on their own)."""
    if not metrics_dir.is_dir():
        raise MetricsReportError(f"ci-metrics directory not found: {metrics_dir}")

    feedback_seconds: list[float] = []
    for path in sorted(metrics_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        try:
            concluded_at = dt.datetime.fromisoformat(record["concluded_at"].replace("Z", "+00:00"))
            seconds = float(record["feedback_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        if concluded_at.tzinfo is None:
            concluded_at = concluded_at.replace(tzinfo=dt.timezone.utc)
        if since <= concluded_at <= now:
            feedback_seconds.append(seconds)
    return feedback_seconds


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; ``values`` must be non-empty."""
    if not values:
        raise ValueError("percentile() requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[rank]


def render_report(
    feedback_seconds: list[float],
    *,
    budget_minutes: float = DEFAULT_REBALANCE_BUDGET_MINUTES,
) -> str:
    if not feedback_seconds:
        return (
            "### Weekly PR feedback time\n\n"
            "_no ci-metrics records found in the trailing window_\n"
        )
    p50_s = statistics.median(feedback_seconds)
    p90_s = percentile(feedback_seconds, 90)
    lines = [
        "### Weekly PR feedback time",
        "",
        f"Sample size: {len(feedback_seconds)} run(s)",
        "",
        "| Percentile | Time |",
        "|---|---|",
        f"| p50 | {p50_s / 60:.1f} min |",
        f"| p90 | {p90_s / 60:.1f} min |",
    ]
    if p90_s / 60 > budget_minutes:
        lines.append("")
        lines.append(
            f"::warning::p90 PR feedback time ({p90_s / 60:.1f} min) exceeds the "
            f"{budget_minutes:.0f} min budget (ADR-0013) — {REBALANCE_INSTRUCTION}."
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics-dir", default="ci-metrics", help="Directory of ci-metrics JSON records"
    )
    parser.add_argument("--window-days", type=int, default=7, help="Trailing window size in days")
    parser.add_argument(
        "--budget-minutes",
        type=float,
        default=DEFAULT_REBALANCE_BUDGET_MINUTES,
        help="Rebalance-trigger budget in minutes (ADR-0013 default: 15)",
    )
    parser.add_argument(
        "--output", default=None, help="Write report to this path (default: stdout)"
    )
    args = parser.parse_args(argv)

    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=args.window_days)

    try:
        feedback_seconds = load_records(Path(args.metrics_dir), since=since, now=now)
    except MetricsReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = render_report(feedback_seconds, budget_minutes=args.budget_minutes)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
