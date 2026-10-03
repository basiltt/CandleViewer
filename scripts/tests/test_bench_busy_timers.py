"""Tests for the upstream-contribution timer harness (E50-C02)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs/research/xstate/upstream"))

import bench_busy_timers as b

SAMPLE = """## 1. other
## 2. timer lateness ms
busy machines   lateness
0   1.5
500 52.1

## 3. later
7 9.9
"""


def test_parse_table_reads_only_lateness_section() -> None:
    assert b.parse_table(SAMPLE) == {0: 1.5, 500: 52.1}


def test_summarise_reports_spread() -> None:
    s = b.summarise([{500: 50.0}, {500: 60.0}, {500: 55.0}])["500"]
    assert (s["n"], s["min"], s["p50"], s["max"]) == (3, 50.0, 55.0, 60.0)
    assert s["p99"] == 60.0


def test_main_bar(monkeypatch, capsys) -> None:
    monkeypatch.setattr(b, "run_once", lambda *a, **k: {500: 120.0})
    assert b.main(["--repo", ".", "--runs", "2", "--bar-ms", "100"]) == 1
    monkeypatch.setattr(b, "run_once", lambda *a, **k: {500: 60.0})
    assert b.main(["--repo", ".", "--runs", "2", "--bar-ms", "100"]) == 0
    assert "within" in capsys.readouterr().out
