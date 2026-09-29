"""Unit tests for tools/ci/ci_feedback_time_report.py (E03-T15).

Covers the acceptance scenario "Weekly feedback time is published": p50/p90
published, and a p90 above the 15-minute budget flagged with the rebalance
instruction.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.ci_feedback_time_report import (
    MetricsReportError,
    load_records,
    main,
    percentile,
    render_report,
)


def _write_record(
    metrics_dir: Path, name: str, *, feedback_seconds: float, concluded_at: dt.datetime
) -> None:
    metrics_dir.mkdir(parents=True, exist_ok=True)
    (metrics_dir / f"{name}.json").write_text(
        json.dumps(
            {
                "pr": 1,
                "feedback_seconds": feedback_seconds,
                "concluded_at": concluded_at.isoformat(),
            }
        ),
        encoding="utf-8",
    )


def test_percentile_single_value_returns_that_value() -> None:
    assert percentile([42.0], 90) == 42.0


def test_percentile_requires_non_empty_list() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)


def test_load_records_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(MetricsReportError):
        load_records(
            tmp_path / "nope",
            since=dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            now=dt.datetime.max.replace(tzinfo=dt.timezone.utc),
        )


def test_load_records_skips_malformed_and_out_of_window(tmp_path: Path) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    metrics_dir = tmp_path / "ci-metrics"
    _write_record(
        metrics_dir, "in-window", feedback_seconds=300.0, concluded_at=now - dt.timedelta(days=1)
    )
    _write_record(
        metrics_dir, "too-old", feedback_seconds=999.0, concluded_at=now - dt.timedelta(days=30)
    )
    (metrics_dir / "malformed.json").write_text("not json", encoding="utf-8")
    (metrics_dir / "missing-field.json").write_text(json.dumps({"pr": 2}), encoding="utf-8")

    records = load_records(metrics_dir, since=now - dt.timedelta(days=7), now=now)
    assert records == [300.0]


def test_render_report_empty_window_says_no_records() -> None:
    report = render_report([])
    assert "no ci-metrics records found" in report


def test_render_report_publishes_p50_and_p90() -> None:
    # 10 records at 60s .. 600s in 60s steps.
    values = [float(60 * i) for i in range(1, 11)]
    report = render_report(values, budget_minutes=15.0)
    assert "p50" in report
    assert "p90" in report
    assert "Sample size: 10 run(s)" in report


def test_render_report_flags_rebalance_when_p90_over_budget() -> None:
    # All runs take 20 minutes -> p90 well above the 15-minute budget.
    values = [20.0 * 60] * 10
    report = render_report(values, budget_minutes=15.0)
    assert "::warning::" in report
    assert "narrow that lane's trigger conditions or split it" in report


def test_render_report_no_warning_when_p90_within_budget() -> None:
    values = [5.0 * 60] * 10
    report = render_report(values, budget_minutes=15.0)
    assert "::warning::" not in report


def test_main_writes_report_to_output_file(tmp_path: Path) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    metrics_dir = tmp_path / "ci-metrics"
    _write_record(metrics_dir, "run-1", feedback_seconds=600.0, concluded_at=now)
    output = tmp_path / "report.md"

    rc = main(["--metrics-dir", str(metrics_dir), "--output", str(output)])

    assert rc == 0
    assert "p50" in output.read_text(encoding="utf-8")


def test_main_exits_two_on_missing_metrics_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--metrics-dir", str(tmp_path / "absent")])
    assert rc == 2
    assert "error:" in capsys.readouterr().err
