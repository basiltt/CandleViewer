"""Unit tests for scripts/check_markdown_governance_docs.py (GOV-006).

Regression (originating case: QA defect #1563 P2) -- E01-Q02's ticket body
scope bullet "markdownlint over governance documents + relative-link
resolution missing from workflow" was never implemented; this suite proves
the checker actually flags broken headings, broken relative links and
passes on the real governance docs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_markdown_governance_docs as gov006


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_clean_doc_has_no_violations(tmp_path: Path) -> None:
    _write(tmp_path / "doc.md", "# Title\n\nBody text.\n")
    violations = gov006.find_violations(str(tmp_path), ("doc.md",))
    assert violations == []


def test_broken_relative_link_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "doc.md", "See [x](./missing.md) for details.\n")
    violations = gov006.find_violations(str(tmp_path), ("doc.md",))
    assert any("relative link target does not exist" in v.detail for v in violations)


def test_valid_relative_link_is_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "other.md", "# Other\n")
    _write(tmp_path / "doc.md", "See [x](./other.md) for details.\n")
    violations = gov006.find_violations(str(tmp_path), ("doc.md",))
    assert violations == []


def test_external_and_anchor_links_are_ignored(tmp_path: Path) -> None:
    _write(
        tmp_path / "doc.md",
        "[ext](https://example.com) [anchor](#section) [mail](mailto:a@b.com)\n",
    )
    violations = gov006.find_violations(str(tmp_path), ("doc.md",))
    assert violations == []


def test_heading_level_jump_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "doc.md", "# Title\n\n#### Too deep\n")
    violations = gov006.find_violations(str(tmp_path), ("doc.md",))
    assert any("heading level jumps" in v.detail for v in violations)


def test_hard_tab_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "doc.md", "# Title\n\n\tindented with a tab\n")
    violations = gov006.find_violations(str(tmp_path), ("doc.md",))
    assert any("hard tab" in v.detail for v in violations)


def test_missing_doc_raises_internal_error(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(gov006.InternalError):
        gov006.find_violations(str(tmp_path), ("nope.md",))


def test_main_exits_zero_on_real_governance_docs() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    exit_code = gov006.main(["--repo-root", str(repo_root)])
    assert exit_code == 0


def test_main_json_output_is_structured(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "doc.md", "See [x](./missing.md).\n")
    exit_code = gov006.main(["--repo-root", str(tmp_path), "--docs", "doc.md", "--json"])
    out = capsys.readouterr().out
    assert exit_code == 1
    payload = __import__("json").loads(out)
    assert payload[0]["code"] == "GOV-006"
