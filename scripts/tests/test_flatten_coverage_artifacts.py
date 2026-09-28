"""Unit tests for tools/ci/flatten_coverage_artifacts.py (E03-T04)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.flatten_coverage_artifacts import flatten


def test_flatten_copies_web_lcov_to_expected_path(tmp_path: Path) -> None:
    report_dir = tmp_path / "coverage-artifacts"
    source = (
        report_dir
        / "coverage-unit-frontend"
        / "apps"
        / "web"
        / "coverage"
        / "lcov.info"
    )
    source.parent.mkdir(parents=True)
    source.write_text("SF:x.ts\nLF:10\nLH:8\nend_of_record\n", encoding="utf-8")

    written = flatten(report_dir)

    dest = report_dir / "coverage-unit-frontend" / "lcov.info"
    assert dest in written
    assert dest.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_flatten_skips_when_already_flat(tmp_path: Path) -> None:
    report_dir = tmp_path / "coverage-artifacts"
    dest = report_dir / "py-coverage" / "coverage.xml"
    # services/api uses coverage-xml, not lcov, so it should never be touched.
    dest.parent.mkdir(parents=True)
    dest.write_text("<coverage></coverage>", encoding="utf-8")

    written = flatten(report_dir)
    assert dest not in written


def test_flatten_missing_source_is_silently_skipped(tmp_path: Path) -> None:
    # No source files at all -> nothing written, no exception (coverage_gate.py
    # is responsible for reporting the resulting CI-COV-003).
    report_dir = tmp_path / "coverage-artifacts"
    assert flatten(report_dir) == []


def test_flatten_does_not_overwrite_existing_destination(tmp_path: Path) -> None:
    report_dir = tmp_path / "coverage-artifacts"
    existing = report_dir / "coverage-unit-engine" / "lcov.info"
    existing.parent.mkdir(parents=True)
    existing.write_text("already-here", encoding="utf-8")

    source = (
        report_dir
        / "coverage-unit-engine"
        / "packages"
        / "chart-engine"
        / "coverage"
        / "lcov.info"
    )
    source.parent.mkdir(parents=True)
    source.write_text("would-overwrite", encoding="utf-8")

    written = flatten(report_dir)
    assert existing not in written
    assert existing.read_text(encoding="utf-8") == "already-here"


def test_main_cli_prints_flattened_paths(tmp_path: Path, capsys: object) -> None:
    from tools.ci.flatten_coverage_artifacts import main

    report_dir = tmp_path / "coverage-artifacts"
    source = (
        report_dir
        / "coverage-unit-frontend"
        / "apps"
        / "web"
        / "coverage"
        / "lcov.info"
    )
    source.parent.mkdir(parents=True)
    source.write_text("SF:x.ts\nLF:10\nLH:8\nend_of_record\n", encoding="utf-8")

    rc = main([str(report_dir)])
    assert rc == 0


def test_main_defaults_to_coverage_artifacts_dir() -> None:
    from tools.ci.flatten_coverage_artifacts import main

    # No CLI arg -> defaults to Path("coverage-artifacts"), which doesn't
    # exist in the test working directory, so flatten() finds nothing and
    # returns cleanly rather than raising.
    assert main([]) == 0
