"""Guard 1 -- Kind <-> label sync (E01-T07 AC1).

Keeps the `type/*` label and the board `Kind` single-select field in
agreement. Idempotent; skips when the last change was made by this
workflow's own actor (loop guard).
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


def evaluate(issue: Issue) -> Decision:
    """Decide whether the `type/*` label and `Kind` field need reconciling.

    ``allow=True`` always (this guard never blocks a close/open -- it only
    proposes a label to add so Kind and label agree). ``add_labels`` carries
    the label to apply, if any.
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

    type_labels_present = {lbl for lbl in issue.labels if lbl.startswith("type/")}

    if expected_label in type_labels_present and len(type_labels_present) == 1:
        return Decision(
            allow=True,
            reason="type/* label already agrees with Kind",
            dod_ref="01-sdlc-and-branching.md#5.2",
            audit_note=f"kind-sync: in agreement ({expected_label})",
            guard=GUARD_NAME,
        )

    return Decision(
        allow=True,
        reason=f"Kind={issue.kind} requires label {expected_label}; "
        f"current type/* labels={sorted(type_labels_present)}",
        dod_ref="01-sdlc-and-branching.md#5.2",
        audit_note=f"kind-sync: applying {expected_label}",
        guard=GUARD_NAME,
        add_labels=frozenset({expected_label}),
    )
