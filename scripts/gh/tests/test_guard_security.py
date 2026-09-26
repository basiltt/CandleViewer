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


def test_close_with_write_access_signoff_comment_is_allowed() -> None:
    issue = Issue(
        number=1, kind="Task", labels=frozenset({"security"}), body="",
        owner_login="alice", actor_login="closer-dave",
    )
    comments = [Comment(author_login="sec-carol", body="Security sign-off: pass", author_has_write_access=True)]
    decision = sec.evaluate_close(issue, comments)
    assert decision.allow


def test_close_with_write_access_comment_without_marker_does_not_satisfy_guard() -> None:
    # A routine "LGTM"/approval comment from a write-access holder must not
    # silently satisfy the gate -- only the explicit marker counts.
    issue = Issue(number=1, kind="Task", labels=frozenset({"security"}), body="", owner_login="alice")
    comments = [Comment(author_login="sec-carol", body="Reviewed, approved.", author_has_write_access=True)]
    decision = sec.evaluate_close(issue, comments)
    assert not decision.allow


def test_close_not_security_related_is_not_gated() -> None:
    issue = Issue(number=1, kind="Task", labels=frozenset({"area/docs"}), body="", owner_login="alice")
    decision = sec.evaluate_close(issue, comments=[])
    assert decision.allow


def test_close_fails_closed_on_write_access_lookup_error() -> None:
    issue = Issue(number=1, kind="Task", labels=frozenset({"security"}), body="", owner_login="alice")
    decision = sec.evaluate_close(issue, comments=[], write_access_lookup_failed=True)
    assert not decision.allow
    assert decision.fail_closed


def test_close_with_marker_but_failed_write_access_check_fails_closed() -> None:
    issue = Issue(number=1, kind="Task", labels=frozenset({"security"}), body="", owner_login="alice")
    comments = [
        Comment(
            author_login="sec-carol",
            body="Security sign-off: pass",
            author_has_write_access=False,
            write_access_check_failed=True,
        )
    ]
    decision = sec.evaluate_close(issue, comments)
    assert not decision.allow
    assert decision.fail_closed



def test_closer_cannot_self_signoff_security() -> None:
    issue = Issue(
        number=1, kind="Task", labels=frozenset({"security"}), body="",
        owner_login="alice", actor_login="basiltt",
    )
    comments = [Comment(author_login="basiltt", body="Security sign-off: pass", author_has_write_access=True)]
    assert not sec.evaluate_close(issue, comments).allow


def test_unknown_closer_fails_closed() -> None:
    # ACTOR_LOGIN missing → no comment can be proven independent → block.
    issue = Issue(number=1, kind="Task", labels=frozenset({"security"}), body="", owner_login="alice")
    comments = [Comment(author_login="sec-carol", body="Security sign-off: pass", author_has_write_access=True)]
    assert not sec.evaluate_close(issue, comments).allow
