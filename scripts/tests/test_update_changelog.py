"""Integration-style tests for tools/ci/update_changelog.py — acceptance
scenario "A feature merge lands in the Unreleased changelog" (E03-T11).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.changelog_lib import parse_commit
from tools.ci.update_changelog import _default_changelog, apply_update


def test_apply_update_adds_feature_bullet_under_unreleased_features() -> None:
    commits = [parse_commit("deadbee", "feat(chart): add volume pane")]
    new_text, changed = apply_update(_default_changelog(), commits)
    assert changed
    features_idx = new_text.index("### Features")
    fixes_idx = new_text.index("### Fixes")
    section = new_text[features_idx:fixes_idx]
    assert "add volume pane" in section
    assert "(deadbee)" in section


def test_apply_update_no_changelog_worthy_commits_is_noop() -> None:
    commits = [parse_commit("s1", "refactor(backend-platform): extract helper")]
    original = _default_changelog()
    new_text, changed = apply_update(original, commits)
    assert not changed
    assert new_text == original


def test_apply_update_appends_to_existing_entries_without_duplicating_headings() -> None:
    base = _default_changelog()
    commits1 = [parse_commit("s1", "feat(chart): add volume pane")]
    text1, _ = apply_update(base, commits1)
    commits2 = [parse_commit("s2", "feat(chart): add heatmap pane")]
    text2, changed2 = apply_update(text1, commits2)
    assert changed2
    assert text2.count("### Features") == 1
    assert "add volume pane" in text2
    assert "add heatmap pane" in text2


def test_apply_update_from_commits_json_round_trip(tmp_path: Path) -> None:
    commits_path = tmp_path / "commits.json"
    commits_path.write_text(
        json.dumps([{"sha": "abc1234", "message": "fix(oms-execution): correct rounding"}]),
        encoding="utf-8",
    )
    raw = json.loads(commits_path.read_text(encoding="utf-8"))
    commits = [parse_commit(item["sha"], item["message"]) for item in raw]
    new_text, changed = apply_update(_default_changelog(), commits)
    assert changed
    assert "correct rounding" in new_text
