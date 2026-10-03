"""Tests for tools/statechart/suite_budget.py (E50-T06)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.statechart.suite_budget import analyse, machine_keys, main


def _junit(tmp: Path, total: float, cases: list[tuple[str, float]]) -> Path:
    body = "".join(f'<testcase classname="t" name="{n}" time="{t}"/>' for n, t in cases)
    p = tmp / "j.xml"
    p.write_text(
        f'<testsuites><testsuite time="{total}" tests="{len(cases)}">{body}</testsuite></testsuites>',
        encoding="utf-8",
    )
    return p


def test_within_budget_passes(tmp_path: Path) -> None:
    j = _junit(tmp_path, 10, [("a[leg:x]", 0.1), ("b[oco:y]", 0.1)])
    report, bad = analyse(j, ["leg", "oco"])
    assert bad == [] and report["suite_s"] == 10


def test_slow_suite_fails_budget_gate(tmp_path: Path) -> None:
    j = _junit(tmp_path, 61, [("a[leg:x]", 0.1)])
    _, bad = analyse(j, ["leg"])
    assert any("budget 60s" in v for v in bad)
    assert main([str(j), "--machines", str(tmp_path)]) == 1


def test_slow_machine_and_missing_machine_fail(tmp_path: Path) -> None:
    j = _junit(tmp_path, 5, [("a[leg:x]", 2.0)])
    _, bad = analyse(j, ["leg", "oco"])
    assert any("leg" in v and "cases/s" in v for v in bad)
    assert any("oco" in v and "no generated cases" in v for v in bad)


def test_unreadable_input_exit_2(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope.xml")]) == 2


def test_machine_keys_from_real_charts() -> None:
    keys = machine_keys()
    assert "trade_group" in keys and "kill_switch" in keys
