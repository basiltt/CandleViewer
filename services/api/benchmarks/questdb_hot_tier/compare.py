"""Compares a benchmark run against the committed `baseline.json`.

Per the ticket's DoD: "not yet gating, per R0 quality gates" — this script
**always exits 0**. It prints a human-readable table and lists any shape
that regressed beyond `--tolerance-pct` (default 25%, matching the spike's
own `worse_by_more_than_25pct` rule in `spikes/storage/bench.py`) so a
reviewer/operator can act on it; it never fails a build.

Run:

    uv run python -m benchmarks.questdb_hot_tier.compare --run /tmp/run.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_BASELINE_PATH = Path(__file__).parent / "baseline.json"


class MissingShape(ValueError):
    """A shape present in the baseline is absent from the candidate run."""


def compare_shapes(
    baseline: dict[str, Any], candidate: dict[str, Any], *, tolerance_pct: float = 25.0
) -> dict[str, Any]:
    """Returns a report dict: per-shape verdict plus overall lists.

    Verdicts:
    - ``"missing"``: shape absent from `candidate["shapes"]`.
    - ``"regressed"``: candidate p95 exceeds baseline p95 by more than
      `tolerance_pct` percent.
    - ``"ok"``: within tolerance (includes candidate being faster).
    """
    baseline_shapes = baseline.get("shapes", {})
    candidate_shapes = candidate.get("shapes", {})

    rows: dict[str, dict[str, Any]] = {}
    regressed: list[str] = []
    missing: list[str] = []

    for shape_id, base_entry in baseline_shapes.items():
        base_engine = base_entry.get("questdb", base_entry)
        base_p95 = float(base_engine["p95_ms"])

        if shape_id not in candidate_shapes:
            missing.append(shape_id)
            rows[shape_id] = {
                "verdict": "missing",
                "baseline_p95_ms": base_p95,
                "candidate_p95_ms": None,
                "delta_pct": None,
            }
            continue

        cand_entry = candidate_shapes[shape_id]
        cand_p95 = float(cand_entry["p95_ms"])
        delta_pct = ((cand_p95 - base_p95) / base_p95 * 100.0) if base_p95 > 0 else 0.0
        verdict = "regressed" if delta_pct > tolerance_pct else "ok"
        if verdict == "regressed":
            regressed.append(shape_id)
        rows[shape_id] = {
            "verdict": verdict,
            "baseline_p95_ms": base_p95,
            "candidate_p95_ms": cand_p95,
            "delta_pct": round(delta_pct, 1),
        }

    return {
        "tolerance_pct": tolerance_pct,
        "rows": rows,
        "regressed": regressed,
        "missing": missing,
        "all_ok": not regressed and not missing,
    }


def format_table(report: dict[str, Any]) -> str:
    lines = [
        f"{'shape':<6}{'verdict':<10}{'baseline p95':>14}{'candidate p95':>16}{'delta %':>10}",
    ]
    for shape_id, row in sorted(report["rows"].items()):
        cand = row["candidate_p95_ms"]
        delta = row["delta_pct"]
        lines.append(
            f"{shape_id:<6}{row['verdict']:<10}"
            f"{row['baseline_p95_ms']:>14.3f}"
            f"{(cand if cand is not None else float('nan')):>16.3f}"
            f"{(delta if delta is not None else float('nan')):>10.1f}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="path to a runner.py output JSON")
    ap.add_argument("--baseline", default=str(_BASELINE_PATH))
    ap.add_argument("--tolerance-pct", type=float, default=25.0)
    args = ap.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.run).read_text(encoding="utf-8"))
    report = compare_shapes(baseline, candidate, tolerance_pct=args.tolerance_pct)

    print(format_table(report))
    if report["regressed"]:
        print(f"\nREGRESSED (not gating): {report['regressed']}")
    if report["missing"]:
        print(f"\nMISSING shapes (not gating): {report['missing']}")
    if report["all_ok"]:
        print("\nAll shapes within tolerance.")

    return 0  # never gates — see module docstring


if __name__ == "__main__":
    raise SystemExit(main())
