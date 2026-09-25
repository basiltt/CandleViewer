from __future__ import annotations

from scripts.gh import guard_kind_sync as ks
from scripts.gh.models import Issue


def _issue(kind: str, labels: frozenset[str], actor: str = "some-human") -> Issue:
    return Issue(
        number=1,
        kind=kind,
        labels=labels,
        body="",
        owner_login="alice",
        actor_login=actor,
    )


def test_matching_label_is_a_noop() -> None:
    issue = _issue("Story", frozenset({"type/story"}))
    decision = ks.evaluate(issue)
    assert decision.allow
    assert decision.add_labels == frozenset()


def test_mismatched_label_proposes_correction() -> None:
    issue = _issue("Bug", frozenset({"type/story"}))
    decision = ks.evaluate(issue)
    assert decision.allow
    assert decision.add_labels == frozenset({"type/bug"})


def test_missing_label_proposes_addition() -> None:
    issue = _issue("Task", frozenset())
    decision = ks.evaluate(issue)
    assert decision.add_labels == frozenset({"type/task"})


def test_self_authored_event_is_skipped_loop_guard() -> None:
    issue = _issue("Task", frozenset(), actor=ks.BOT_ACTOR_LOGIN)
    decision = ks.evaluate(issue)
    assert decision.allow
    assert decision.add_labels == frozenset()
    assert "self-authored" in decision.audit_note


def test_unknown_kind_is_a_noop() -> None:
    issue = _issue("Unknown", frozenset())
    decision = ks.evaluate(issue)
    assert decision.allow
    assert decision.add_labels == frozenset()
