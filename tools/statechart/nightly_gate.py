"""Nightly xstate gate verdict (E50-T04; 29-statechart-adoption-plan.md §1.7).

Consumes the ``--json`` output of ``docs/research/xstate/gate/run_gate.py`` and
(optionally) the JSON of ``docs/research/xstate/bench/bench_c_timers_v2.py``
(BENCH-6), writes the nightly report and decides the exit code.

* ``--mode pinned``   gates. ``run_gate.py`` itself exits 1 on the *known*
  0.9.1 baseline failures (triaged in ADR-0016), so the verdict here is a
  regression diff: a blocking check (any non-``repro`` FAIL, or any ERROR)
  that is not already failing in the committed baseline result. A BENCH-6
  p99 above the threshold at 500 busy machines also fails.
* ``--mode upstream`` never gates: same report, always exit 0, every delta is
  an informational note that feeds the upstream-liaison chore.

Offline and deterministic: it only reads files. Exit 0 = green (or
informational), 1 = pinned regression / BENCH-6 breach, 2 = unreadable input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BENCH6_THRESHOLD_MS = 100.0
BENCH6_LEVEL = "500"
SKIP_ENV = "SKIP-ENV"


def _key(check: dict[str, Any]) -> str:
    return f"{check.get('kind')}:{check.get('id')}"


def _blocking_failures(result: dict[str, Any]) -> dict[str, str]:
    """``kind:id -> status`` for every blocking non-green check."""
    out: dict[str, str] = {}
    for c in result.get("checks", []):
        status = c.get("status")
        if status == "ERROR" or (status == "FAIL" and c.get("kind") != "repro"):
            out[_key(c)] = str(status)
    return out


def regressions(result: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Blocking failures present in ``result`` but not in ``baseline``."""
    known = _blocking_failures(baseline)
    return sorted(k for k in _blocking_failures(result) if k not in known)


def skipped_env(result: dict[str, Any]) -> list[str]:
    """Checks run_gate.py reported as ``SKIP-ENV`` (skipped (environment), #1928)."""
    return sorted(
        _key(c) for c in result.get("checks", []) if c.get("status") == SKIP_ENV
    )


def fixed(result: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Baseline blocking failures that no longer fail (improvements).

    A check skipped for environment reasons was not run, so it is not "fixed".
    """
    now = _blocking_failures(result)
    skipped = set(skipped_env(result))
    return sorted(
        k for k in _blocking_failures(baseline) if k not in now and k not in skipped
    )


def bench6(
    bench: dict[str, Any] | None, threshold: float
) -> tuple[bool | None, float | None]:
    """Return ``(ok, p99)``.

    ``ok`` is None when no bench was supplied, False when the p99 is missing
    (absence of evidence never passes) or over budget.
    """
    if bench is None:
        return None, None
    level = (bench.get("summary_by_busy_level") or {}).get(BENCH6_LEVEL) or {}
    p99 = level.get("p99")
    if p99 is None:
        return False, None
    return float(p99) <= threshold, float(p99)


def render(
    *,
    mode: str,
    date: str,
    result: dict[str, Any],
    new: list[str],
    gone: list[str],
    bench_ok: bool | None,
    p99: float | None,
    threshold: float,
    skipped: list[str] | None = None,
) -> str:
    gating = mode == "pinned"
    red = bool(new) or bench_ok is False
    verdict = ("RED" if red else "GREEN") if gating else ("NOTE" if red else "CLEAN")
    lines = [
        f"# xstate nightly gate - {date} ({mode})",
        "",
        f"- Verdict: **{verdict}**"
        + ("" if gating else " (informational, never gates)"),
        f"- Library: {result.get('library_version')} @ {result.get('library_commit')}",
        f"- Build: {result.get('build')}",
        f"- run_gate exit code: {result.get('exit_code')}",
        "",
        "## Regressions vs committed baseline",
    ]
    lines += [f"- {k}" for k in new] or ["- none"]
    lines += ["", "## Baseline failures now passing"]
    lines += [f"- {k}" for k in gone] or ["- none"]
    lines += ["", "## Skipped (environment) - not run on this host, not a regression"]
    lines += [f"- {k}" for k in skipped or []] or ["- none"]
    lines += ["", "## BENCH-6 (timer lateness, 500 busy machines, p99)"]
    if bench_ok is None:
        lines.append("- not run")
    else:
        shown = "missing" if p99 is None else f"{p99:.1f} ms"
        status = "ok" if bench_ok else "BREACH"
        lines.append(f"- p99 {shown} vs budget {threshold:.0f} ms: {status}")
    if gating and red:
        lines += ["", "Notify: E50-C17 (upstream liaison) - pinned gate regression."]
    return "\n".join(lines) + "\n"


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path}: expected a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("pinned", "upstream"), required=True)
    ap.add_argument(
        "--result", type=Path, required=True, help="run_gate.py --json output"
    )
    ap.add_argument(
        "--baseline", type=Path, required=True, help="committed baseline result JSON"
    )
    ap.add_argument("--bench", type=Path, help="bench_c_timers_v2.py JSON (BENCH-6)")
    ap.add_argument("--threshold", type=float, default=BENCH6_THRESHOLD_MS)
    ap.add_argument("--date", required=True, help="report date, YYYY-MM-DD")
    ap.add_argument(
        "--out", type=Path, required=True, help="artifacts/xstate-gate/<date>.md"
    )
    args = ap.parse_args(argv)
    try:
        result = _load(args.result)
        baseline = _load(args.baseline)
        bench = _load(args.bench) if args.bench else None
    except (OSError, ValueError, TypeError) as exc:
        print(f"nightly_gate: {exc}", file=sys.stderr)
        return 2
    new = regressions(result, baseline)
    gone = fixed(result, baseline)
    ok, p99 = bench6(bench, args.threshold)
    report = render(
        mode=args.mode,
        date=args.date,
        result=result,
        new=new,
        gone=gone,
        bench_ok=ok,
        p99=p99,
        threshold=args.threshold,
        skipped=skipped_env(result),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    if args.mode == "upstream":
        return 0
    return 1 if (new or ok is False) else 0


if __name__ == "__main__":
    sys.exit(main())
