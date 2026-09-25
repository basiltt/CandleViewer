"""CLI entry point for board-automation workflows (E01-T07).

Invoked from `.github/workflows/board-automation.yml` jobs. Reads the
triggering event context from environment variables (never inline
interpolation of untrusted issue content into shell), calls the appropriate
pure `evaluate()` guard, then applies (or, in observe-only mode, merely logs)
the resulting decision via the thin `gh_adapter`.

Usage:
    python -m scripts.gh.run_guard kind-sync
    python -m scripts.gh.run_guard qa-guard
    python -m scripts.gh.run_guard security-guard --mode label-sync
    python -m scripts.gh.run_guard security-guard --mode close
    python -m scripts.gh.run_guard a11y-guard

Required env vars: GH_REPO ("owner/name"), ISSUE_NUMBER, ACTOR_LOGIN.
Optional: GOVERNANCE_ENFORCE ("true"/"false", default "false" == observe-only).
"""

from __future__ import annotations

import argparse
import os
import sys

from scripts.gh import (
    gh_adapter,
    guard_a11y,
    guard_kind_sync,
    guard_qa_signoff,
    guard_security,
)
from scripts.gh.models import Decision, Issue

QA_ORG = "CandleViewer"
QA_TEAM = "qa"
SECURITY_ORG = "CandleViewer"
SECURITY_TEAM = "security"


def _enforcing() -> bool:
    return os.environ.get("GOVERNANCE_ENFORCE", "false").strip().lower() == "true"


def _with_actor(issue: Issue) -> Issue:
    from dataclasses import replace

    return replace(issue, actor_login=os.environ.get("ACTOR_LOGIN", ""))


def _check_team(repo_org: str, team: str, login: str) -> bool:
    """Returns True if lookup failed (fail-closed signal)."""
    try:
        gh_adapter.is_team_member(repo_org, team, login)
        return False
    except gh_adapter.GhApiError:
        return True


def _annotate_team_membership(comments, org: str, team: str) -> tuple[list, bool]:
    """Best-effort per-comment membership check; on any lookup failure the
    caller is told via the second return value so the guard can fail closed."""
    from dataclasses import replace

    annotated = []
    any_failure = False
    for c in comments:
        try:
            is_member = gh_adapter.is_team_member(org, team, c.author_login)
        except gh_adapter.GhApiError:
            is_member = False
            any_failure = True
        annotated.append(replace(c, author_is_team_member=is_member))
    return annotated, any_failure


def _apply_decision(repo: str, number: int, decision: Decision) -> None:
    gh_adapter.log_decision(number, decision)
    enforcing = _enforcing()
    if decision.add_labels:
        if enforcing:
            gh_adapter.add_labels(repo, number, decision.add_labels)
        else:
            print(f"GOV-006 {number} {decision.guard} OBSERVE-ONLY would-add-labels={sorted(decision.add_labels)}")
    if not decision.allow:
        if enforcing:
            gh_adapter.reopen_issue(repo, number)
            gh_adapter.post_or_update_decision_comment(repo, number, decision)
        else:
            print(f"GOV-006 {number} {decision.guard} OBSERVE-ONLY would-block: {decision.reason}")
    else:
        if enforcing:
            gh_adapter.post_or_update_decision_comment(repo, number, decision)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("guard", choices=["kind-sync", "qa-guard", "security-guard", "a11y-guard"])
    parser.add_argument("--mode", choices=["label-sync", "close"], default="close")
    args = parser.parse_args(argv)

    repo = os.environ["GH_REPO"]
    number = int(os.environ["ISSUE_NUMBER"])
    owner, name = repo.split("/", 1)

    issue, comments = gh_adapter.fetch_issue(repo, number)
    issue = _with_actor(issue)

    if args.guard == "kind-sync":
        decision = guard_kind_sync.evaluate(issue)
    elif args.guard == "qa-guard":
        annotated, failed = _annotate_team_membership(comments, QA_ORG, QA_TEAM)
        decision = guard_qa_signoff.evaluate(issue, annotated, team_lookup_failed=failed)
    elif args.guard == "security-guard":
        if args.mode == "label-sync":
            decision = guard_security.evaluate_label_sync(issue)
        else:
            annotated, failed = _annotate_team_membership(comments, SECURITY_ORG, SECURITY_TEAM)
            decision = guard_security.evaluate_close(issue, annotated, team_lookup_failed=failed)
    else:  # a11y-guard
        decision = guard_a11y.evaluate(issue, comments, repo_owner=owner, repo_name=name)

    _apply_decision(repo, number, decision)
    return 0 if decision.allow or not _enforcing() else 1


if __name__ == "__main__":
    sys.exit(main())
