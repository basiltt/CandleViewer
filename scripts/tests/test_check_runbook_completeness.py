"""Tests for scripts/check_runbook_completeness.py (E03-T15, CI-DOC-001)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from check_runbook_completeness import (
    check,
    collect_documented_codes,
    collect_emitted_codes,
    main,
)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "tools" / "ci").mkdir(parents=True)
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "docs").mkdir(parents=True)
    return tmp_path


def test_collect_emitted_codes_finds_code_and_source_file(fake_repo: Path) -> None:
    (fake_repo / "tools" / "ci" / "gate.py").write_text(
        '"""Emits CI-GEN-001 on drift."""\n', encoding="utf-8"
    )
    emitted = collect_emitted_codes(fake_repo)
    assert "CI-GEN-001" in emitted
    assert emitted["CI-GEN-001"] == ["tools/ci/gate.py"]


def test_collect_emitted_codes_dedupes_across_files(fake_repo: Path) -> None:
    (fake_repo / "tools" / "ci" / "a.py").write_text("CI-SEC-001\n", encoding="utf-8")
    (fake_repo / "tools" / "ci" / "b.py").write_text("CI-SEC-001\n", encoding="utf-8")
    emitted = collect_emitted_codes(fake_repo)
    assert sorted(emitted["CI-SEC-001"]) == ["tools/ci/a.py", "tools/ci/b.py"]


def test_collect_emitted_codes_ignores_pycache(fake_repo: Path) -> None:
    pycache = fake_repo / "tools" / "ci" / "__pycache__"
    pycache.mkdir()
    (pycache / "gate.cpython-313.pyc").write_bytes(b"CI-GEN-001")
    emitted = collect_emitted_codes(fake_repo)
    assert "CI-GEN-001" not in emitted


def test_collect_documented_codes_missing_runbook_raises(fake_repo: Path) -> None:
    from check_runbook_completeness import RunbookCompletenessError

    with pytest.raises(RunbookCompletenessError):
        collect_documented_codes(fake_repo / "docs" / "ci-runbook.md")


def test_collect_documented_codes_parses_headings(fake_repo: Path) -> None:
    runbook = fake_repo / "docs" / "ci-runbook.md"
    runbook.write_text("### CI-GEN-001 — drift\n\nDo the thing.\n", encoding="utf-8")
    assert collect_documented_codes(runbook) == {"CI-GEN-001"}


def test_check_reports_missing_code_when_emitted_but_undocumented(fake_repo: Path) -> None:
    (fake_repo / "tools" / "ci" / "gate.py").write_text("CI-GEN-001\n", encoding="utf-8")
    (fake_repo / "docs" / "ci-runbook.md").write_text("no codes here\n", encoding="utf-8")
    missing, extra = check(fake_repo, fake_repo / "docs" / "ci-runbook.md")
    assert missing == ["CI-GEN-001"]
    assert extra == []


def test_check_reports_extra_code_as_informational_only(fake_repo: Path) -> None:
    (fake_repo / "docs" / "ci-runbook.md").write_text("### CI-GEN-001\n", encoding="utf-8")
    missing, extra = check(fake_repo, fake_repo / "docs" / "ci-runbook.md")
    assert missing == []
    assert extra == ["CI-GEN-001"]


def test_check_clean_when_sets_match(fake_repo: Path) -> None:
    (fake_repo / "tools" / "ci" / "gate.py").write_text("CI-GEN-001\n", encoding="utf-8")
    (fake_repo / "docs" / "ci-runbook.md").write_text("### CI-GEN-001\n", encoding="utf-8")
    missing, extra = check(fake_repo, fake_repo / "docs" / "ci-runbook.md")
    assert missing == []
    assert extra == []


def test_main_exits_nonzero_on_missing_code(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (fake_repo / "tools" / "ci" / "gate.py").write_text("CI-GEN-001\n", encoding="utf-8")
    (fake_repo / "docs" / "ci-runbook.md").write_text("nothing\n", encoding="utf-8")
    rc = main(["--repo-root", str(fake_repo), "--runbook", "docs/ci-runbook.md"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "CI-DOC-001" in err
    assert "CI-GEN-001" in err


def test_main_exits_zero_on_clean_repo(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (fake_repo / "tools" / "ci" / "gate.py").write_text("CI-GEN-001\n", encoding="utf-8")
    (fake_repo / "docs" / "ci-runbook.md").write_text("### CI-GEN-001\n", encoding="utf-8")
    rc = main(["--repo-root", str(fake_repo), "--runbook", "docs/ci-runbook.md"])
    assert rc == 0


def test_main_exits_two_when_runbook_missing(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--repo-root", str(fake_repo), "--runbook", "docs/does-not-exist.md"])
    assert rc == 2
    assert "CI-DOC-001" in capsys.readouterr().err


def test_real_repo_runbook_is_complete() -> None:
    """Integration-flavoured regression: the actual repo runbook must cover
    every code actually emitted by the real workflow/tool sources, so this
    checker cannot pass in CI while docs/ci-runbook.md is stale."""
    repo_root = Path(__file__).resolve().parents[2]
    runbook_path = repo_root / "docs" / "ci-runbook.md"
    if not runbook_path.is_file():
        pytest.skip("docs/ci-runbook.md not present in this checkout")
    missing, _extra = check(repo_root, runbook_path)
    assert missing == [], f"undocumented codes: {missing}"
