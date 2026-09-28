"""Unit tests for scripts/check_governance_links.py (GOV-LINK)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_governance_links


def _write(root: Path, rel_path: str, content: str) -> Path:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_dangling_relative_link_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, "CONSTITUTION.md", "See [the plan](docs/plan/does-not-exist.md) for detail.\n")
    exit_code = check_governance_links.main(["--repo-root", str(tmp_path)])
    assert exit_code == 1


def test_resolvable_relative_link_is_clean(tmp_path: Path) -> None:
    _write(tmp_path, "docs/plan/target.md", "# Target\n")
    _write(tmp_path, "CONSTITUTION.md", "See [the plan](docs/plan/target.md) for detail.\n")
    exit_code = check_governance_links.main(["--repo-root", str(tmp_path)])
    assert exit_code == 0


def test_external_and_anchor_links_are_skipped(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "CONSTITUTION.md",
        "See [external](https://example.com/nope) and [anchor](#some-heading).\n",
    )
    exit_code = check_governance_links.main(["--repo-root", str(tmp_path)])
    assert exit_code == 0


def test_link_with_anchor_suffix_resolves_the_file_part(tmp_path: Path) -> None:
    _write(tmp_path, "docs/plan/target.md", "# Target\n")
    _write(
        tmp_path,
        "CONSTITUTION.md",
        "See [section](docs/plan/target.md#some-section) for detail.\n",
    )
    exit_code = check_governance_links.main(["--repo-root", str(tmp_path)])
    assert exit_code == 0


def test_missing_target_file_entirely_is_a_clean_run(tmp_path: Path) -> None:
    # None of the default target/glob files exist in this tmp_path fixture -
    # the checker must not crash, just find nothing to scan.
    exit_code = check_governance_links.main(["--repo-root", str(tmp_path)])
    assert exit_code == 0
