"""E49-K01: cluster_report is offline and deterministic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.triage import cluster_report as cr

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "triage"


def _load() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues = json.loads((FIX / "issues.json").read_text(encoding="utf-8"))
    cfg = json.loads((FIX / "clusters.json").read_text(encoding="utf-8"))
    return issues, cfg


def test_is_defect_excludes_planning_keys() -> None:
    assert not cr.is_defect({"title": "[E49-S06] story"})
    assert cr.is_defect({"title": "[E49-S06-B1] bug"})
    assert cr.is_defect({"title": "flaky: x"})


def test_assign_confirmed_wins_then_rules_then_singleton() -> None:
    issues, cfg = _load()
    got = cr.assign(issues, cfg["confirmed"], cfg["rules"])
    assert got == {
        1: "flaky-tests",
        2: "dod-evidence-gap",
        3: "storage-writer",
        4: "unwired-component",
        6: "storage-writer",
    }


def test_build_table_counts_open_and_closed() -> None:
    issues, cfg = _load()
    table = cr.build_table(issues, cr.assign(issues, cfg["confirmed"], cfg["rules"]))
    assert "| storage-writer | 2 | 0 | 50% | #3, #6 |" in table
    assert "| unwired-component | 0 | 1 | 0% | - |" in table
    assert "Open defects: 4; in a named cluster: 4 (100%)." in table


def test_main_prints_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert cr.main([str(FIX / "issues.json"), "--clusters", str(FIX / "clusters.json")]) == 0
    assert "| Cluster |" in capsys.readouterr().out
