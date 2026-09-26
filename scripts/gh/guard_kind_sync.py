"""Guard 1 -- Kind <-> label sync (E01-T07 AC1).

Keeps the `type/*` label and the board `Kind` single-select field in
agreement. The label is treated as the observed intent (set by the issue
form / a human) and the Projects v2 `Kind` field is reconciled *to* it --
never the reverse, and never derived from the label alone pretending to be
the field (that would make this guard a no-op tautology: label vs.
label-derived-value always agree).

Requires `PROJECTS_PAT` (ADR-0017) to read/write the actual `Kind` field via
Projects v2 GraphQL, since the default `GITHUB_TOKEN` has no Projects v2
access. When `PROJECTS_PAT` is not yet provisioned (or the issue is not on
the board), this guard degrades to "no-op, project field not checked" --
logged distinctly from "in agreement" so `GOVERNANCE_ENFORCE=true` rollout is
never mistaken for having verified reconciliation it did not actually do.

Idempotent; skips when the last change was made by this workflow's own actor
(loop guard).
"""

from __future__ import annotations

from scripts.gh.models import Decision, Issue

GUARD_NAME = "kind-sync"

# type/* label <-> Kind field value mapping (issue-form default is the seed).
KIND_TO_LABEL = {
    "Epic": "type/epic",
    "Story": "type/story",
    "Task": "type/task",
    "Bug": "type/bug",
    "Spike": "type/spike",
    "Chore": "type/chore",
}
LABEL_TO_KIND = {v: k for k, v in KIND_TO_LABEL.items()}

BOT_ACTOR_LOGIN = "github-actions[bot]"


def evaluate(issue: Issue, *, project_kind: str | None, project_available: bool) -> Decision:
    """Decide whether the Projects v2 `Kind` field needs reconciling to the
    `type/*` label.

    ``allow=True`` always (this guard never blocks a close/open -- it only
    proposes a `Kind` field value to write). ``project_available=False``
    means the item could not be looked up (no `PROJECTS_PAT`, or the issue
    is not on the board) -- the guard must say so plainly rather than
    silently reporting "in agreement" for a field it never actually read.
    """
    if issue.actor_login == BOT_ACTOR_LOGIN:
        # Loop guard: never react to our own writes.
        return Decision(
            allow=True,
            reason="actor is this workflow's own bot identity; skipping to avoid a loop",
            dod_ref="01-sdlc-and-branching.md#5.2",
            audit_note="kind-sync: skipped (self-authored event)",
            guard=GUARD_NAME,
        )

    expected_label = KIND_TO_LABEL.get(issue.kind)
    if expected_label is None:
        return Decision(
            allow=True,
            reason=f"unknown Kind {issue.kind!r}; no type/* mapping, nothing to sync",
            dod_ref="01-sdlc-and-branching.md#5.2",
            audit_note="kind-sync: no-op (unmapped Kind)",
            guard=GUARD_NAME,
        )

    if not project_available:
        return Decision(
            allow=True,
            reason=(
                "Projects v2 item/field unavailable (PROJECTS_PAT not provisioned, or issue "
                "not on the board yet); Kind field was NOT checked or reconciled"
            ),
            dod_ref="01-sdlc-and-branching.md#5.2",
            audit_note="kind-sync: SKIPPED - Projects v2 Kind field not checked",
            guard=GUARD_NAME,
        )

    if project_kind == issue.kind:
        return Decision(
            allow=True,
            reason=f"Projects v2 Kind field ({project_kind!r}) already agrees with type/* label",
            dod_ref="01-sdlc-and-branching.md#5.2",
            audit_note=f"kind-sync: in agreement ({expected_label} <-> Kind={project_kind})",
            guard=GUARD_NAME,
        )

    return Decision(
        allow=True,
        reason=f"type/* label implies Kind={issue.kind!r} but Projects v2 Kind field is {project_kind!r}",
        dod_ref="01-sdlc-and-branching.md#5.2",
        audit_note=f"kind-sync: reconciling Projects v2 Kind field to {issue.kind!r}",
        guard=GUARD_NAME,
        set_project_kind=issue.kind,
    )
