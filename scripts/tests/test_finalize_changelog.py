"""Tests for tools/ci/finalize_changelog.py (release-train cut finalisation,
E03-T11 ticket "Technical notes" / §3 in 07-release-and-prr.md)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.changelog_lib import parse_commit
from tools.ci.finalize_changelog import finalize
from tools.ci.update_changelog import _default_changelog, apply_update


def test_finalize_moves_unreleased_entries_under_version_heading() -> None:
    base = _default_changelog()
    commits = [
        parse_commit("s1", "feat(chart): add volume pane"),
        parse_commit("s2", "fix(oms-execution): correct rounding"),
    ]
    text, _ = apply_update(base, commits)

    new_text, release_body = finalize(text, "0.3.0", "2026-10-03")

    assert "## 0.3.0 — 2026-10-03" in new_text
    assert "## 0.3.0 — 2026-10-03" in release_body
    assert "add volume pane" in release_body
    assert "correct rounding" in release_body

    # Unreleased section is fresh/empty above the new version heading.
    unreleased_idx = new_text.index("## Unreleased")
    version_idx = new_text.index("## 0.3.0")
    unreleased_section = new_text[unreleased_idx:version_idx]
    assert "add volume pane" not in unreleased_section


def test_finalize_omits_empty_categories_from_release_body() -> None:
    base = _default_changelog()
    commits = [parse_commit("s1", "feat(chart): add volume pane")]
    text, _ = apply_update(base, commits)

    _, release_body = finalize(text, "0.1.0", "2026-10-03")

    assert "### Features" in release_body
    assert "### Fixes" not in release_body
