"""Pure statistics + baseline comparison for the storage perf harness (E07-Q03)."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

MIN_SAMPLES_FOR_PERCENTILES = 30
REGRESSION_THRESHOLD = 0.20


def percentile_nearest_rank(samples: Sequence[float], p: float) -> float:
    """Nearest-rank percentile: the value at rank ceil(p/100 * n) (1-based)."""
    if not samples:
        raise ValueError("no samples")
    if not 0 < p <= 100:
        raise ValueError("p must be in (0, 100]")
    ordered = sorted(samples)
    rank = max(1, math.ceil(p / 100.0 * len(ordered)))
    return ordered[rank - 1]


def summarize(samples: Sequence[float]) -> dict[str, object]:
    """p50/p95/p99 when >=30 samples, otherwise raw values only (no fake precision)."""
    if len(samples) < MIN_SAMPLES_FOR_PERCENTILES:
        return {"n": len(samples), "raw": list(samples)}
    return {
        "n": len(samples),
        "p50": percentile_nearest_rank(samples, 50),
        "p95": percentile_nearest_rank(samples, 95),
        "p99": percentile_nearest_rank(samples, 99),
    }


def compare_to_baseline(
    baseline: dict[str, float],
    current: dict[str, float],
    threshold: float = REGRESSION_THRESHOLD,
) -> list[dict[str, object]]:
    """Return a regression entry per shape whose p95 exceeds baseline by MORE than threshold.

    Exactly `threshold` (e.g. +20.0 %) is not a regression. Shapes absent from the
    baseline are ignored; shapes absent from `current` are reported as missing.
    """
    out: list[dict[str, object]] = []
    for shape, base in sorted(baseline.items()):
        if shape not in current:
            out.append(
                {
                    "shape": shape,
                    "baseline_p95_ms": base,
                    "current_p95_ms": None,
                    "delta_pct": None,
                    "reason": "missing",
                }
            )
            continue
        cur = current[shape]
        # Compare via integer-scaled ratio to keep the exact-boundary case exact.
        if cur * 100 > base * (100 + round(threshold * 100)):
            out.append(
                {
                    "shape": shape,
                    "baseline_p95_ms": base,
                    "current_p95_ms": cur,
                    "delta_pct": round((cur / base - 1) * 100, 2),
                    "reason": "regression",
                }
            )
    return out


def format_regression_report(regs: list[dict[str, object]]) -> str:
    lines = ["Storage perf regression (p95 over baseline + threshold):"]
    for r in regs:
        if r["reason"] == "missing":
            lines.append(f"  shape {r['shape']}: missing from current run")
        else:
            lines.append(
                f"  shape {r['shape']}: {r['baseline_p95_ms']} ms -> {r['current_p95_ms']} ms"
                f" ({r['delta_pct']:+}%)"
            )
    return "\n".join(lines)


class PerfRegressionError(AssertionError):
    """Raised by `assert_within_baseline` when a metric regressed past the gate."""


def assert_within_baseline(
    baseline: dict[str, float],
    current: dict[str, float],
    *,
    threshold: float = REGRESSION_THRESHOLD,
    abs_slack_ms: float = 0.0,
) -> None:
    """Fail (raise) when any metric is > `threshold` over baseline AND more than
    `abs_slack_ms` slower in absolute terms (sub-ms CI jitter is not a regression).
    A metric missing from `current` always fails."""
    regs = [
        r
        for r in compare_to_baseline(baseline, current, threshold)
        if r["reason"] == "missing"
        or float(str(r["current_p95_ms"])) - float(str(r["baseline_p95_ms"])) > abs_slack_ms
    ]
    if regs:
        raise PerfRegressionError(format_regression_report(regs))


def write_report_section(path: Path, section: str, data: dict[str, object]) -> dict[str, object]:
    """Merge `data` under `section` into the JSON report at `path` (created if absent)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {}
    if path.exists():
        report = json.loads(path.read_text("utf-8"))
    report[section] = data
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    return report
