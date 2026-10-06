# -----------------------------------------------------------------------------
# bench_c_timers_v2.py — thin wrapper over upstream production_characteristics.py
# -----------------------------------------------------------------------------
"""BENCH-6 correction (round 13): bench_c_timers.py (this dir) was never the
right tool for measuring `after` lateness under load — it doesn't reproduce
the "N busy machines" loaded-timer scenario upstream ships in its own bench.

This wrapper shells out to the library's own
`benchmarks/production_characteristics.py --quick`, parses its §2 table
("busy machines" / "lateness ms"), and re-emits the numbers as our JSON shape
so `run_gate.py` can consume BENCH-6 without re-implementing the scenario.

Usage:
    python bench_c_timers_v2.py [--runs N] [--repo PATH]

Exit: writes JSON to stdout; also returns the parsed dict from main() for
callers that import this module directly.
"""

from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[1] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import argparse
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

DEFAULT_REPO = Path(
    str(_XS)
)
LATENESS_RE = re.compile(r"^\s*(\d+)\s+([+\-]?\d+(?:\.\d+)?)\s*$")


def _run_once(repo: Path, python_exe: Path) -> Dict[int, float]:
    """Run `production_characteristics.py --quick` once; return
    {busy_machines: lateness_ms} parsed out of its §2 table."""
    proc = subprocess.run(
        [str(python_exe), "benchmarks/production_characteristics.py", "--quick"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = proc.stdout
    readings: Dict[int, float] = {}
    in_section = False
    for line in out.splitlines():
        if "lateness" in line.lower() and "ms" in line.lower():
            in_section = True
            continue
        if in_section:
            if "busy machines" in line.lower():
                continue
            m = LATENESS_RE.match(line)
            if m:
                busy = int(m.group(1))
                ms = float(m.group(2).lstrip("+"))
                readings[busy] = ms
            elif line.strip() == "":
                # blank line ends the table only if we already captured rows
                if readings:
                    in_section = False
    return readings


def main(argv: List[str] = None) -> Dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    args = ap.parse_args(argv)

    python_exe = args.repo / ".venv-main" / "Scripts" / "python.exe"
    if not python_exe.exists():
        python_exe = Path(sys.executable)

    per_run: List[Dict[int, float]] = []
    for _ in range(args.runs):
        per_run.append(_run_once(args.repo, python_exe))

    busy_levels = sorted({k for r in per_run for k in r})
    by_level: Dict[str, List[float]] = {
        str(b): [r[b] for r in per_run if b in r] for b in busy_levels
    }

    result = {
        "bench": "bench_c_timers_v2 (wraps upstream production_characteristics.py --quick, section 2)",
        "runs": args.runs,
        "our_bar_ms_p99_at_500_busy": 100,
        "raw_ms_by_busy_level": by_level,
        "summary_by_busy_level": {
            level: {
                "n": len(vals),
                "p50": statistics.median(vals) if vals else None,
                "p99": (
                    sorted(vals)[max(0, int(len(vals) * 0.99) - 1)] if vals else None
                ),
                "mean": statistics.fmean(vals) if vals else None,
            }
            for level, vals in by_level.items()
        },
    }

    within_bar = None
    if "500" in by_level and by_level["500"]:
        p99_500 = result["summary_by_busy_level"]["500"]["p99"]
        within_bar = p99_500 <= 100
    result["within_bar_at_500"] = within_bar

    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
