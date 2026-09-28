"""Unit tests for tools/ci/flaky_quarantine_report.py (E02-T10, C-9.3)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.flaky_quarantine_report import build_report, scan_pytest_file, scan_vitest_file


def test_scan_pytest_file_referenced_marker(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text(
        "import pytest\n"
        "@pytest.mark.flaky  # ticket: OF-42\n"
        "def test_thing():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    entries = scan_pytest_file(f, tmp_path)
    assert len(entries) == 1
    assert entries[0].ticket == "OF-42"
    assert entries[0].referenced


def test_scan_pytest_file_unreferenced_marker(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text(
        "import pytest\n@pytest.mark.flaky\ndef test_thing():\n    assert True\n",
        encoding="utf-8",
    )
    entries = scan_pytest_file(f, tmp_path)
    assert len(entries) == 1
    assert not entries[0].referenced


def test_scan_vitest_file_referenced_marker(tmp_path: Path) -> None:
    f = tmp_path / "x.test.mjs"
    f.write_text(
        '// ticket: OF-99\nit.flaky("does a thing", () => {});\n',
        encoding="utf-8",
    )
    entries = scan_vitest_file(f, tmp_path)
    assert len(entries) == 1
    assert entries[0].ticket == "OF-99"


def test_scan_vitest_file_unreferenced_marker(tmp_path: Path) -> None:
    f = tmp_path / "x.test.mjs"
    f.write_text('it.flaky("does a thing", () => {});\n', encoding="utf-8")
    entries = scan_vitest_file(f, tmp_path)
    assert len(entries) == 1
    assert not entries[0].referenced


def test_build_report_skips_venv_and_node_modules(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "test_ignored.py").write_text(
        "@pytest.mark.flaky\ndef test_x(): pass\n", encoding="utf-8"
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.test.mjs").write_text(
        'it.flaky("x", () => {});\n', encoding="utf-8"
    )
    report = build_report(tmp_path)
    assert report.entries == ()


def test_build_report_finds_real_files(tmp_path: Path) -> None:
    (tmp_path / "test_real.py").write_text(
        "@pytest.mark.flaky  # ticket: OF-1\ndef test_x(): pass\n", encoding="utf-8"
    )
    report = build_report(tmp_path)
    assert len(report.entries) == 1
    assert report.unreferenced == ()


def test_report_to_dict_counts_unreferenced() -> None:
    from tools.ci.flaky_quarantine_report import QuarantineEntry, QuarantineReport

    report = QuarantineReport(
        entries=(
            QuarantineEntry(path="a.py", line=1, ticket="OF-1"),
            QuarantineEntry(path="b.py", line=2, ticket=None),
        )
    )
    d = report.to_dict()
    assert d["unreferenced_count"] == 1
    assert len(d["quarantined"]) == 2
