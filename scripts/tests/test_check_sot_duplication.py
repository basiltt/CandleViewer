"""Unit tests for scripts/check_sot_duplication.py (GOV-003)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_sot_duplication


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


REGISTRY = {
    "registries": [
        {
            "id": "required-check-names",
            "owner_file": "CONSTITUTION.md",
            "owner_section": "9",
            "threshold": 3,
            "tokens": ["unit-backend", "unit-engine", "unit-frontend", "engine-bench", "pr-metadata"],
        }
    ]
}


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    _init_repo(tmp_path)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    registry_path = scripts_dir / "sot-registry.json"
    registry_path.write_text(json.dumps(REGISTRY), encoding="utf-8")
    allowlist_path = scripts_dir / "sot-allowlist.txt"
    allowlist_path.write_text("# empty\n", encoding="utf-8")
    return registry_path, allowlist_path


def test_duplicated_list_at_threshold_reports_gov003(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry_path, allowlist_path = _setup(tmp_path)
    _write(
        tmp_path,
        "CONTRIBUTING.md",
        "Required checks: unit-backend, unit-engine, unit-frontend, engine-bench, pr-metadata.\n",
    )
    _add_all(tmp_path)

    exit_code = check_sot_duplication.main(
        [
            "--repo-root",
            str(tmp_path),
            "--registry",
            str(registry_path),
            "--allowlist",
            str(allowlist_path),
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "GOV-003" in out
    assert "CONTRIBUTING.md" in out
    assert "CONSTITUTION.md" in out


def test_single_mention_below_threshold_is_clean(tmp_path: Path) -> None:
    registry_path, allowlist_path = _setup(tmp_path)
    _write(tmp_path, "docs/note.md", "See the pr-metadata check in CONSTITUTION.md section 9.\n")
    _add_all(tmp_path)

    exit_code = check_sot_duplication.main(
        [
            "--repo-root",
            str(tmp_path),
            "--registry",
            str(registry_path),
            "--allowlist",
            str(allowlist_path),
        ]
    )
    assert exit_code == 0


def test_allowlisted_duplication_is_clean(tmp_path: Path) -> None:
    registry_path, _ = _setup(tmp_path)
    allowlist_path = tmp_path / "scripts" / "sot-allowlist.txt"
    allowlist_path.write_text(
        "CONTRIBUTING.md:required-check-names:unit-backend\n"
        "# reason: explanatory prose mention, not a restated list\n"
        "CONTRIBUTING.md:required-check-names:unit-engine\n"
        "# reason: same\n"
        "CONTRIBUTING.md:required-check-names:unit-frontend\n"
        "# reason: same\n",
        encoding="utf-8",
    )
    _write(
        tmp_path,
        "CONTRIBUTING.md",
        "Required checks: unit-backend, unit-engine, unit-frontend.\n",
    )
    _add_all(tmp_path)

    exit_code = check_sot_duplication.main(
        [
            "--repo-root",
            str(tmp_path),
            "--registry",
            str(registry_path),
            "--allowlist",
            str(allowlist_path),
        ]
    )
    assert exit_code == 0


def test_owner_file_itself_is_never_flagged(tmp_path: Path) -> None:
    registry_path, allowlist_path = _setup(tmp_path)
    _write(
        tmp_path,
        "CONSTITUTION.md",
        "unit-backend, unit-engine, unit-frontend, engine-bench, pr-metadata.\n",
    )
    _add_all(tmp_path)

    exit_code = check_sot_duplication.main(
        [
            "--repo-root",
            str(tmp_path),
            "--registry",
            str(registry_path),
            "--allowlist",
            str(allowlist_path),
        ]
    )
    assert exit_code == 0
