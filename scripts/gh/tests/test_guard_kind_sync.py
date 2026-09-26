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


def test_project_kind_matches_label_is_in_agreement() -> None:
    issue = _issue("Story", frozenset({"type/story"}))
    decision = ks.evaluate(issue, project_kind="Story", project_available=True)
    assert decision.allow
    assert decision.set_project_kind is None
    assert "agrees" in decision.reason


def test_project_kind_mismatch_proposes_reconciliation() -> None:
    issue = _issue("Bug", frozenset({"type/bug"}))
    decision = ks.evaluate(issue, project_kind="Story", project_available=True)
    assert decision.allow
    assert decision.set_project_kind == "Bug"


def test_project_unavailable_is_reported_distinctly_not_as_agreement() -> None:
    issue = _issue("Task", frozenset({"type/task"}))
    decision = ks.evaluate(issue, project_kind=None, project_available=False)
    assert decision.allow
    assert decision.set_project_kind is None
    assert "SKIPPED" in decision.audit_note
    assert "not checked" in decision.audit_note


def test_self_authored_event_is_skipped_loop_guard() -> None:
    issue = _issue("Task", frozenset(), actor=ks.BOT_ACTOR_LOGIN)
    decision = ks.evaluate(issue, project_kind=None, project_available=False)
    assert decision.allow
    assert decision.set_project_kind is None
    assert "self-authored" in decision.audit_note


def test_unknown_kind_is_a_noop() -> None:
    issue = _issue("Unknown", frozenset())
    decision = ks.evaluate(issue, project_kind=None, project_available=False)
    assert decision.allow
    assert decision.set_project_kind is None
