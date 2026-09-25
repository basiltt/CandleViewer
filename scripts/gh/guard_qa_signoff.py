"""Guard 2 -- QA sign-off (E01-T07 AC1/AC2/AC4).

On close of a Story/Bug: require an actor-attributed comment from a
`@CandleViewer/qa` team member matching the documented sign-off marker
(`QA sign-off: pass`), OR an explicitly recorded QA-capacity-deviation
statement by the ticket owner (permitted by
`docs/plan/02-definition-of-ready-done.md` section 3.2 / section 8).

A forged marker typed into the *issue body* by the author never satisfies
this guard -- only an actor-attributed *comment* from a real QA team member,
or the owner's own deviation comment, counts.
"""

from __future__ import annotations

from scripts.gh.issue_body import QA_DEVIATION_MARKER_RE, QA_SIGNOFF_MARKER_RE
from scripts.gh.models import Comment, Decision, Issue

GUARD_NAME = "qa-guard"
DOD_REF = "02-definition-of-ready-done.md#3.2"

GATED_KINDS = {"Story", "Bug"}


def _qa_signoff_comment(comments: list[Comment]) -> Comment | None:
    for comment in comments:
        if not comment.author_is_team_member:
            continue
        match = QA_SIGNOFF_MARKER_RE.search(comment.body)
        if match and match.group(1).lower() == "pass":
            return comment
    return None


def _deviation_comment(comments: list[Comment], owner_login: str) -> Comment | None:
    for comment in comments:
        if comment.author_login != owner_login:
            continue
        if QA_DEVIATION_MARKER_RE.search(comment.body):
            return comment
    return None


def evaluate(
    issue: Issue,
    comments: list[Comment],
    *,
    team_lookup_failed: bool = False,
) -> Decision:
    if issue.kind not in GATED_KINDS:
        return Decision(
            allow=True,
            reason=f"Kind={issue.kind} is not Story/Bug; QA sign-off guard does not apply",
            dod_ref=DOD_REF,
            audit_note="qa-guard: not applicable",
            guard=GUARD_NAME,
        )

    if team_lookup_failed:
        # Fail-closed: an API error while checking team membership must never
        # be treated as an implicit pass.
        return Decision(
            allow=False,
            reason="could not verify @CandleViewer/qa team membership (API error)",
            dod_ref=DOD_REF,
            audit_note="qa-guard: BLOCKED - guard could not verify, must be re-run",
            guard=GUARD_NAME,
            fail_closed=True,
        )

    signoff = _qa_signoff_comment(comments)
    if signoff is not None:
        return Decision(
            allow=True,
            reason=f"QA sign-off found in comment by @{signoff.author_login}",
            dod_ref=DOD_REF,
            audit_note=f"qa-guard: ALLOWED - sign-off by @{signoff.author_login}",
            guard=GUARD_NAME,
        )

    deviation = _deviation_comment(comments, issue.owner_login)
    if deviation is not None:
        return Decision(
            allow=True,
            reason="QA capacity deviation recorded by ticket owner",
            dod_ref=DOD_REF,
            audit_note=(
                f"qa-guard: ALLOWED - QA capacity deviation path used "
                f"(recorded by @{deviation.author_login})"
            ),
            guard=GUARD_NAME,
        )

    return Decision(
        allow=False,
        reason=(
            "no actor-attributed QA sign-off comment from @CandleViewer/qa and no "
            "recorded QA capacity deviation by the ticket owner"
        ),
        dod_ref=DOD_REF,
        audit_note=(
            "qa-guard: BLOCKED - missing DoD item 'QA sign-off' "
            f"(see {DOD_REF})"
        ),
        guard=GUARD_NAME,
    )
