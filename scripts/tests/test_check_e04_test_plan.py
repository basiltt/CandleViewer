"""Tests for scripts/check_e04_test_plan.py (E04-Q01)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_e04_test_plan import ROOT, alert_names, check

ROW = "| E04-TC-X01 | pre | steps | exp | {s} / E04-T01 | Auto |\n"


def _plan(stories: list[str]) -> str:
    return "".join(ROW.format(s=s) for s in stories)


def test_missing_story_reported() -> None:
    errs = check(_plan(["US-OBS-001"]), "", set())
    assert any("US-OBS-002" in e for e in errs)


def test_missing_alert_reported() -> None:
    all_s = [f"US-OBS-{n:03d}" for n in (1, 2, 3, 4, 5, 7)]
    assert check(_plan(all_s), "| PostgresDown | x |\n", {"PostgresDown", "Nope"}) == [
        "Nope: missing from alert drill matrix"
    ]


def test_short_row_reported() -> None:
    errs = check("| E04-TC-X01 | a | b |\n", "", set())
    assert any("6 non-empty" in e for e in errs)


def test_repo_plan_is_consistent() -> None:
    plan = (ROOT / "qa/plans/e04-observability-test-plan.md").read_text(
        encoding="utf-8"
    )
    matrix = (ROOT / "qa/plans/e04-alert-drill-matrix.md").read_text(encoding="utf-8")
    assert check(plan, matrix, alert_names(ROOT / "infra/prometheus/alerts")) == []
