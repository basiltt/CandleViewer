"""Check the E04 black-box plan covers US-OBS-001..005,007 and every alert rule is in the drill matrix (E04-Q01)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STORIES = [f"US-OBS-{n:03d}" for n in (1, 2, 3, 4, 5, 7)]
SKIP = {"Watchdog"}


def alert_names(alerts_dir: Path) -> set[str]:
    names: set[str] = set()
    for f in alerts_dir.glob("*.yml"):
        for g in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get(
            "groups", []
        ):
            for r in g.get("rules", []):
                sev = (r.get("labels") or {}).get("severity")
                a = r.get("alert")
                if (
                    a
                    and a not in SKIP
                    and sev in ("page", "ticket")
                    and not a.startswith("ExpectedMetricMissing")
                ):
                    names.add(a)
    return names


def check(plan: str, matrix: str, alerts: set[str]) -> list[str]:
    errors = [
        f"{s}: no case verifies this story"
        for s in STORIES
        if not re.search(rf"\|[^|\n]*{s} /", plan)
    ]
    for line in plan.splitlines():
        if line.startswith("| E04-TC-"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) != 6 or not all(cells):
                errors.append(
                    f"{cells[0] if cells else line}: expected 6 non-empty columns"
                )
    for a in sorted(alerts):
        if not re.search(rf"^\| {a} \|", matrix, re.MULTILINE):
            errors.append(f"{a}: missing from alert drill matrix")
    return errors


def main() -> int:
    plan = (ROOT / "qa/plans/e04-observability-test-plan.md").read_text(
        encoding="utf-8"
    )
    matrix = (ROOT / "qa/plans/e04-alert-drill-matrix.md").read_text(encoding="utf-8")
    errors = check(plan, matrix, alert_names(ROOT / "infra/prometheus/alerts"))
    for e in errors:
        print(f"ERROR: {e}")
    print("OK" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
