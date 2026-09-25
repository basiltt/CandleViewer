"""Unit tests for scripts/check_rule_refs.py (GOV-002)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_rule_refs


def _init_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True)


def _write(repo_root: Path, rel_path: str, content: str) -> Path:
    path = repo_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _add_all(repo_root: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True)


def _constitution(declared_ids: list[str]) -> str:
    lines = [f"**{rid}** Some rule text.\n" for rid in declared_ids]
    return "".join(lines)


def test_clean_tree_exits_zero(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(tmp_path, "CONSTITUTION.md", _constitution(["C-1.1", "C-2.6"]))
    _write(tmp_path, "docs/note.md", "See C-1.1 and C-2.6 for details.\n")
    _add_all(tmp_path)

    exit_code = check_rule_refs.main(["--repo-root", str(tmp_path)])
    assert exit_code == 0


def test_dangling_reference_reports_gov002_and_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_repo(tmp_path)
    _write(tmp_path, "CONSTITUTION.md", _constitution(["C-1.1"]))
    _write(tmp_path, "docs/note.md", "line one\nsee C-99.9 for details\n")
    _add_all(tmp_path)

    exit_code = check_rule_refs.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "GOV-002" in out
    assert "docs/note.md:2 C-99.9" in out


def test_untracked_scratch_file_is_ignored(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(tmp_path, "CONSTITUTION.md", _constitution(["C-1.1"]))
    _write(tmp_path, "scratch.md", "references C-77.7 which does not exist\n")
    # Deliberately not added/committed — must be ignored via `git ls-files`.

    exit_code = check_rule_refs.main(["--repo-root", str(tmp_path)])
    assert exit_code == 0
