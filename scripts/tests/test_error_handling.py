"""Tests for internal-error handling (exit code 2) shared by both checkers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_rule_refs
import check_sot_duplication


def _init_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True)


def test_check_rule_refs_bad_encoding_exits_two(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "CONSTITUTION.md").write_text("**C-1.1** ok\n", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\x00\x01 not valid utf-8 C-1.1")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    exit_code = check_rule_refs.main(["--repo-root", str(tmp_path)])
    assert exit_code == 2


def test_check_sot_duplication_missing_registry_exits_two(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "CONSTITUTION.md").write_text("nothing\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    exit_code = check_sot_duplication.main(
        [
            "--repo-root",
            str(tmp_path),
            "--registry",
            str(tmp_path / "does-not-exist.json"),
        ]
    )
    assert exit_code == 2
