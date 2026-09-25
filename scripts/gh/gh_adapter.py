"""Thin GitHub-side-effects adapter for board-automation guards (E01-T07).

Every mutating call here goes through `gh` (the GitHub CLI, already
authenticated in Actions via `GH_TOKEN`) so this module has no direct HTTP
dependency and stays easy to stub in tests. Nothing in here interprets issue
body/comment content as anything other than data: content is always passed
via files or argv/environment, never interpolated into a shell string that
mixes trusted and untrusted text.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from scripts.gh.issue_body import gov_bot_marker
from scripts.gh.models import Comment, Decision, Issue

GOV_LOG_PREFIX = "GOV-006"


class GhApiError(RuntimeError):
    """Raised when a `gh` invocation fails; callers must treat this as a
    fail-closed condition, never a silent pass."""


def _run_gh(args: list[str], *, input_text: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["gh", *args],
            input=input_text,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise GhApiError(f"gh {' '.join(args)} failed: {exc}") from exc
    return result.stdout


def fetch_issue(repo: str, number: int) -> tuple[Issue, list[Comment]]:
    """Fetch the current issue state via `gh issue view --json`."""
    raw = _run_gh(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "number,body,labels,author,comments",
        ]
    )
    data = json.loads(raw)
    labels = frozenset(lbl["name"] for lbl in data.get("labels", []))
    kind = _kind_from_labels(labels)
    comments = [
        Comment(
            author_login=c["author"]["login"],
            body=c.get("body", ""),
        )
        for c in data.get("comments", [])
    ]
    issue = Issue(
        number=data["number"],
        kind=kind,
        labels=labels,
        body=data.get("body", "") or "",
        owner_login=data.get("author", {}).get("login", ""),
    )
    return issue, comments


_LABEL_TO_KIND = {
    "type/epic": "Epic",
    "type/story": "Story",
    "type/task": "Task",
    "type/bug": "Bug",
    "type/spike": "Spike",
    "type/chore": "Chore",
}


def _kind_from_labels(labels: frozenset[str]) -> str:
    for label in labels:
        if label in _LABEL_TO_KIND:
            return _LABEL_TO_KIND[label]
    return "Task"


def is_team_member(org: str, team: str, login: str) -> bool:
    """Check team membership via the GitHub API. Raises GhApiError on any
    non-2xx/network failure -- callers must treat that as fail-closed, never
    default to "not a member" silently passing through as an allow."""
    _run_gh(
        [
            "api",
            f"orgs/{org}/teams/{team}/memberships/{login}",
        ]
    )
    return True


def reopen_issue(repo: str, number: int) -> None:
    _run_gh(["issue", "reopen", str(number), "--repo", repo])


def add_labels(repo: str, number: int, labels: frozenset[str]) -> None:
    if not labels:
        return
    _run_gh(["issue", "edit", str(number), "--repo", repo, "--add-label", ",".join(sorted(labels))])


@dataclass(frozen=True)
class ExistingComment:
    comment_id: str
    body: str


def _find_own_comment(repo: str, number: int, guard: str) -> ExistingComment | None:
    marker = gov_bot_marker(guard)
    raw = _run_gh(
        ["issue", "view", str(number), "--repo", repo, "--json", "comments"]
    )
    data = json.loads(raw)
    for c in data.get("comments", []):
        if marker in c.get("body", ""):
            return ExistingComment(comment_id=c["id"], body=c["body"])
    return None


def post_or_update_decision_comment(repo: str, number: int, decision: Decision) -> None:
    """Post exactly one audit comment per guard, editing the prior one on
    re-run instead of spamming a new comment each time."""
    marker = gov_bot_marker(decision.guard)
    verdict = "ALLOWED" if decision.allow else "BLOCKED"
    body = (
        f"{marker}\n"
        f"**Board automation: {decision.guard}** -- {verdict}\n\n"
        f"{decision.audit_note}\n\n"
        f"Reason: {decision.reason}\n\n"
        f"DoD reference: {decision.dod_ref}\n"
    )
    existing = _find_own_comment(repo, number, decision.guard)
    if existing is not None:
        _run_gh(
            ["issue", "comment", str(number), "--repo", repo, "--edit-last", "--body-file", "-"],
            input_text=body,
        )
    else:
        _run_gh(
            ["issue", "comment", str(number), "--repo", repo, "--body-file", "-"],
            input_text=body,
        )


def log_decision(number: int, decision: Decision) -> None:
    """Structured workflow log line, per the ticket's Observability section."""
    print(f"{GOV_LOG_PREFIX} {number} {decision.guard} "
          f"{'ALLOWED' if decision.allow else 'BLOCKED'} {decision.reason}")
