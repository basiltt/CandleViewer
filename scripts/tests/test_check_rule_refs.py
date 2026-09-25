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


def test_json_output_emits_structured_violations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_repo(tmp_path)
    _write(tmp_path, "CONSTITUTION.md", _constitution(["C-1.1"]))
    _write(tmp_path, "docs/note.md", "see C-99.9\n")
    _add_all(tmp_path)

    exit_code = check_rule_refs.main(["--repo-root", str(tmp_path), "--json"])
    out = capsys.readouterr().out

    assert exit_code == 1
    payload = __import__("json").loads(out)
    assert payload == [
        {"code": "GOV-002", "path": "docs/note.md", "line": 1, "rule_id": "C-99.9"}
    ]


def test_fix_suggest_lists_nearest_ids_in_same_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_repo(tmp_path)
    _write(tmp_path, "CONSTITUTION.md", _constitution(["C-2.1", "C-2.6", "C-4.1"]))
    _write(tmp_path, "docs/note.md", "see C-2.9 for details\n")
    _add_all(tmp_path)

    exit_code = check_rule_refs.main(["--repo-root", str(tmp_path), "--fix-suggest"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "nearest declared ids for C-2.9: C-2.1, C-2.6" in out


def test_fix_suggest_falls_back_to_all_ids_when_section_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_repo(tmp_path)
    _write(tmp_path, "CONSTITUTION.md", _constitution(["C-4.1"]))
    _write(tmp_path, "docs/note.md", "see C-9.9 for details\n")
    _add_all(tmp_path)

    exit_code = check_rule_refs.main(["--repo-root", str(tmp_path), "--fix-suggest"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "nearest declared ids for C-9.9: C-4.1" in out


def test_codeowners_basename_is_scanned_without_md_extension(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(tmp_path, "CONSTITUTION.md", _constitution(["C-1.1"]))
    _write(tmp_path, ".github/CODEOWNERS", "# owns C-88.8\n")
    _add_all(tmp_path)

    exit_code = check_rule_refs.main(["--repo-root", str(tmp_path)])
    assert exit_code == 1


def test_nearest_ids_malformed_rule_id_falls_back_to_sorted_declared() -> None:
    result = check_rule_refs.nearest_ids("not-a-rule-id", {"C-1.1", "C-2.2"})
    assert result == ["C-1.1", "C-2.2"]


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
