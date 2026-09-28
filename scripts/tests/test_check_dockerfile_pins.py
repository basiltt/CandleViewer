"""Unit tests for tools/ci/check_dockerfile_pins.py (SR-131, CI-IMG-001)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.check_dockerfile_pins import check_file, main


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_check_file_digest_pinned_passes(tmp_path: Path) -> None:
    d = _write(
        tmp_path,
        "Dockerfile",
        "FROM python:3.12-slim@sha256:"
        + "a" * 64
        + " AS builder\nFROM python:3.12-slim@sha256:"
        + "a" * 64
        + " AS runtime\n",
    )
    assert check_file(d) == []


def test_check_file_floating_tag_fails(tmp_path: Path) -> None:
    d = _write(tmp_path, "Dockerfile", "FROM python:3.12-slim\n")
    violations = check_file(d)
    assert len(violations) == 1
    assert "unpinned base image" in violations[0].reason


def test_check_file_stage_reference_exempt(tmp_path: Path) -> None:
    d = _write(
        tmp_path,
        "Dockerfile",
        "FROM python:3.12-slim@sha256:" + "b" * 64 + " AS builder\nFROM builder AS runtime\n",
    )
    assert check_file(d) == []


def test_check_file_scratch_exempt(tmp_path: Path) -> None:
    d = _write(tmp_path, "Dockerfile", "FROM scratch\n")
    assert check_file(d) == []


def test_check_file_comment_lines_ignored(tmp_path: Path) -> None:
    d = _write(
        tmp_path,
        "Dockerfile",
        "# FROM python:3.12-slim\nFROM python:3.12-slim@sha256:" + "c" * 64 + "\n",
    )
    assert check_file(d) == []


def test_main_reports_violation_and_exits_1(tmp_path: Path) -> None:
    _write(tmp_path, "Dockerfile", "FROM python:3.12-slim\n")
    assert main([str(tmp_path)]) == 1


def test_main_clean_dockerfile_exits_0(tmp_path: Path) -> None:
    _write(tmp_path, "Dockerfile", "FROM python:3.12-slim@sha256:" + "d" * 64 + "\n")
    assert main([str(tmp_path)]) == 0


def test_main_no_dockerfiles_found_exits_2(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2


def test_main_missing_path_exits_2(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope")]) == 2
