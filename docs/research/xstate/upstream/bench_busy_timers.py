"""Busy-machine timer-lateness harness (upstream contribution, E50-C02).

Wraps a checkout's own ``benchmarks/production_characteristics.py --quick``,
parses its "busy machines / lateness ms" table and emits n/min/p50/p99/max per
busy level as JSON, with an optional pass/fail bar. No machine-specific paths.

    python bench_busy_timers.py --repo PATH [--python EXE] [--runs N]
        [--bar-ms 100] [--bar-level 500] [--timeout 120]
Exit status: 0 within bar (or no bar evaluated), 1 over bar.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROW_RE = re.compile(r"^\s*(\d+)\s+([+\-]?\d+(?:\.\d+)?)\s*$")


def parse_table(text: str) -> dict[int, float]:
    """Return {busy_machines: lateness_ms} from the lateness table."""
    readings: dict[int, float] = {}
    in_section = False
    for line in text.splitlines():
        low = line.lower()
        if "lateness" in low and "ms" in low:
            in_section = True
            continue
        if not in_section or "busy machines" in low:
            continue
        m = ROW_RE.match(line)
        if m:
            readings[int(m.group(1))] = float(m.group(2))
        elif not line.strip() and readings:
            in_section = False
    return readings


def percentile(vals: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..1)."""
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, -(-int(q * 100) * len(s) // 100) - 1))]


def summarise(per_run: list[dict[int, float]]) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    for level in sorted({k for r in per_run for k in r}):
        v = [r[level] for r in per_run if level in r]
        out[str(level)] = {
            "n": len(v),
            "min": min(v),
            "p50": statistics.median(v),
            "p99": percentile(v, 0.99),
            "max": max(v),
        }
    return out


def run_once(repo: Path, python: str, timeout: float) -> dict[int, float]:
    proc = subprocess.run(
        [python, "benchmarks/production_characteristics.py", "--quick"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return parse_table(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--bar-ms", type=float, default=None)
    ap.add_argument("--bar-level", type=int, default=500)
    ap.add_argument("--timeout", type=float, default=120)
    a = ap.parse_args(argv)
    summary = summarise([run_once(a.repo, a.python, a.timeout) for _ in range(a.runs)])
    result: dict[str, object] = {"runs": a.runs, "summary_by_busy_level": summary}
    ok = True
    if a.bar_ms is not None:
        row = summary.get(str(a.bar_level))
        ok = row is not None and float(row["p99"]) <= a.bar_ms
        result["bar"] = {"level": a.bar_level, "ms": a.bar_ms, "within": ok}
    print(json.dumps(result, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
