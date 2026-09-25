"""Guard 4 -- a11y run-link guard (E01-T07 AC5).

On close of an `a11y`-labelled issue: require a linked axe-core CI run URL,
either in the body's `### a11y evidence` section or in a comment, validated
as pointing at *this repository's* Actions runs (not an arbitrary link).
"""

from __future__ import annotations

from scripts.gh.issue_body import find_repo_actions_run_urls, find_section
from scripts.gh.models import Comment, Decision, Issue

GUARD_NAME = "a11y-guard"
DOD_REF = "05-accessibility-standard.md#4"

A11Y_LABEL = "a11y"
A11Y_EVIDENCE_HEADING = "a11y evidence"


def evaluate(
    issue: Issue,
    comments: list[Comment],
    *,
    repo_owner: str,
    repo_name: str,
) -> Decision:
    if A11Y_LABEL not in issue.labels:
        return Decision(
            allow=True,
            reason="ticket is not a11y-labelled",
            dod_ref=DOD_REF,
            audit_note="a11y-guard: not applicable",
            guard=GUARD_NAME,
        )

    body_section = find_section(issue.body, A11Y_EVIDENCE_HEADING)
    body_links = find_repo_actions_run_urls(body_section or "", repo_owner, repo_name)
    if body_links:
        return Decision(
            allow=True,
            reason=f"valid Actions run link found in '### {A11Y_EVIDENCE_HEADING}': {body_links[0]}",
            dod_ref=DOD_REF,
            audit_note=f"a11y-guard: ALLOWED - run link {body_links[0]}",
            guard=GUARD_NAME,
        )

    for comment in comments:
        comment_links = find_repo_actions_run_urls(comment.body, repo_owner, repo_name)
        if comment_links:
            return Decision(
                allow=True,
                reason=f"valid Actions run link found in a comment: {comment_links[0]}",
                dod_ref=DOD_REF,
                audit_note=f"a11y-guard: ALLOWED - run link {comment_links[0]} (comment)",
                guard=GUARD_NAME,
            )

    return Decision(
        allow=False,
        reason=(
            f"no link to a {repo_owner}/{repo_name} Actions run found in "
            f"'### {A11Y_EVIDENCE_HEADING}' or in a comment"
        ),
        dod_ref=DOD_REF,
        audit_note=(
            f"a11y-guard: BLOCKED - missing DoD item 'a11y evidence run link' (see {DOD_REF})"
        ),
        guard=GUARD_NAME,
    )
