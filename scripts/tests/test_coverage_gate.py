"""Unit tests for tools/ci/coverage_gate.py (E03-T04).

Covers the four Gherkin acceptance scenarios plus the fixture matrix named
in the ticket's Test plan: below floor, at floor, above baseline, within
tolerance, missing artifact, malformed lcov, malformed coverage.xml.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.coverage_gate import (
    CoverageGateError,
    PackageConfig,
    compute_ratchet_proposals,
    evaluate_all,
    evaluate_package,
    load_config,
    parse_coverage_xml,
    parse_lcov,
    render_summary_table,
)


def _lcov(lines_found: int, lines_hit: int) -> str:
    return f"SF:src/x.ts\nLF:{lines_found}\nLH:{lines_hit}\nend_of_record\n"


def _coverage_xml(line_rate: float) -> str:
    return f'<?xml version="1.0"?><coverage line-rate="{line_rate}"></coverage>'


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- Gherkin scenario 1: below floor fails --------------------------------


def test_evaluate_package_below_floor_fails(tmp_path: Path) -> None:
    pkg = PackageConfig(
        "services/api",
        floor=85.0,
        baseline=85.0,
        artifact="py-coverage",
        report_format="coverage-xml",
    )
    report_path = _write(tmp_path / "coverage.xml", _coverage_xml(0.832))
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "FAIL"
    assert result.code == "CI-COV-001"
    assert result.reason == "services/api 83.2% < floor 85.0%"


# --- Gherkin scenario 2: regression beyond tolerance fails, even above floor


def test_evaluate_package_baseline_regression_beyond_tolerance_fails(
    tmp_path: Path,
) -> None:
    pkg = PackageConfig(
        "packages/ui",
        floor=80.0,
        baseline=91.0,
        artifact="coverage-unit-frontend",
        report_format="lcov",
    )
    report_path = _write(tmp_path / "lcov.info", _lcov(lines_found=1000, lines_hit=880))
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "FAIL"
    assert result.code == "CI-COV-002"
    assert "regression 3.0pp beyond 0.5pp tolerance" in result.reason


# --- Gherkin scenario 3: ratchet proposal on improvement ------------------


def test_ratchet_proposal_emitted_when_measured_exceeds_baseline_by_at_least_one_pp() -> (
    None
):
    from tools.ci.coverage_gate import GateReport, PackageResult

    report = GateReport(
        results=[
            PackageResult(
                name="packages/protocol",
                floor=85.0,
                baseline=88.0,
                measured=89.4,
                delta=1.4,
                verdict="PASS",
                code=None,
                reason=None,
            )
        ]
    )
    proposals = compute_ratchet_proposals(report)
    assert proposals == {"packages/protocol": 89.4}


def test_ratchet_proposal_not_emitted_below_one_pp_improvement() -> None:
    from tools.ci.coverage_gate import GateReport, PackageResult

    report = GateReport(
        results=[
            PackageResult(
                name="packages/protocol",
                floor=85.0,
                baseline=88.0,
                measured=88.6,
                delta=0.6,
                verdict="PASS",
                code=None,
                reason=None,
            )
        ]
    )
    assert compute_ratchet_proposals(report) == {}


# --- Gherkin scenario 4: missing artifact is a failure --------------------


def test_evaluate_package_missing_artifact_fails(tmp_path: Path) -> None:
    pkg = PackageConfig(
        "packages/chart-engine",
        floor=85.0,
        baseline=85.0,
        artifact="coverage-unit-engine",
        report_format="lcov",
    )
    missing_path = tmp_path / "does-not-exist" / "lcov.info"
    result = evaluate_package(pkg, missing_path, tolerance_pp=0.5)
    assert result.verdict == "FAIL"
    assert result.code == "CI-COV-003"
    assert "missing coverage artifact" in result.reason


# --- Additional fixture-matrix cases (ticket Test plan) -------------------


def test_evaluate_package_at_floor_exactly_passes(tmp_path: Path) -> None:
    pkg = PackageConfig(
        "services/api",
        floor=85.0,
        baseline=85.0,
        artifact="py-coverage",
        report_format="coverage-xml",
    )
    report_path = _write(tmp_path / "coverage.xml", _coverage_xml(0.85))
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "PASS"


def test_evaluate_package_regression_within_tolerance_passes(tmp_path: Path) -> None:
    pkg = PackageConfig(
        "packages/ui",
        floor=80.0,
        baseline=91.0,
        artifact="coverage-unit-frontend",
        report_format="lcov",
    )
    # 90.6% is 0.4pp below baseline — within the 0.5pp tolerance.
    report_path = _write(tmp_path / "lcov.info", _lcov(lines_found=1000, lines_hit=906))
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "PASS"


def test_evaluate_package_above_baseline_passes(tmp_path: Path) -> None:
    pkg = PackageConfig(
        "packages/protocol",
        floor=85.0,
        baseline=88.0,
        artifact="coverage-unit-engine",
        report_format="lcov",
    )
    report_path = _write(tmp_path / "lcov.info", _lcov(lines_found=1000, lines_hit=894))
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "PASS"
    assert result.measured == pytest.approx(89.4)


def test_parse_lcov_malformed_raises() -> None:
    with pytest.raises(CoverageGateError, match="malformed or empty"):
        parse_lcov("this is not an lcov file\n")


def test_parse_coverage_xml_malformed_raises() -> None:
    with pytest.raises(CoverageGateError, match="malformed coverage.xml"):
        parse_coverage_xml("<not-xml")


def test_parse_coverage_xml_missing_line_rate_raises() -> None:
    with pytest.raises(CoverageGateError, match="line-rate"):
        parse_coverage_xml("<coverage></coverage>")


def test_evaluate_package_malformed_lcov_is_missing_artifact_failure(
    tmp_path: Path,
) -> None:
    pkg = PackageConfig(
        "packages/chart-engine",
        floor=85.0,
        baseline=85.0,
        artifact="coverage-unit-engine",
        report_format="lcov",
    )
    report_path = _write(tmp_path / "lcov.info", "garbage, not lcov at all\n")
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "FAIL"
    assert result.code == "CI-COV-003"


def test_evaluate_package_malformed_coverage_xml_is_missing_artifact_failure(
    tmp_path: Path,
) -> None:
    pkg = PackageConfig(
        "services/api",
        floor=85.0,
        baseline=85.0,
        artifact="py-coverage",
        report_format="coverage-xml",
    )
    report_path = _write(tmp_path / "coverage.xml", "<broken")
    result = evaluate_package(pkg, report_path, tolerance_pp=0.5)
    assert result.verdict == "FAIL"
    assert result.code == "CI-COV-003"


# --- Config loading --------------------------------------------------------


def test_load_config_reads_real_baselines_file() -> None:
    baselines_path = (
        Path(__file__).resolve().parents[2] / "tools" / "ci" / "coverage-baselines.json"
    )
    tolerance, packages = load_config(baselines_path)
    assert tolerance == pytest.approx(0.5)
    assert "services/api" in packages
    assert packages["services/api"].floor == pytest.approx(85.0)


def test_load_config_missing_tolerance_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "packages": {
                    "x": {
                        "floor": 1,
                        "baseline": 1,
                        "artifact": "a",
                        "report_format": "lcov",
                    }
                }
            }
        )
    )
    with pytest.raises(CoverageGateError, match="tolerance_pp"):
        load_config(bad)


def test_load_config_missing_packages_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"tolerance_pp": 0.5}))
    with pytest.raises(CoverageGateError, match="packages"):
        load_config(bad)


def test_load_config_malformed_package_entry_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"tolerance_pp": 0.5, "packages": {"x": {"floor": "not-a-number"}}})
    )
    with pytest.raises(CoverageGateError, match="malformed package entry"):
        load_config(bad)


def test_load_config_unreadable_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CoverageGateError, match="cannot read"):
        load_config(tmp_path / "does-not-exist.json")


# --- evaluate_all / summary table ------------------------------------------


def test_evaluate_all_mixed_pass_and_fail(tmp_path: Path) -> None:
    packages = {
        "services/api": PackageConfig(
            "services/api", 85.0, 85.0, "py-coverage", "coverage-xml"
        ),
        "packages/ui": PackageConfig(
            "packages/ui", 80.0, 80.0, "coverage-unit-frontend", "lcov"
        ),
    }
    _write(tmp_path / "py-coverage" / "coverage.xml", _coverage_xml(0.90))
    _write(tmp_path / "coverage-unit-frontend" / "lcov.info", _lcov(1000, 700))

    report = evaluate_all(packages, tmp_path, tolerance_pp=0.5)
    verdicts = {r.name: r.verdict for r in report.results}
    assert verdicts["services/api"] == "PASS"
    assert verdicts["packages/ui"] == "FAIL"
    assert report.conclusion == "failure"


def test_render_summary_table_uses_words_not_colour() -> None:
    packages = {
        "services/api": PackageConfig(
            "services/api", 85.0, 85.0, "py-coverage", "coverage-xml"
        )
    }
    report = evaluate_all(packages, Path("/nonexistent"), tolerance_pp=0.5)
    table = render_summary_table(report)
    assert "PASS" in table or "FAIL" in table
    assert "package" in table and "verdict" in table


def test_parse_coverage_xml_non_numeric_line_rate_raises() -> None:
    with pytest.raises(CoverageGateError, match="non-numeric line-rate"):
        parse_coverage_xml('<coverage line-rate="not-a-number"></coverage>')


def test_read_measured_coverage_unknown_format_raises(tmp_path: Path) -> None:
    from tools.ci.coverage_gate import read_measured_coverage

    report_path = _write(tmp_path / "report.txt", "x")
    with pytest.raises(CoverageGateError, match="unknown report_format"):
        read_measured_coverage(report_path, "unknown-format")


def test_read_measured_coverage_missing_file_raises(tmp_path: Path) -> None:
    from tools.ci.coverage_gate import read_measured_coverage

    with pytest.raises(CoverageGateError, match="not found"):
        read_measured_coverage(tmp_path / "nope.info", "lcov")


def test_parse_lcov_zero_lines_found_returns_zero() -> None:
    assert parse_lcov("SF:x.ts\nLF:0\nLH:0\nend_of_record\n") == 0.0


# --- CLI main() -------------------------------------------------------------


def test_main_passes_writes_summary_and_returns_zero(tmp_path: Path) -> None:
    from tools.ci.coverage_gate import main

    baselines = tmp_path / "coverage-baselines.json"
    baselines.write_text(
        json.dumps(
            {
                "tolerance_pp": 0.5,
                "packages": {
                    "services/api": {
                        "floor": 85.0,
                        "baseline": 85.0,
                        "artifact": "py-coverage",
                        "report_format": "coverage-xml",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    report_dir = tmp_path / "artifacts"
    _write(report_dir / "py-coverage" / "coverage.xml", _coverage_xml(0.90))
    summary_out = tmp_path / "summary.md"

    rc = main(
        [
            "--baselines",
            str(baselines),
            "--report-dir",
            str(report_dir),
            "--summary-out",
            str(summary_out),
        ]
    )
    assert rc == 0
    assert "services/api" in summary_out.read_text(encoding="utf-8")


def test_main_fails_and_prints_error_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools.ci.coverage_gate import main

    baselines = tmp_path / "coverage-baselines.json"
    baselines.write_text(
        json.dumps(
            {
                "tolerance_pp": 0.5,
                "packages": {
                    "services/api": {
                        "floor": 85.0,
                        "baseline": 85.0,
                        "artifact": "py-coverage",
                        "report_format": "coverage-xml",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    rc = main(
        ["--baselines", str(baselines), "--report-dir", str(tmp_path / "no-artifacts")]
    )
    assert rc == 1
    assert "CI-COV-003" in capsys.readouterr().err


def test_main_ratchet_writes_proposals_file(tmp_path: Path) -> None:
    from tools.ci.coverage_gate import main

    baselines = tmp_path / "coverage-baselines.json"
    baselines.write_text(
        json.dumps(
            {
                "tolerance_pp": 0.5,
                "packages": {
                    "packages/protocol": {
                        "floor": 85.0,
                        "baseline": 88.0,
                        "artifact": "coverage-unit-engine",
                        "report_format": "lcov",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    report_dir = tmp_path / "artifacts"
    _write(report_dir / "coverage-unit-engine" / "lcov.info", _lcov(1000, 894))
    ratchet_out = tmp_path / "ratchet.json"

    rc = main(
        [
            "--baselines",
            str(baselines),
            "--report-dir",
            str(report_dir),
            "--ratchet",
            "--ratchet-out",
            str(ratchet_out),
        ]
    )
    assert rc == 0
    proposals = json.loads(ratchet_out.read_text(encoding="utf-8"))
    assert proposals == {"packages/protocol": 89.4}


def test_main_bad_config_returns_two(tmp_path: Path) -> None:
    from tools.ci.coverage_gate import main

    baselines = tmp_path / "coverage-baselines.json"
    baselines.write_text("not json", encoding="utf-8")
    assert main(["--baselines", str(baselines)]) == 2


# --- Lane applicability (path-filtered lanes) -----------------------------


def _engine_pkg() -> PackageConfig:
    return PackageConfig(
        "packages/chart-engine",
        floor=85.0,
        baseline=85.0,
        artifact="coverage-unit-engine",
        report_format="lcov",
    )


def test_missing_artifact_is_na_when_producing_lane_did_not_run(tmp_path: Path) -> None:
    # A py-only PR skips the js lane; frontend/engine artifacts legitimately do not exist.
    report = evaluate_all(
        {"packages/chart-engine": _engine_pkg()},
        tmp_path,
        tolerance_pp=0.5,
        ran_lanes={"py"},
    )
    (r,) = report.results
    assert r.verdict == "N/A"
    assert r.code is None
    assert report.conclusion == "success"


def test_missing_artifact_still_fails_when_producing_lane_ran(tmp_path: Path) -> None:
    report = evaluate_all(
        {"packages/chart-engine": _engine_pkg()},
        tmp_path,
        tolerance_pp=0.5,
        ran_lanes={"js", "py"},
    )
    (r,) = report.results
    assert r.verdict == "FAIL"
    assert r.code == "CI-COV-003"
    assert report.conclusion == "failure"


def test_ran_lanes_none_requires_every_artifact(tmp_path: Path) -> None:
    # Backwards compatible: no lane info means every configured package is applicable.
    report = evaluate_all(
        {"packages/chart-engine": _engine_pkg()}, tmp_path, tolerance_pp=0.5
    )
    assert report.results[0].code == "CI-COV-003"
