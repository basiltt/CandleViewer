"""Tests for tools/statechart/nightly_gate.py (E50-T04)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.statechart.nightly_gate import bench6, main, regressions


def _res(*checks: tuple[str, str, str]) -> dict:
    return {
        "library_version": "0.9.1",
        "library_commit": "abc",
        "build": "b",
        "exit_code": 1,
        "checks": [{"kind": k, "id": i, "status": s} for k, i, s in checks],
    }


BASE = _res(("verify", "LC-01", "FAIL"), ("verify", "LC-02", "PASS"), ("repro", "R1", "FAIL"))


def _run(tmp_path: Path, mode: str, result: dict, bench: dict | None = None) -> tuple[int, str]:
    r, b, out = tmp_path / "r.json", tmp_path / "b.json", tmp_path / "a" / "d.md"
    r.write_text(json.dumps(result))
    b.write_text(json.dumps(BASE))
    argv = [
        "--mode",
        mode,
        "--result",
        str(r),
        "--baseline",
        str(b),
        "--date",
        "2026-10-04",
        "--out",
        str(out),
    ]
    if bench is not None:
        bp = tmp_path / "bench.json"
        bp.write_text(json.dumps(bench))
        argv += ["--bench", str(bp)]
    return main(argv), out.read_text(encoding="utf-8")


def test_regressions_known_baseline_failure_is_not_a_regression() -> None:
    assert regressions(BASE, BASE) == []


def test_regressions_new_blocking_failure_is_reported_repro_is_not() -> None:
    cur = _res(("verify", "LC-01", "FAIL"), ("verify", "LC-02", "FAIL"), ("repro", "R2", "FAIL"))
    assert regressions(cur, BASE) == ["verify:LC-02"]


def test_regressions_error_always_counts() -> None:
    assert regressions(_res(("probe", "P1", "ERROR")), BASE) == ["probe:P1"]


def test_pinned_regression_is_red_and_notifies_liaison(tmp_path: Path) -> None:
    rc, report = _run(tmp_path, "pinned", _res(("verify", "LC-02", "FAIL")))
    assert rc == 1
    assert "RED" in report and "E50-C17" in report


def test_pinned_baseline_state_is_green(tmp_path: Path) -> None:
    rc, report = _run(tmp_path, "pinned", BASE)
    assert rc == 0 and "GREEN" in report


def test_upstream_failure_never_gates_and_is_informational(tmp_path: Path) -> None:
    rc, report = _run(tmp_path, "upstream", _res(("verify", "LC-02", "FAIL")))
    assert rc == 0
    assert "informational" in report and "E50-C17" not in report


def test_bench6_budget_and_missing_evidence() -> None:
    ok = {"summary_by_busy_level": {"500": {"p99": 55.8}}}
    over = {"summary_by_busy_level": {"500": {"p99": 100.1}}}
    assert bench6(ok, 100.0) == (True, 55.8)
    assert bench6(over, 100.0)[0] is False
    assert bench6({"summary_by_busy_level": {}}, 100.0) == (False, None)
    assert bench6(None, 100.0) == (None, None)


def test_pinned_bench_breach_fails(tmp_path: Path) -> None:
    bench = {"summary_by_busy_level": {"500": {"p99": 250.0}}}
    rc, report = _run(tmp_path, "pinned", BASE, bench)
    assert rc == 1 and "BREACH" in report


def test_unreadable_input_exits_2(tmp_path: Path) -> None:
    rc = main(
        [
            "--mode",
            "pinned",
            "--result",
            str(tmp_path / "x"),
            "--baseline",
            str(tmp_path / "y"),
            "--date",
            "d",
            "--out",
            str(tmp_path / "o.md"),
        ]
    )
    assert rc == 2
