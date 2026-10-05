"""Contract-suite budget gate (E50-T06; 29-statechart-adoption-plan.md §1.7).

Reads the JUnit XML of ``pytest tests/xstate_contract`` and fails when

* the suite wall time exceeds the budget (default 60 s), or
* a machine's generated cases run slower than the per-machine throughput
  floor (cases / second), or a committed machine has no cases at all.

Offline and deterministic: it only parses a file. Exit 0 = within budget,
1 = budget breached, 2 = usage / unreadable input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_BUDGET_S = 60.0
#: Conservative floor (cases/s per machine) well under the measured ~25-60 on
#: a loaded dev host, so it flags a pathological slowdown, not CI noise.
DEFAULT_MIN_CASES_PER_S = 3.0
_ROOT = Path(__file__).resolve().parents[2]
_MACHINES = _ROOT / "services/api/candleviewer/statechart/machines"


def machine_keys(machines: Path = _MACHINES) -> list[str]:
    """Machine keys (``trade_group``) from ``BNN.<key>.machine.json`` names."""
    keys = []
    for p in sorted(machines.glob("B*.machine.json")):
        parts = p.name.split(".")
        if len(parts) >= 4:
            keys.append(parts[1])
    return keys


def analyse(
    junit: Path,
    keys: list[str],
    budget_s: float = DEFAULT_BUDGET_S,
    min_rate: float = DEFAULT_MIN_CASES_PER_S,
) -> tuple[dict[str, object], list[str]]:
    """Return (report, violations)."""
    # Input is our own pytest JUnit output; stdlib expat does not fetch external
    # entities, and a DOCTYPE/entity declaration is rejected outright below.
    text = junit.read_text(encoding="utf-8")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ET.ParseError("DTD/entity declarations are not allowed in JUnit XML")
    root = ET.fromstring(text)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(float(s.get("time", 0)) for s in suites)
    per: dict[str, list[float]] = {k: [0, 0.0] for k in keys}
    pats = {k: re.compile(rf"(?<![a-z_]){re.escape(k)}(?![a-z_])") for k in keys}
    for case in root.iter("testcase"):
        name = case.get("name", "")
        for k, pat in pats.items():
            if pat.search(name):
                per[k][0] += 1
                per[k][1] += float(case.get("time", 0))
    violations: list[str] = []
    if total > budget_s:
        violations.append(f"suite took {total:.1f}s > budget {budget_s:.0f}s")
    machines: dict[str, dict[str, float]] = {}
    for k, (n, t) in per.items():
        rate = n / t if t > 0 else float("inf")
        machines[k] = {"cases": n, "seconds": round(t, 2), "cases_per_s": round(rate, 1)}
        if n == 0:
            violations.append(f"machine {k}: no generated cases found")
        elif rate < min_rate:
            violations.append(f"machine {k}: {rate:.1f} cases/s < floor {min_rate:g}")
    report = {"suite_s": round(total, 2), "budget_s": budget_s, "machines": machines}
    return report, violations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("junit", type=Path)
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--min-cases-per-s", type=float, default=DEFAULT_MIN_CASES_PER_S)
    ap.add_argument("--machines", type=Path, default=_MACHINES)
    a = ap.parse_args(argv)
    try:
        report, bad = analyse(a.junit, machine_keys(a.machines), a.budget_s, a.min_cases_per_s)
    except (OSError, ET.ParseError) as exc:
        print(f"suite_budget: cannot read {a.junit}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    for v in bad:
        print(f"BUDGET FAIL: {v}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
