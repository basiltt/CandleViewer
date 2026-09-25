from __future__ import annotations

from scripts.gh import guard_security as sec
from scripts.gh.models import Comment, Issue


def test_always_security_area_without_label_gets_label_applied() -> None:
    issue = Issue(number=1, kind="Task", labels=frozenset({"area/auth-rbac"}), body="", owner_login="alice")
    decision = sec.evaluate_label_sync(issue)
    assert decision.add_labels == frozenset({"security"})


def test_existing_security_label_is_a_noop_on_label_sync() -> None:
    issue = Issue(number=1, kind="Task", labels=frozenset({"area/auth-rbac", "security"}), body="", owner_login="alice")
    decision = sec.evaluate_label_sync(issue)
    assert decision.add_labels == frozenset()


def test_non_security_area_is_a_noop_on_label_sync() -> None:
    issue = Issue(number=1, kind="Task", labels=frozenset({"area/docs"}), body="", owner_login="alice")
    decision = sec.evaluate_label_sync(issue)
    assert decision.add_labels == frozenset()


def test_close_without_security_comment_is_blocked_for_always_security_area() -> None:
    issue = Issue(number=1, kind="Task", labels=frozenset({"area/oms-execution"}), body="", owner_login="alice")
    decision = sec.evaluate_close(issue, comments=[])
    assert not decision.allow


def test_close_with_security_team_comment_is_allowed() -> None:
    issue = Issue(number=1, kind="Task", labels=frozenset({"security"}), body="", owner_login="alice")
    comments = [Comment(author_login="sec-carol", body="Reviewed, approved.", author_is_team_member=True)]
    decision = sec.evaluate_close(issue, comments)
    assert decision.allow


def test_close_not_security_related_is_not_gated() -> None:
    issue = Issue(number=1, kind="Task", labels=frozenset({"area/docs"}), body="", owner_login="alice")
    decision = sec.evaluate_close(issue, comments=[])
    assert decision.allow


def test_close_fails_closed_on_team_lookup_error() -> None:
    issue = Issue(number=1, kind="Task", labels=frozenset({"security"}), body="", owner_login="alice")
    decision = sec.evaluate_close(issue, comments=[], team_lookup_failed=True)
    assert not decision.allow
    assert decision.fail_closed
