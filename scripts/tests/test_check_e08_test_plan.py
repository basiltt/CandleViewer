"""Tests for scripts/check_e08_test_plan.py (E08-Q01)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from check_e08_test_plan import DEFAULT_PLAN, check, expand, main

HDR = (
    "| Case | Pre | Steps | Exp | Verifies | Automation |\n|---|---|---|---|---|---|\n"
)


def _plan(cases: str, trace: str) -> str:
    rows = "".join(
        f"| US-MKT-{n:03d} | A{n:02d} | A{n:02d} | — |\n"
        for n in range(1, 10)
        if n != 1
    )
    base = "".join(
        f"| E08-TC-A{n:02d} | `f/x` | s | e | US-MKT-{n:03d}, E08-S01 | E08-Q02 |\n"
        for n in range(2, 10)
    )
    return (
        HDR
        + cases
        + base
        + "\n| Story | Cases | Automated | Manual-only |\n|---|---|---|---|\n"
        + trace
        + rows
    )


def test_check_real_plan_passes() -> None:
    assert check(DEFAULT_PLAN.read_text(encoding="utf-8")) == []
    assert main([str(DEFAULT_PLAN)]) == 0


def test_expand_ranges() -> None:
    assert expand("A01–A03, B07") == {"A01", "A02", "A03", "B07"}


def test_check_story_without_case_fails() -> None:
    errs = check(_plan("", "| US-MKT-001 | — | — | — |\n"))
    assert any("US-MKT-001: no case" in e for e in errs)


def test_check_missing_fixture_fails() -> None:
    case = "| E08-TC-A01 | none | s | e | US-MKT-001, E08-S01 | E08-Q02 |\n"
    errs = check(_plan(case, "| US-MKT-001 | A01 | A01 | — |\n"))
    assert any("no fixture" in e for e in errs)


def test_check_manual_counted_as_automated_fails() -> None:
    case = (
        "| E08-TC-A01 | `f/x` | s | e | US-MKT-001, E08-S01 | manual-only, E08-Q02 |\n"
    )
    errs = check(_plan(case, "| US-MKT-001 | A01 | A01 | — |\n"))
    assert any("manual-only counted as automated" in e for e in errs)


def test_check_drifted_table_fails(tmp_path: Path) -> None:
    case = "| E08-TC-A01 | `f/x` | s | e | US-MKT-001, E08-S01 | E08-Q02 |\n"
    p = tmp_path / "plan.md"
    p.write_text(
        _plan(case, "| US-MKT-001 | A01, A02 | A01, A02 | — |\n"), encoding="utf-8"
    )
    assert main([str(p)]) == 1
