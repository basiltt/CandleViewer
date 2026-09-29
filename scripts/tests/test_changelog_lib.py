"""Unit tests for tools/ci/changelog_lib.py (E03-T11, CI-REL-001/CI-REL-002).

Fixture corpus per ticket "Test plan": feat, fix, perf, refactor, `!`,
BREAKING footer, revert, merge commits, non-conventional.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.changelog_lib import (
    Bump,
    Category,
    build_changelog_update,
    check_changelog_fragment,
    check_security_wording,
    is_pr_exempt,
    parse_commit,
)


def test_parse_commit_feat_maps_to_features_and_minor() -> None:
    c = parse_commit("abc1234", "feat(chart-engine): add volume pane")
    assert c.is_conventional
    assert c.category == Category.FEATURES
    assert c.bump == Bump.MINOR
    assert c.scope == "chart-engine"


def test_parse_commit_fix_maps_to_fixes_and_patch() -> None:
    c = parse_commit("abc1234", "fix(oms-execution): correct rounding")
    assert c.category == Category.FIXES
    assert c.bump == Bump.PATCH


def test_parse_commit_perf_maps_to_performance_and_patch() -> None:
    c = parse_commit("abc1234", "perf(chart-engine): batch buffer uploads")
    assert c.category == Category.PERFORMANCE
    assert c.bump == Bump.PATCH


def test_parse_commit_refactor_has_no_category_or_bump() -> None:
    c = parse_commit("abc1234", "refactor(backend-platform): extract helper")
    assert c.is_conventional
    assert c.category is None
    assert c.bump == Bump.NONE


def test_parse_commit_bang_forces_breaking_major() -> None:
    c = parse_commit("abc1234", "feat(auth-rbac)!: drop legacy session cookie")
    assert c.breaking
    assert c.bump == Bump.MAJOR
    assert c.category == Category.BREAKING


def test_parse_commit_breaking_change_footer_forces_major() -> None:
    msg = "feat(auth-rbac): rotate session keys\n\nBREAKING CHANGE: old sessions are invalidated"
    c = parse_commit("abc1234", msg)
    assert c.breaking
    assert c.bump == Bump.MAJOR
    assert c.breaking_detail == "old sessions are invalidated"


def test_parse_commit_revert_without_breaking_has_no_bump() -> None:
    c = parse_commit("abc1234", "revert: feat(chart-engine): add volume pane")
    assert c.is_conventional
    assert c.bump == Bump.NONE
    assert c.category is None


def test_parse_commit_merge_commit_is_excluded() -> None:
    c = parse_commit("abc1234", "Merge pull request #42 from feat/foo")
    assert c.is_merge
    assert not c.is_conventional


def test_parse_commit_non_conventional_is_rejected() -> None:
    c = parse_commit("abc1234", "wip fixes")
    assert not c.is_conventional
    assert c.category is None


def test_build_changelog_update_highest_bump_wins() -> None:
    commits = [
        parse_commit("s1", "fix(oms-execution): a"),
        parse_commit("s2", "feat(auth-rbac)!: b"),
        parse_commit("s3", "feat(chart-engine): c"),
    ]
    update = build_changelog_update(commits)
    assert update.bump == Bump.MAJOR
    assert update.triggering_breaking_commits == ["s2"]
    assert len(update.entries[Category.FEATURES]) == 1
    assert len(update.entries[Category.BREAKING]) == 1
    assert len(update.entries[Category.FIXES]) == 1


def test_build_changelog_update_ignores_merge_and_non_conventional() -> None:
    commits = [
        parse_commit("s1", "Merge pull request #1 from x"),
        parse_commit("s2", "wip"),
    ]
    update = build_changelog_update(commits)
    assert update.bump == Bump.NONE
    assert not update.has_entries()


def test_is_pr_exempt_true_for_docs_chore_ci() -> None:
    assert is_pr_exempt("docs: fix typo in sitemap")
    assert is_pr_exempt("chore(infra-devops): bump deps")
    assert is_pr_exempt("ci: tighten timeout")


def test_is_pr_exempt_false_for_feat() -> None:
    assert not is_pr_exempt("feat(chart): add volume pane")


def test_check_changelog_fragment_conventional_title_passes() -> None:
    result = check_changelog_fragment("feat(chart): add volume pane", "")
    assert result.ok


def test_check_changelog_fragment_docs_only_is_exempt() -> None:
    result = check_changelog_fragment("docs: fix typo in sitemap", "")
    assert result.ok


def test_check_changelog_fragment_non_conventional_without_footer_fails() -> None:
    result = check_changelog_fragment("wip fixes", "no footer here")
    assert not result.ok
    assert result.error_code == "CI-REL-001"


def test_check_changelog_fragment_non_conventional_with_footer_passes() -> None:
    body = "Some PR description.\n\nChangelog: adds a new volume pane to the chart\n"
    result = check_changelog_fragment("wip fixes", body)
    assert result.ok


def test_check_security_wording_flags_exploit_language() -> None:
    result = check_security_wording(
        ["- Hardened API-key decryption path", "- Fixed exploit in the payload parser"]
    )
    assert not result.ok
    assert len(result.violations) == 1


def test_check_security_wording_clean_lines_pass() -> None:
    result = check_security_wording(["- Hardened API-key decryption path against timing side-channel"])
    assert result.ok
    assert result.violations == []
