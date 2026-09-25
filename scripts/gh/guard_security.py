"""Guard 3 -- Security-close guard (E01-T07 AC3).

- On `opened`/`labeled`: auto-apply the `security` label when an
  always-security `area/*` label is present (`02-definition-of-ready-done.md`
  section 8), so it cannot be omitted at creation.
- On `closed`, for any issue carrying `security` (explicit or always-security
  area): require a comment from a `@CandleViewer/security` member.
"""

from __future__ import annotations

from scripts.gh.models import Comment, Decision, Issue

GUARD_NAME = "security-guard"
DOD_REF = "02-definition-of-ready-done.md#8"

# `02-definition-of-ready-done.md` section 8: "always" security areas.
ALWAYS_SECURITY_AREAS = frozenset(
    {
        "area/auth-rbac",
        "area/oms-execution",
    }
)

SECURITY_LABEL = "security"


def _is_always_security(issue: Issue) -> bool:
    return bool(issue.labels & ALWAYS_SECURITY_AREAS) or bool(
        issue.always_security_areas
    )


def evaluate_label_sync(issue: Issue) -> Decision:
    """Run on `opened`/`labeled`: auto-apply `security` for always-security areas."""
    if SECURITY_LABEL in issue.labels:
        return Decision(
            allow=True,
            reason="security label already present",
            dod_ref=DOD_REF,
            audit_note="security-guard: label already present",
            guard=GUARD_NAME,
        )

    if not _is_always_security(issue):
        return Decision(
            allow=True,
            reason="no always-security area label present",
            dod_ref=DOD_REF,
            audit_note="security-guard: no-op (not an always-security area)",
            guard=GUARD_NAME,
        )

    return Decision(
        allow=True,
        reason="always-security area label present without explicit security label",
        dod_ref=DOD_REF,
        audit_note="security-guard: auto-applying 'security' label",
        guard=GUARD_NAME,
        add_labels=frozenset({SECURITY_LABEL}),
    )


def evaluate_close(
    issue: Issue,
    comments: list[Comment],
    *,
    team_lookup_failed: bool = False,
) -> Decision:
    """Run on `closed`: require a @CandleViewer/security member comment when
    the ticket is (explicitly or implicitly) security-labelled."""
    if not (SECURITY_LABEL in issue.labels or _is_always_security(issue)):
        return Decision(
            allow=True,
            reason="ticket is not security-labelled and touches no always-security area",
            dod_ref=DOD_REF,
            audit_note="security-guard: not applicable",
            guard=GUARD_NAME,
        )

    if team_lookup_failed:
        return Decision(
            allow=False,
            reason="could not verify @CandleViewer/security team membership (API error)",
            dod_ref=DOD_REF,
            audit_note="security-guard: BLOCKED - guard could not verify, must be re-run",
            guard=GUARD_NAME,
            fail_closed=True,
        )

    for comment in comments:
        if comment.author_is_team_member:
            return Decision(
                allow=True,
                reason=f"security sign-off comment found from @{comment.author_login}",
                dod_ref=DOD_REF,
                audit_note=f"security-guard: ALLOWED - sign-off by @{comment.author_login}",
                guard=GUARD_NAME,
            )

    return Decision(
        allow=False,
        reason="no comment from a @CandleViewer/security team member",
        dod_ref=DOD_REF,
        audit_note=(
            f"security-guard: BLOCKED - missing DoD item 'Security sign-off' (see {DOD_REF})"
        ),
        guard=GUARD_NAME,
    )
