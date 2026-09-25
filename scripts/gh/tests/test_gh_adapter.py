from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from scripts.gh import gh_adapter
from scripts.gh.models import Decision


def _completed(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=0, stdout=stdout, stderr="")


def test_run_gh_raises_gh_api_error_on_failure() -> None:
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["gh"])):
        with pytest.raises(gh_adapter.GhApiError):
            gh_adapter._run_gh(["issue", "view", "1"])


def test_run_gh_raises_on_missing_binary() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(gh_adapter.GhApiError):
            gh_adapter._run_gh(["issue", "view", "1"])


def test_fetch_issue_parses_labels_and_comments() -> None:
    payload = json.dumps(
        {
            "number": 42,
            "body": "### Test plan\n\nsomething\n",
            "labels": [{"name": "type/story"}, {"name": "qa"}],
            "author": {"login": "alice"},
            "comments": [{"author": {"login": "bob"}, "body": "hello"}],
        }
    )
    with patch.object(gh_adapter, "_run_gh", return_value=payload):
        issue, comments = gh_adapter.fetch_issue("basiltt/CandleViewer", 42)
    assert issue.number == 42
    assert issue.kind == "Story"
    assert "qa" in issue.labels
    assert issue.owner_login == "alice"
    assert comments[0].author_login == "bob"
    assert comments[0].body == "hello"


def test_kind_from_labels_defaults_to_task() -> None:
    assert gh_adapter._kind_from_labels(frozenset({"area/docs"})) == "Task"


def test_is_team_member_true_on_success() -> None:
    with patch.object(gh_adapter, "_run_gh", return_value="{}"):
        assert gh_adapter.is_team_member("CandleViewer", "qa", "bob") is True


def test_is_team_member_raises_on_failure() -> None:
    with patch.object(gh_adapter, "_run_gh", side_effect=gh_adapter.GhApiError("boom")):
        with pytest.raises(gh_adapter.GhApiError):
            gh_adapter.is_team_member("CandleViewer", "qa", "bob")


def test_reopen_issue_calls_gh_reopen() -> None:
    with patch.object(gh_adapter, "_run_gh") as mock_run:
        gh_adapter.reopen_issue("basiltt/CandleViewer", 42)
    mock_run.assert_called_once_with(["issue", "reopen", "42", "--repo", "basiltt/CandleViewer"])


def test_add_labels_noop_when_empty() -> None:
    with patch.object(gh_adapter, "_run_gh") as mock_run:
        gh_adapter.add_labels("basiltt/CandleViewer", 42, frozenset())
    mock_run.assert_not_called()


def test_add_labels_calls_gh_edit() -> None:
    with patch.object(gh_adapter, "_run_gh") as mock_run:
        gh_adapter.add_labels("basiltt/CandleViewer", 42, frozenset({"security"}))
    mock_run.assert_called_once_with(
        ["issue", "edit", "42", "--repo", "basiltt/CandleViewer", "--add-label", "security"]
    )


def test_find_own_comment_locates_marker() -> None:
    payload = json.dumps(
        {"comments": [{"id": "IC_1", "body": "<!-- gov-bot:qa-guard -->\nold body"}]}
    )
    with patch.object(gh_adapter, "_run_gh", return_value=payload):
        result = gh_adapter._find_own_comment("basiltt/CandleViewer", 42, "qa-guard")
    assert result is not None
    assert result.comment_id == "IC_1"


def test_find_own_comment_returns_none_when_absent() -> None:
    payload = json.dumps({"comments": []})
    with patch.object(gh_adapter, "_run_gh", return_value=payload):
        result = gh_adapter._find_own_comment("basiltt/CandleViewer", 42, "qa-guard")
    assert result is None


def test_post_or_update_decision_comment_edits_existing() -> None:
    decision = Decision(
        allow=False,
        reason="missing sign-off",
        dod_ref="02-definition-of-ready-done.md#3.2",
        audit_note="qa-guard: BLOCKED",
        guard="qa-guard",
    )
    with patch.object(gh_adapter, "_find_own_comment", return_value=gh_adapter.ExistingComment("IC_1", "old")):
        with patch.object(gh_adapter, "_run_gh") as mock_run:
            gh_adapter.post_or_update_decision_comment("basiltt/CandleViewer", 42, decision)
    args = mock_run.call_args[0][0]
    assert "--edit-last" in args


def test_post_or_update_decision_comment_posts_new() -> None:
    decision = Decision(
        allow=True,
        reason="ok",
        dod_ref="ref",
        audit_note="note",
        guard="a11y-guard",
    )
    with patch.object(gh_adapter, "_find_own_comment", return_value=None):
        with patch.object(gh_adapter, "_run_gh") as mock_run:
            gh_adapter.post_or_update_decision_comment("basiltt/CandleViewer", 42, decision)
    args = mock_run.call_args[0][0]
    assert "--edit-last" not in args


def test_log_decision_prints_structured_line(capsys: pytest.CaptureFixture[str]) -> None:
    decision = Decision(allow=False, reason="r", dod_ref="ref", audit_note="n", guard="qa-guard")
    gh_adapter.log_decision(42, decision)
    out = capsys.readouterr().out
    assert "GOV-006 42 qa-guard BLOCKED r" in out
