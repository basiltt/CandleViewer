from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.gh import run_guard
from scripts.gh.models import Comment, Issue


def _issue(**overrides) -> Issue:
    base = dict(number=1, kind="Story", labels=frozenset({"type/story"}), body="", owner_login="alice")
    base.update(overrides)
    return Issue(**base)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_REPO", "basiltt/CandleViewer")
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("ACTOR_LOGIN", "some-human")
    monkeypatch.delenv("GOVERNANCE_ENFORCE", raising=False)


def test_enforcing_defaults_false() -> None:
    assert run_guard._enforcing() is False


def test_enforcing_true_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_ENFORCE", "true")
    assert run_guard._enforcing() is True


def test_check_team_returns_false_on_success() -> None:
    with patch("scripts.gh.gh_adapter.is_team_member", return_value=True):
        assert run_guard._check_team("CandleViewer", "qa", "bob") is False


def test_check_team_returns_true_on_failure() -> None:
    from scripts.gh.gh_adapter import GhApiError

    with patch("scripts.gh.gh_adapter.is_team_member", side_effect=GhApiError("boom")):
        assert run_guard._check_team("CandleViewer", "qa", "bob") is True


def test_annotate_team_membership_flags_failure() -> None:
    from scripts.gh.gh_adapter import GhApiError

    comments = [Comment(author_login="bob", body="x")]
    with patch("scripts.gh.gh_adapter.is_team_member", side_effect=GhApiError("boom")):
        annotated, failed = run_guard._annotate_team_membership(comments, "CandleViewer", "qa")
    assert failed is True
    assert annotated[0].author_is_team_member is False


def test_annotate_team_membership_marks_member() -> None:
    comments = [Comment(author_login="bob", body="x")]
    with patch("scripts.gh.gh_adapter.is_team_member", return_value=True):
        annotated, failed = run_guard._annotate_team_membership(comments, "CandleViewer", "qa")
    assert failed is False
    assert annotated[0].author_is_team_member is True


def test_main_kind_sync_observe_only_does_not_call_add_labels() -> None:
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(_issue(kind="Bug"), [])):
        with patch.object(run_guard.gh_adapter, "add_labels") as mock_add:
            rc = run_guard.main(["kind-sync"])
    mock_add.assert_not_called()
    assert rc == 0


def test_main_kind_sync_enforcing_applies_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_ENFORCE", "true")
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(_issue(kind="Bug"), [])):
        with patch.object(run_guard.gh_adapter, "add_labels") as mock_add:
            with patch.object(run_guard.gh_adapter, "post_or_update_decision_comment"):
                run_guard.main(["kind-sync"])
    mock_add.assert_called_once()


def test_main_qa_guard_blocks_and_returns_1_when_enforcing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_ENFORCE", "true")
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(_issue(), [])):
        with patch.object(run_guard.gh_adapter, "reopen_issue") as mock_reopen:
            with patch.object(run_guard.gh_adapter, "post_or_update_decision_comment"):
                rc = run_guard.main(["qa-guard"])
    mock_reopen.assert_called_once()
    assert rc == 1


def test_main_qa_guard_observe_only_never_reopens() -> None:
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(_issue(), [])):
        with patch.object(run_guard.gh_adapter, "reopen_issue") as mock_reopen:
            rc = run_guard.main(["qa-guard"])
    mock_reopen.assert_not_called()
    assert rc == 0


def test_main_security_guard_label_sync_mode() -> None:
    issue = _issue(kind="Task", labels=frozenset({"area/auth-rbac"}))
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(issue, [])):
        with patch.object(run_guard.gh_adapter, "add_labels") as mock_add:
            run_guard.main(["security-guard", "--mode", "label-sync"])
    mock_add.assert_not_called()  # observe-only by default


def test_main_a11y_guard_uses_repo_owner_and_name() -> None:
    issue = _issue(kind="Task", labels=frozenset({"a11y"}), body="### a11y evidence\n\n_No response_\n")
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(issue, [])):
        rc = run_guard.main(["a11y-guard"])
    assert rc == 0
