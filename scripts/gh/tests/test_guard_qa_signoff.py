from __future__ import annotations

from scripts.gh import guard_qa_signoff as qa
from scripts.gh.models import Comment, Issue


def _story(body: str = "") -> Issue:
    return Issue(
        number=1,
        kind="Story",
        labels=frozenset({"type/story"}),
        body=body,
        owner_login="alice",
    )


def test_story_without_signoff_is_blocked() -> None:
    decision = qa.evaluate(_story(), comments=[])
    assert not decision.allow
    assert "3.2" in decision.dod_ref


def test_story_with_team_member_signoff_comment_is_allowed() -> None:
    comments = [
        Comment(author_login="qa-bob", body="QA sign-off: pass", author_is_team_member=True)
    ]
    decision = qa.evaluate(_story(), comments)
    assert decision.allow


def test_forged_signoff_in_body_does_not_satisfy_guard() -> None:
    # Gherkin: "A forged sign-off in the body does not satisfy the guard"
    issue = _story(body="### Test plan\n\nQA sign-off: pass\n")
    decision = qa.evaluate(issue, comments=[])
    assert not decision.allow


def test_non_team_member_comment_with_marker_does_not_satisfy_guard() -> None:
    comments = [
        Comment(author_login="author", body="QA sign-off: pass", author_is_team_member=False)
    ]
    decision = qa.evaluate(_story(), comments)
    assert not decision.allow


def test_recorded_qa_capacity_deviation_by_owner_is_accepted() -> None:
    comments = [
        Comment(
            author_login="alice",
            body="QA capacity deviation: I ran the black-box plan myself, all pass.",
            author_is_team_member=False,
        )
    ]
    decision = qa.evaluate(_story(), comments)
    assert decision.allow
    assert "deviation" in decision.audit_note.lower()


def test_deviation_comment_from_non_owner_does_not_count() -> None:
    comments = [
        Comment(author_login="not-the-owner", body="QA capacity deviation: done.", author_is_team_member=False)
    ]
    decision = qa.evaluate(_story(), comments)
    assert not decision.allow


def test_api_error_during_team_lookup_fails_closed() -> None:
    decision = qa.evaluate(_story(), comments=[], team_lookup_failed=True)
    assert not decision.allow
    assert decision.fail_closed
    assert "could not verify" in decision.audit_note.lower()


def test_task_kind_is_not_gated() -> None:
    issue = Issue(number=2, kind="Task", labels=frozenset(), body="", owner_login="alice")
    decision = qa.evaluate(issue, comments=[])
    assert decision.allow
